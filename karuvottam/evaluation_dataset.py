"""Reproducible multi-year Karuvottam evaluation-dataset assembly."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import fmean
from typing import Iterable, Mapping, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

from karuvottam.calendar_engine import CalendarRule
from karuvottam.data_access import (
    DataAccess,
    LocationRecord,
    WeatherObservationRecord,
)
from karuvottam.database import migrate_database
from karuvottam.forecast_timeline import (
    FORECAST_DAYS,
    TIMELINE_MODEL_VERSION,
    ForecastTimelineEngine,
    unavailable_research_score,
)
from karuvottam.lunar_events import LunarEventEngine
from karuvottam.weather_client import (
    OpenMeteoHistoricalClient,
    RawWeatherPayloadStore,
    WeatherIngestionReport,
    WeatherIngestionService,
)
from karuvottam.weather_provider import (
    selected_historical_provider,
)
from karuvottam.windows import KaruvottamWindow, KaruvottamWindowEngine


DATASET_VERSION = 'evaluation-dataset-1.0'
MEASUREMENT_CONTRACT_VERSION = 'hour-ending-precipitation-1.0'
CSV_COLUMNS = (
    'dataset_version',
    'dataset_key',
    'location_id',
    'location_name',
    'weather_source',
    'season_type',
    'season_year',
    'source_window_key',
    'source_window_start_local',
    'source_window_end_local',
    'source_window_trigger_type',
    'source_window_trigger_utc',
    'source_expected_hours',
    'source_observed_hours',
    'source_missing_hours',
    'source_interpolated_hours',
    'source_measurement_issue_hours',
    'source_coverage_pct',
    'source_quality_flag',
    'source_precipitation_mm',
    'source_mean_temperature_c',
    'source_mean_relative_humidity_pct',
    'source_mean_cloud_cover_pct',
    'source_mean_wind_speed_kmh',
    'mapping_basis_end_local',
    'target_day_number',
    'target_date_local',
    'target_expected_hours',
    'target_observed_hours',
    'target_missing_hours',
    'target_interpolated_hours',
    'target_measurement_issue_hours',
    'target_coverage_pct',
    'target_quality_flag',
    'observed_precipitation_mm',
    'calendar_rule_version',
    'timeline_model_version',
    'measurement_contract_version',
)


@dataclass(frozen=True)
class EvaluationDatasetSpec:
    location_id: int
    location_name: str
    latitude: float
    longitude: float
    timezone_name: str
    weather_source: str
    start_year: int
    end_year: int
    dataset_version: str = DATASET_VERSION

    def __post_init__(self) -> None:
        if self.location_id < 1:
            raise ValueError('location_id must be positive')
        if not self.location_name.strip():
            raise ValueError('location_name must not be blank')
        if not -90 <= self.latitude <= 90:
            raise ValueError('latitude must be between -90 and 90')
        if not -180 <= self.longitude <= 180:
            raise ValueError('longitude must be between -180 and 180')
        ZoneInfo(self.timezone_name)
        if not self.weather_source.strip():
            raise ValueError('weather_source must not be blank')
        if self.start_year < 1 or self.end_year < self.start_year:
            raise ValueError('year range is invalid')
        if not self.dataset_version.strip():
            raise ValueError('dataset_version must not be blank')

    @property
    def dataset_key(self) -> str:
        identity = {
            'dataset_version': self.dataset_version,
            'location_id': self.location_id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'timezone_name': self.timezone_name,
            'weather_source': self.weather_source,
            'start_year': self.start_year,
            'end_year': self.end_year,
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
        return f'{self.dataset_version}:{hashlib.sha256(encoded).hexdigest()[:16]}'


@dataclass(frozen=True)
class CoverageSummary:
    expected_hours: int
    observed_hours: int
    missing_hours: int
    interpolated_hours: int
    measurement_issue_hours: int
    precipitation_hours: int
    coverage_pct: float
    quality_flag: str
    precipitation_mm: float | None
    mean_temperature_c: float | None
    mean_relative_humidity_pct: float | None
    mean_cloud_cover_pct: float | None
    mean_wind_speed_kmh: float | None
    raw_payload_references: tuple[str, ...]


@dataclass(frozen=True)
class DatasetGap:
    scope: str
    source_window_key: str
    target_date_local: str | None
    first_missing_hour_end_utc: str
    last_missing_hour_end_utc: str
    missing_hours: int


@dataclass(frozen=True)
class EvaluationDatasetRow:
    values: Mapping[str, object]


@dataclass(frozen=True)
class EvaluationDatasetArtifact:
    dataset_key: str
    dataset_csv_path: Path
    gaps_csv_path: Path
    manifest_path: Path
    dataset_sha256: str
    gaps_sha256: str
    row_count: int
    complete_row_count: int
    warning_row_count: int
    no_data_row_count: int
    required_start_date: date
    required_end_date: date


@dataclass(frozen=True)
class WeatherCollectionChunk:
    start_date: date
    end_date: date
    fetched_hours: int
    inserted_hours: int
    existing_hours: int
    rejected_hours: int
    payload_sha256: str
    raw_payload_reference: str


@dataclass(frozen=True)
class WeatherCollectionReport:
    required_start_date: date
    required_end_date: date
    chunks: tuple[WeatherCollectionChunk, ...]

    @property
    def fetched_hours(self) -> int:
        return sum(chunk.fetched_hours for chunk in self.chunks)

    @property
    def inserted_hours(self) -> int:
        return sum(chunk.inserted_hours for chunk in self.chunks)

    @property
    def existing_hours(self) -> int:
        return sum(chunk.existing_hours for chunk in self.chunks)

    @property
    def rejected_hours(self) -> int:
        return sum(chunk.rejected_hours for chunk in self.chunks)


@dataclass(frozen=True)
class _SeasonContext:
    source_window: KaruvottamWindow
    mapping_basis_end_local: datetime
    target_dates: tuple[date, ...]
    source_window_key: str


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('stored observation timestamp must be timezone-aware')
    return parsed.astimezone(timezone.utc)


def _floor_hour(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _expected_interval_ends(start: datetime, end: datetime) -> tuple[datetime, ...]:
    """Return UTC hour-end labels assigned to ``(start, end]``.

    ERA5 hourly precipitation is a preceding-hour accumulation. Assigning by its
    end label preserves a stable whole-hour series when local boundaries fall at
    half past a UTC hour; the manifest makes the sub-hour boundary limitation
    explicit instead of silently claiming exact partial-hour attribution.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('aggregation bounds must be timezone-aware')
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    if end_utc <= start_utc:
        raise ValueError('aggregation end must be after start')
    first_end = _floor_hour(start_utc) + timedelta(hours=1)
    last_end = _floor_hour(end_utc)
    if first_end > last_end:
        return ()
    count = int((last_end - first_end) / timedelta(hours=1)) + 1
    return tuple(first_end + timedelta(hours=offset) for offset in range(count))


def _contiguous_gaps(
    missing: Sequence[datetime],
    *,
    scope: str,
    source_window_key: str,
    target_date: date | None,
) -> tuple[DatasetGap, ...]:
    if not missing:
        return ()
    gaps: list[DatasetGap] = []
    first = previous = missing[0]
    count = 1
    for current in missing[1:]:
        if current - previous == timedelta(hours=1):
            previous = current
            count += 1
            continue
        gaps.append(
            DatasetGap(
                scope=scope,
                source_window_key=source_window_key,
                target_date_local=target_date.isoformat() if target_date else None,
                first_missing_hour_end_utc=first.isoformat().replace('+00:00', 'Z'),
                last_missing_hour_end_utc=previous.isoformat().replace('+00:00', 'Z'),
                missing_hours=count,
            )
        )
        first = previous = current
        count = 1
    gaps.append(
        DatasetGap(
            scope=scope,
            source_window_key=source_window_key,
            target_date_local=target_date.isoformat() if target_date else None,
            first_missing_hour_end_utc=first.isoformat().replace('+00:00', 'Z'),
            last_missing_hour_end_utc=previous.isoformat().replace('+00:00', 'Z'),
            missing_hours=count,
        )
    )
    return tuple(gaps)


class EvaluationDatasetBuilder:
    """Join source windows to later observed daily rainfall without imputation."""

    def __init__(
        self,
        data_access: DataAccess,
        window_engine: KaruvottamWindowEngine,
        local_timezone: ZoneInfo,
    ) -> None:
        self.data_access = data_access
        self.window_engine = window_engine
        self.local_timezone = local_timezone
        self.timeline_engine = ForecastTimelineEngine(local_timezone)

    def build(
        self,
        spec: EvaluationDatasetSpec,
        output_directory: str | Path,
        *,
        built_at: datetime | None = None,
    ) -> EvaluationDatasetArtifact:
        if spec.timezone_name != self.local_timezone.key:
            raise ValueError('dataset timezone does not match the window engine timezone')
        contexts = self._contexts(spec.start_year, spec.end_year)
        required_start, required_end = self._required_bounds(contexts)
        query_start = datetime.combine(
            required_start, time.min, tzinfo=timezone.utc
        )
        query_end = datetime.combine(
            required_end + timedelta(days=1), time.min, tzinfo=timezone.utc
        )
        with self.data_access.transaction() as work:
            location = work.locations.get(spec.location_id)
            if location is None:
                raise ValueError(f'unknown location_id: {spec.location_id}')
            self._validate_location(spec, location)
            stored = work.weather_observations.list_between(
                spec.location_id,
                query_start,
                query_end,
                source=spec.weather_source,
            )

        records = {_parse_timestamp(record.observed_at_utc): record for record in stored}
        rows: list[EvaluationDatasetRow] = []
        gaps: list[DatasetGap] = []
        window_manifest: list[dict[str, object]] = []
        used_raw_references: set[str] = set()
        for context in contexts:
            source_summary, source_missing = self._summarize(
                context.source_window.start_datetime_local,
                context.source_window.end_datetime_local,
                records,
            )
            gaps.extend(
                _contiguous_gaps(
                    source_missing,
                    scope='source_window',
                    source_window_key=context.source_window_key,
                    target_date=None,
                )
            )
            used_raw_references.update(source_summary.raw_payload_references)
            window_manifest.append(
                self._window_manifest(context, source_summary)
            )
            for day_number, target_date in enumerate(context.target_dates, start=1):
                day_start = datetime.combine(
                    target_date,
                    time.min,
                    tzinfo=self.local_timezone,
                )
                day_summary, day_missing = self._summarize(
                    day_start,
                    day_start + timedelta(days=1),
                    records,
                )
                gaps.extend(
                    _contiguous_gaps(
                        day_missing,
                        scope='target_day',
                        source_window_key=context.source_window_key,
                        target_date=target_date,
                    )
                )
                used_raw_references.update(day_summary.raw_payload_references)
                rows.append(
                    self._row(
                        spec,
                        context,
                        source_summary,
                        target_date,
                        day_number,
                        day_summary,
                    )
                )

        csv_bytes = self._dataset_csv(rows)
        gaps_bytes = self._gaps_csv(gaps)
        dataset_digest = hashlib.sha256(csv_bytes).hexdigest()
        gaps_digest = hashlib.sha256(gaps_bytes).hexdigest()
        output = Path(output_directory)
        output.mkdir(parents=True, exist_ok=True)
        csv_path = output / 'evaluation_dataset.csv'
        gaps_path = output / 'data_gaps.csv'
        manifest_path = output / 'manifest.json'
        self._write_atomic(csv_path, csv_bytes)
        self._write_atomic(gaps_path, gaps_bytes)

        quality_counts = {
            flag: sum(
                row.values['target_quality_flag'] == flag for row in rows
            )
            for flag in ('complete', 'warning', 'no_data')
        }
        built_value = built_at or datetime.now(timezone.utc)
        if built_value.tzinfo is None or built_value.utcoffset() is None:
            raise ValueError('built_at must be timezone-aware')
        built = built_value.astimezone(timezone.utc)
        raw_references = sorted(used_raw_references)
        manifest = {
            'dataset_version': spec.dataset_version,
            'dataset_key': spec.dataset_key,
            'built_at_utc': built.isoformat().replace('+00:00', 'Z'),
            'location': {
                'id': spec.location_id,
                'name': spec.location_name,
                'latitude': spec.latitude,
                'longitude': spec.longitude,
                'timezone': spec.timezone_name,
            },
            'weather_source': spec.weather_source,
            'season_year_range': {
                'start': spec.start_year,
                'end': spec.end_year,
            },
            'required_weather_date_range_utc': {
                'start': required_start.isoformat(),
                'end': required_end.isoformat(),
            },
            'contracts': {
                'calendar_rule_version': self.window_engine.calendar_rule.version,
                'timeline_model_version': TIMELINE_MODEL_VERSION,
                'measurement_contract_version': MEASUREMENT_CONTRACT_VERSION,
                'forecast_days': FORECAST_DAYS,
            },
            'transformations': [
                'Source windows use timezone-aware half-open [start,end) bounds.',
                'Preceding-hour precipitation is assigned by its UTC hour-end label using (start,end] bounds.',
                'Daily outcomes use Asia/Kolkata midnight-to-midnight bounds.',
                'Missing hours are retained as gaps; no interpolation or zero filling is performed.',
                'Interpolated source records remain included but are counted and flagged.',
            ],
            'measurement_notes': [
                'ERA5 is gridded reanalysis, not a rain-gauge measurement.',
                'Hourly precipitation is interpreted as the preceding 60-minute accumulation.',
                'When a local/window boundary cuts a UTC hour, end-label assignment can shift at most one boundary hour; no fractional rainfall is invented.',
                'Only one explicitly selected provider/model source is joined per build.',
            ],
            'rows': {
                'total': len(rows),
                'complete': quality_counts['complete'],
                'warning': quality_counts['warning'],
                'no_data': quality_counts['no_data'],
            },
            'files': {
                csv_path.name: {'sha256': dataset_digest},
                gaps_path.name: {'sha256': gaps_digest, 'gap_ranges': len(gaps)},
            },
            'raw_payload_references': raw_references,
            'windows': window_manifest,
        }
        self._write_atomic(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(),
        )
        return EvaluationDatasetArtifact(
            dataset_key=spec.dataset_key,
            dataset_csv_path=csv_path,
            gaps_csv_path=gaps_path,
            manifest_path=manifest_path,
            dataset_sha256=dataset_digest,
            gaps_sha256=gaps_digest,
            row_count=len(rows),
            complete_row_count=quality_counts['complete'],
            warning_row_count=quality_counts['warning'],
            no_data_row_count=quality_counts['no_data'],
            required_start_date=required_start,
            required_end_date=required_end,
        )

    def required_weather_range(self, start_year: int, end_year: int) -> tuple[date, date]:
        if start_year < 1 or end_year < start_year:
            raise ValueError('year range is invalid')
        return self._required_bounds(self._contexts(start_year, end_year))

    def _contexts(self, start_year: int, end_year: int) -> tuple[_SeasonContext, ...]:
        windows = {
            (season, year): self.window_engine.generate(season, year)
            for year in range(start_year, end_year + 2)
            for season in ('aadi', 'margazhi')
        }
        contexts: list[_SeasonContext] = []
        generated_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        for year in range(start_year, end_year + 1):
            for season in ('aadi', 'margazhi'):
                source = windows[(season, year)]
                mapping_end = (
                    windows[('margazhi', year)].end_datetime_local
                    if season == 'aadi'
                    else windows[('aadi', year + 1)].end_datetime_local
                )
                timeline = self.timeline_engine.generate(
                    source,
                    mapping_basis_end_local=mapping_end,
                    research_score=unavailable_research_score(
                        'evaluation_dataset_assembly'
                    ),
                    generated_at=generated_at,
                )
                contexts.append(
                    _SeasonContext(
                        source_window=source,
                        mapping_basis_end_local=mapping_end,
                        target_dates=tuple(entry.target_date for entry in timeline.entries),
                        source_window_key=timeline.source_window_key,
                    )
                )
        return tuple(contexts)

    @staticmethod
    def _required_bounds(contexts: Sequence[_SeasonContext]) -> tuple[date, date]:
        local_instants = [
            instant.astimezone(timezone.utc).date()
            for context in contexts
            for instant in (
                context.source_window.start_datetime_local,
                context.source_window.end_datetime_local,
            )
        ]
        target_dates = [day for context in contexts for day in context.target_dates]
        if not contexts or not target_dates:
            raise ValueError('at least one season context is required')
        # One UTC date of padding captures local-midnight intervals crossing UTC dates.
        return min(local_instants + target_dates) - timedelta(days=1), max(
            local_instants + target_dates
        ) + timedelta(days=1)

    @staticmethod
    def _validate_location(spec: EvaluationDatasetSpec, location: LocationRecord) -> None:
        if (
            location.name != spec.location_name
            or location.latitude != spec.latitude
            or location.longitude != spec.longitude
            or location.timezone_name != spec.timezone_name
        ):
            raise ValueError('dataset location metadata does not match the database')

    @staticmethod
    def _summarize(
        start: datetime,
        end: datetime,
        records: Mapping[datetime, WeatherObservationRecord],
    ) -> tuple[CoverageSummary, tuple[datetime, ...]]:
        expected = _expected_interval_ends(start, end)
        selected = [records[stamp] for stamp in expected if stamp in records]
        missing = tuple(stamp for stamp in expected if stamp not in records)
        measurement_issues = 0
        precipitation_values: list[float] = []
        for record in selected:
            observed_end = _parse_timestamp(record.observed_at_utc)
            expected_start = observed_end - timedelta(hours=1)
            compatible = (
                record.precipitation_interval_minutes == 60
                and record.precipitation_interval_start_utc is not None
                and record.precipitation_interval_end_utc is not None
                and _parse_timestamp(record.precipitation_interval_start_utc)
                == expected_start
                and _parse_timestamp(record.precipitation_interval_end_utc)
                == observed_end
            )
            if not compatible:
                measurement_issues += 1
            elif record.precipitation_mm is not None:
                precipitation_values.append(record.precipitation_mm)

        expected_count = len(expected)
        observed_count = len(selected)
        coverage = round(observed_count / expected_count * 100, 2) if expected_count else 0.0
        interpolated = sum(record.is_interpolated for record in selected)
        if observed_count == 0:
            quality = 'no_data'
        elif (
            missing
            or measurement_issues
            or len(precipitation_values) != expected_count
            or interpolated
        ):
            quality = 'warning'
        else:
            quality = 'complete'

        def mean(field_name: str) -> float | None:
            values = [
                value
                for record in selected
                for value in (getattr(record, field_name),)
                if value is not None
            ]
            return round(fmean(values), 6) if values else None

        return (
            CoverageSummary(
                expected_hours=expected_count,
                observed_hours=observed_count,
                missing_hours=len(missing),
                interpolated_hours=interpolated,
                measurement_issue_hours=measurement_issues,
                precipitation_hours=len(precipitation_values),
                coverage_pct=coverage,
                quality_flag=quality,
                precipitation_mm=(
                    round(sum(precipitation_values), 6)
                    if precipitation_values
                    else None
                ),
                mean_temperature_c=mean('temperature_c'),
                mean_relative_humidity_pct=mean('relative_humidity_pct'),
                mean_cloud_cover_pct=mean('cloud_cover_pct'),
                mean_wind_speed_kmh=mean('wind_speed_kmh'),
                raw_payload_references=tuple(
                    sorted(
                        {
                            record.raw_payload_reference
                            for record in selected
                            if record.raw_payload_reference
                        }
                    )
                ),
            ),
            missing,
        )

    def _row(
        self,
        spec: EvaluationDatasetSpec,
        context: _SeasonContext,
        source: CoverageSummary,
        target_date: date,
        day_number: int,
        target: CoverageSummary,
    ) -> EvaluationDatasetRow:
        window = context.source_window
        return EvaluationDatasetRow(
            {
                'dataset_version': spec.dataset_version,
                'dataset_key': spec.dataset_key,
                'location_id': spec.location_id,
                'location_name': spec.location_name,
                'weather_source': spec.weather_source,
                'season_type': window.season_type,
                'season_year': window.season_year,
                'source_window_key': context.source_window_key,
                'source_window_start_local': window.start_datetime_local.isoformat(),
                'source_window_end_local': window.end_datetime_local.isoformat(),
                'source_window_trigger_type': window.trigger_event.event_type,
                'source_window_trigger_utc': window.trigger_event.event_datetime_utc.isoformat().replace('+00:00', 'Z'),
                'source_expected_hours': source.expected_hours,
                'source_observed_hours': source.observed_hours,
                'source_missing_hours': source.missing_hours,
                'source_interpolated_hours': source.interpolated_hours,
                'source_measurement_issue_hours': source.measurement_issue_hours,
                'source_coverage_pct': source.coverage_pct,
                'source_quality_flag': source.quality_flag,
                'source_precipitation_mm': source.precipitation_mm,
                'source_mean_temperature_c': source.mean_temperature_c,
                'source_mean_relative_humidity_pct': source.mean_relative_humidity_pct,
                'source_mean_cloud_cover_pct': source.mean_cloud_cover_pct,
                'source_mean_wind_speed_kmh': source.mean_wind_speed_kmh,
                'mapping_basis_end_local': context.mapping_basis_end_local.isoformat(),
                'target_day_number': day_number,
                'target_date_local': target_date.isoformat(),
                'target_expected_hours': target.expected_hours,
                'target_observed_hours': target.observed_hours,
                'target_missing_hours': target.missing_hours,
                'target_interpolated_hours': target.interpolated_hours,
                'target_measurement_issue_hours': target.measurement_issue_hours,
                'target_coverage_pct': target.coverage_pct,
                'target_quality_flag': target.quality_flag,
                'observed_precipitation_mm': target.precipitation_mm,
                'calendar_rule_version': window.rule_version,
                'timeline_model_version': TIMELINE_MODEL_VERSION,
                'measurement_contract_version': MEASUREMENT_CONTRACT_VERSION,
            }
        )

    @staticmethod
    def _window_manifest(
        context: _SeasonContext,
        summary: CoverageSummary,
    ) -> dict[str, object]:
        window = context.source_window
        return {
            'source_window_key': context.source_window_key,
            'season_type': window.season_type,
            'season_year': window.season_year,
            'start_local': window.start_datetime_local.isoformat(),
            'end_local': window.end_datetime_local.isoformat(),
            'duration_hours': window.duration_hours,
            'mapping_basis_end_local': context.mapping_basis_end_local.isoformat(),
            'target_start_date': context.target_dates[0].isoformat(),
            'target_end_date': context.target_dates[-1].isoformat(),
            'trigger_event': {
                'type': window.trigger_event.event_type,
                'datetime_utc': window.trigger_event.event_datetime_utc.isoformat().replace('+00:00', 'Z'),
                'datetime_local': window.trigger_event.event_datetime_local.isoformat(),
                'source': window.trigger_event.source,
                'calculation_version': window.trigger_event.calculation_version,
            },
            'source_summary': asdict(summary),
        }

    @staticmethod
    def _dataset_csv(rows: Sequence[EvaluationDatasetRow]) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator='\n')
        writer.writeheader()
        for row in rows:
            writer.writerow(row.values)
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _gaps_csv(gaps: Sequence[DatasetGap]) -> bytes:
        output = io.StringIO(newline='')
        fields = tuple(DatasetGap.__dataclass_fields__)
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        for gap in gaps:
            writer.writerow(asdict(gap))
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary = path.parent / f'.{path.name}.{uuid4().hex}.tmp'
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class MultiYearWeatherCollector:
    """Fetch a planned historical range in bounded, retryable chunks."""

    def __init__(
        self,
        ingestion_service: WeatherIngestionService,
        dataset_builder: EvaluationDatasetBuilder,
        *,
        chunk_days: int = 366,
    ) -> None:
        if chunk_days < 1:
            raise ValueError('chunk_days must be positive')
        self.ingestion_service = ingestion_service
        self.dataset_builder = dataset_builder
        self.chunk_days = chunk_days

    def collect(self, spec: EvaluationDatasetSpec) -> WeatherCollectionReport:
        start, end = self.dataset_builder.required_weather_range(
            spec.start_year, spec.end_year
        )
        chunks = []
        for chunk_start, chunk_end in self._chunks(start, end):
            report = self.ingestion_service.ingest(
                location_id=spec.location_id,
                latitude=spec.latitude,
                longitude=spec.longitude,
                start_date=chunk_start,
                end_date=chunk_end,
            )
            chunks.append(self._chunk_report(chunk_start, chunk_end, report))
        return WeatherCollectionReport(start, end, tuple(chunks))

    def _chunks(self, start: date, end: date) -> Iterable[tuple[date, date]]:
        current = start
        while current <= end:
            chunk_end = min(end, current + timedelta(days=self.chunk_days - 1))
            yield current, chunk_end
            current = chunk_end + timedelta(days=1)

    @staticmethod
    def _chunk_report(
        start: date,
        end: date,
        report: WeatherIngestionReport,
    ) -> WeatherCollectionChunk:
        return WeatherCollectionChunk(
            start_date=start,
            end_date=end,
            fetched_hours=report.fetched_hours,
            inserted_hours=report.inserted_hours,
            existing_hours=report.existing_hours,
            rejected_hours=report.rejected_hours,
            payload_sha256=report.payload_sha256,
            raw_payload_reference=report.raw_payload_reference,
        )


def _configured_services():
    from config import settings

    migrate_database(settings.database_path)
    data_access = DataAccess(settings.database_path)
    with data_access.transaction() as work:
        matches = [
            location
            for location in work.locations.list_active()
            if location.name == settings.location_name
            and location.latitude == settings.latitude
            and location.longitude == settings.longitude
            and location.timezone_name == settings.timezone_name
        ]
        if matches:
            location = matches[0]
        else:
            location = work.locations.add(
                name=settings.location_name,
                latitude=settings.latitude,
                longitude=settings.longitude,
                elevation_m=settings.elevation_m,
                timezone_name=settings.timezone_name,
            )
    reference_month, reference_day = settings.chithirai_reference_parts
    rule = CalendarRule(
        reference_month=reference_month,
        reference_day=reference_day,
        version=settings.calendar_rule_version,
    )
    window_engine = KaruvottamWindowEngine(
        rule,
        LunarEventEngine(settings.timezone),
        settings.margazhi_alternation_anchor_year,
        settings.margazhi_alternation_anchor_phase,
    )
    builder = EvaluationDatasetBuilder(data_access, window_engine, settings.timezone)
    provider = selected_historical_provider(
        settings.weather_provider,
        settings.weather_model,
        settings.weather_api_base_url,
    )
    ingestion = WeatherIngestionService(
        OpenMeteoHistoricalClient(
            provider,
            api_key=settings.weather_api_key,
            timeout_seconds=settings.weather_timeout_seconds,
            max_attempts=settings.weather_retry_attempts,
            retry_backoff_seconds=settings.weather_retry_backoff_seconds,
        ),
        data_access,
        RawWeatherPayloadStore(settings.weather_raw_data_dir),
    )
    spec_factory = lambda start, end: EvaluationDatasetSpec(
        location_id=location.id,
        location_name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        timezone_name=location.timezone_name,
        weather_source=f'{provider.key}:{provider.model}',
        start_year=start,
        end_year=end,
    )
    return builder, ingestion, provider, spec_factory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Collect and build a reproducible Karuvottam evaluation dataset'
    )
    parser.add_argument('command', choices=('plan', 'collect', 'build', 'assemble'))
    parser.add_argument('--start-year', type=int, required=True)
    parser.add_argument('--end-year', type=int, required=True)
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('data/exports/evaluation-dataset'),
    )
    parser.add_argument('--chunk-days', type=int, default=366)
    return parser


def main() -> None:
    args = _parser().parse_args()
    builder, ingestion, provider, spec_factory = _configured_services()
    spec = spec_factory(args.start_year, args.end_year)
    start, end = builder.required_weather_range(spec.start_year, spec.end_year)
    if args.command == 'plan':
        print(
            json.dumps(
                {
                    'dataset_key': spec.dataset_key,
                    'provider': provider.display_name,
                    'required_start_date': start.isoformat(),
                    'required_end_date': end.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command in {'collect', 'assemble'}:
        report = MultiYearWeatherCollector(
            ingestion,
            builder,
            chunk_days=args.chunk_days,
        ).collect(spec)
        print(
            f'Collected {report.fetched_hours} hours: '
            f'{report.inserted_hours} inserted, {report.existing_hours} existing, '
            f'{report.rejected_hours} rejected.'
        )
    if args.command in {'build', 'assemble'}:
        artifact = builder.build(spec, args.output)
        print(
            f'Built {artifact.row_count} rows at {artifact.dataset_csv_path}; '
            f'sha256={artifact.dataset_sha256}'
        )


if __name__ == '__main__':
    main()
