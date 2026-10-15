"""Previewable UTF-8 CSV import and deterministic export for weather observations."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TextIO
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from karuvottam.data_access import (
    DataAccess,
    WeatherObservation,
    WeatherObservationRecord,
)
from karuvottam.weather_quality import WeatherQualityReport, WeatherQualityValidator


WEATHER_CSV_COLUMNS = (
    'observed_at_utc',
    'observed_at_local',
    'temperature_c',
    'relative_humidity_pct',
    'precipitation_mm',
    'cloud_cover_pct',
    'wind_speed_kmh',
    'wind_direction_deg',
    'pressure_hpa',
    'source',
    'is_interpolated',
    'quality_flag',
    'raw_payload_reference',
    'precipitation_interval_start_utc',
    'precipitation_interval_end_utc',
    'precipitation_interval_minutes',
)

NUMERIC_FIELDS = (
    'temperature_c',
    'relative_humidity_pct',
    'precipitation_mm',
    'cloud_cover_pct',
    'wind_speed_kmh',
    'wind_direction_deg',
    'pressure_hpa',
)


class WeatherCsvError(ValueError):
    """Base error for a CSV document that cannot be processed."""


class WeatherCsvFormatError(WeatherCsvError):
    """Raised when encoding, headers, or CSV structure is invalid."""


@dataclass(frozen=True)
class CsvRowPreview:
    row_number: int
    observation: WeatherObservation | None
    quality_flag: str
    errors: tuple[str, ...]
    will_import: bool


@dataclass(frozen=True)
class WeatherCsvPreview:
    location_id: int
    total_rows: int
    accepted_rows: int
    rejected_rows: int
    rows: tuple[CsvRowPreview, ...]
    quality_report: WeatherQualityReport | None


@dataclass(frozen=True)
class WeatherCsvImportReport:
    total_rows: int
    inserted_rows: int
    existing_rows: int
    rejected_rows: int


class WeatherCsvService:
    def __init__(
        self,
        data_access: DataAccess,
        quality_validator: WeatherQualityValidator | None = None,
    ) -> None:
        self.data_access = data_access
        self.quality_validator = quality_validator or WeatherQualityValidator()

    def preview_import(
        self,
        csv_data: str | bytes | TextIO,
        *,
        location_id: int,
    ) -> WeatherCsvPreview:
        local_timezone = self._location_timezone(location_id)
        reader = self._reader(csv_data)
        parsed: list[tuple[int, WeatherObservation]] = []
        row_errors: dict[int, tuple[str, ...]] = {}
        total_rows = 0

        try:
            for row_number, row in enumerate(reader, start=2):
                total_rows += 1
                try:
                    observation = self._parse_row(
                        row,
                        location_id=location_id,
                        local_timezone=local_timezone,
                    )
                except WeatherCsvError as exc:
                    row_errors[row_number] = (str(exc),)
                else:
                    parsed.append((row_number, observation))
        except csv.Error as exc:
            raise WeatherCsvFormatError(f'invalid CSV structure: {exc}') from exc

        quality_report: WeatherQualityReport | None = None
        quality_by_row: dict[int, tuple[str, tuple[str, ...], bool]] = {}
        if parsed:
            timestamps = [item[1].observed_at_utc for item in parsed]
            expected_start = min(timestamps).astimezone(timezone.utc)
            expected_end = max(timestamps).astimezone(timezone.utc) + timedelta(hours=1)
            quality_report = self.quality_validator.validate(
                [item[1] for item in parsed],
                expected_start_utc=expected_start,
                expected_end_utc=expected_end,
            )
            for (row_number, _), result in zip(
                parsed, quality_report.records, strict=True
            ):
                quality_by_row[row_number] = (
                    result.quality_flag,
                    result.issue_codes,
                    result.rejected,
                )

        parsed_by_row = dict(parsed)
        previews: list[CsvRowPreview] = []
        for row_number in range(2, total_rows + 2):
            observation = parsed_by_row.get(row_number)
            if observation is None:
                previews.append(
                    CsvRowPreview(
                        row_number=row_number,
                        observation=None,
                        quality_flag='invalid_csv',
                        errors=row_errors[row_number],
                        will_import=False,
                    )
                )
                continue
            quality_flag, issue_codes, rejected = quality_by_row[row_number]
            validated = replace(observation, quality_flag=quality_flag)
            previews.append(
                CsvRowPreview(
                    row_number=row_number,
                    observation=validated,
                    quality_flag=quality_flag,
                    errors=issue_codes,
                    will_import=not rejected,
                )
            )

        accepted = sum(row.will_import for row in previews)
        return WeatherCsvPreview(
            location_id=location_id,
            total_rows=total_rows,
            accepted_rows=accepted,
            rejected_rows=total_rows - accepted,
            rows=tuple(previews),
            quality_report=quality_report,
        )

    def import_preview(self, preview: WeatherCsvPreview) -> WeatherCsvImportReport:
        inserted = 0
        existing = 0
        with self.data_access.transaction() as work:
            if work.locations.get(preview.location_id) is None:
                raise ValueError(f'unknown location_id: {preview.location_id}')
            for row in preview.rows:
                if not row.will_import or row.observation is None:
                    continue
                _, created = work.weather_observations.add_if_absent(row.observation)
                if created:
                    inserted += 1
                else:
                    existing += 1
        return WeatherCsvImportReport(
            total_rows=preview.total_rows,
            inserted_rows=inserted,
            existing_rows=existing,
            rejected_rows=preview.rejected_rows,
        )

    def export(
        self,
        *,
        location_id: int,
        start_utc: datetime,
        end_utc: datetime,
        source: str | None = None,
    ) -> str:
        with self.data_access.transaction() as work:
            if work.locations.get(location_id) is None:
                raise ValueError(f'unknown location_id: {location_id}')
            records = work.weather_observations.list_between(
                location_id,
                start_utc,
                end_utc,
                source=source,
            )

        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output,
            fieldnames=WEATHER_CSV_COLUMNS,
            lineterminator='\n',
            extrasaction='raise',
        )
        writer.writeheader()
        for record in records:
            writer.writerow(self._export_row(record))
        return output.getvalue()

    def _location_timezone(self, location_id: int) -> ZoneInfo:
        with self.data_access.transaction() as work:
            location = work.locations.get(location_id)
        if location is None:
            raise ValueError(f'unknown location_id: {location_id}')
        try:
            return ZoneInfo(location.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f'location {location_id} has an unavailable timezone'
            ) from exc

    @staticmethod
    def _reader(csv_data: str | bytes | TextIO) -> csv.DictReader:
        if isinstance(csv_data, bytes):
            try:
                text = csv_data.decode('utf-8-sig')
            except UnicodeDecodeError as exc:
                raise WeatherCsvFormatError('CSV must be UTF-8 encoded') from exc
            stream: TextIO = io.StringIO(text, newline='')
        elif isinstance(csv_data, str):
            stream = io.StringIO(csv_data.removeprefix('\ufeff'), newline='')
        elif hasattr(csv_data, 'read'):
            stream = csv_data
        else:
            raise TypeError('csv_data must be text, UTF-8 bytes, or a text stream')

        try:
            reader = csv.DictReader(stream, strict=True)
            fieldnames = reader.fieldnames
        except csv.Error as exc:
            raise WeatherCsvFormatError(f'invalid CSV header: {exc}') from exc
        if fieldnames is None:
            raise WeatherCsvFormatError('CSV header is required')
        fieldnames = list(fieldnames)
        fieldnames[0] = fieldnames[0].removeprefix('\ufeff')
        reader.fieldnames = fieldnames
        if len(fieldnames) != len(set(fieldnames)):
            raise WeatherCsvFormatError('CSV header contains duplicate columns')
        missing = [column for column in WEATHER_CSV_COLUMNS if column not in fieldnames]
        if missing:
            raise WeatherCsvFormatError(
                'CSV is missing required columns: ' + ', '.join(missing)
            )
        return reader

    def _parse_row(
        self,
        row: dict[str, str | None],
        *,
        location_id: int,
        local_timezone: ZoneInfo,
    ) -> WeatherObservation:
        if None in row:
            raise WeatherCsvError('row has more values than the header')
        observed_utc = self._parse_datetime(row['observed_at_utc'], 'observed_at_utc')
        observed_utc = observed_utc.astimezone(timezone.utc)
        if observed_utc.minute or observed_utc.second:
            raise WeatherCsvError('observed_at_utc must fall on an exact hour')
        observed_local = self._parse_datetime(
            row['observed_at_local'], 'observed_at_local'
        )
        expected_local = observed_utc.astimezone(local_timezone)
        if observed_local.isoformat(timespec='seconds') != expected_local.isoformat(
            timespec='seconds'
        ):
            raise WeatherCsvError(
                'observed_at_local does not match the location timezone'
            )

        source = self._required_text(row['source'], 'source')
        is_interpolated = self._parse_boolean(row['is_interpolated'])
        interval_start, interval_end, interval_minutes = self._parse_interval(
            row,
            observed_utc,
        )
        numeric_values = {
            field_name: self._parse_optional_float(row[field_name], field_name)
            for field_name in NUMERIC_FIELDS
        }
        return WeatherObservation(
            location_id=location_id,
            observed_at_utc=observed_utc,
            observed_at_local=expected_local,
            source=source,
            quality_flag='unvalidated_csv',
            is_interpolated=is_interpolated,
            raw_payload_reference=self._optional_text(row['raw_payload_reference']),
            precipitation_interval_start_utc=interval_start,
            precipitation_interval_end_utc=interval_end,
            precipitation_interval_minutes=interval_minutes,
            **numeric_values,
        )

    def _parse_interval(
        self,
        row: dict[str, str | None],
        observed_utc: datetime,
    ) -> tuple[datetime | None, datetime | None, int | None]:
        raw_start = self._optional_text(row['precipitation_interval_start_utc'])
        raw_end = self._optional_text(row['precipitation_interval_end_utc'])
        raw_minutes = self._optional_text(row['precipitation_interval_minutes'])
        values = (raw_start, raw_end, raw_minutes)
        if all(value is None for value in values):
            return None, None, None
        if any(value is None for value in values):
            raise WeatherCsvError(
                'precipitation interval fields must be provided together'
            )
        assert raw_start is not None and raw_end is not None and raw_minutes is not None
        start = self._parse_datetime(raw_start, 'precipitation_interval_start_utc')
        end = self._parse_datetime(raw_end, 'precipitation_interval_end_utc')
        try:
            minutes = int(raw_minutes)
        except ValueError as exc:
            raise WeatherCsvError(
                'precipitation_interval_minutes must be an integer'
            ) from exc
        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        if minutes <= 0:
            raise WeatherCsvError('precipitation_interval_minutes must be positive')
        if end != observed_utc:
            raise WeatherCsvError(
                'precipitation interval end must equal observed_at_utc'
            )
        if end - start != timedelta(minutes=minutes):
            raise WeatherCsvError(
                'precipitation interval duration does not match its timestamps'
            )
        return start, end, minutes

    @staticmethod
    def _parse_datetime(raw: str | None, field_name: str) -> datetime:
        value = WeatherCsvService._required_text(raw, field_name)
        iso_value = value[:-1] + '+00:00' if value.endswith('Z') else value
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError as exc:
            raise WeatherCsvError(f'{field_name} must be ISO-8601') from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise WeatherCsvError(f'{field_name} must include a timezone offset')
        if parsed.microsecond:
            raise WeatherCsvError(f'{field_name} must not contain fractional seconds')
        return parsed

    @staticmethod
    def _parse_optional_float(raw: str | None, field_name: str) -> float | None:
        value = WeatherCsvService._optional_text(raw)
        if value is None:
            return None
        try:
            return float(value)
        except ValueError as exc:
            raise WeatherCsvError(f'{field_name} must be numeric or blank') from exc

    @staticmethod
    def _parse_boolean(raw: str | None) -> bool:
        value = WeatherCsvService._required_text(raw, 'is_interpolated').lower()
        if value in {'true', '1'}:
            return True
        if value in {'false', '0'}:
            return False
        raise WeatherCsvError('is_interpolated must be true, false, 1, or 0')

    @staticmethod
    def _required_text(raw: str | None, field_name: str) -> str:
        value = WeatherCsvService._optional_text(raw)
        if value is None:
            raise WeatherCsvError(f'{field_name} is required')
        return value

    @staticmethod
    def _optional_text(raw: str | None) -> str | None:
        if raw is None:
            return None
        value = raw.strip()
        return value or None

    @staticmethod
    def _export_row(record: WeatherObservationRecord) -> dict[str, object]:
        return {
            'observed_at_utc': record.observed_at_utc,
            'observed_at_local': record.observed_at_local,
            'temperature_c': WeatherCsvService._csv_value(record.temperature_c),
            'relative_humidity_pct': WeatherCsvService._csv_value(
                record.relative_humidity_pct
            ),
            'precipitation_mm': WeatherCsvService._csv_value(
                record.precipitation_mm
            ),
            'cloud_cover_pct': WeatherCsvService._csv_value(record.cloud_cover_pct),
            'wind_speed_kmh': WeatherCsvService._csv_value(record.wind_speed_kmh),
            'wind_direction_deg': WeatherCsvService._csv_value(
                record.wind_direction_deg
            ),
            'pressure_hpa': WeatherCsvService._csv_value(record.pressure_hpa),
            'source': record.source,
            'is_interpolated': 'true' if record.is_interpolated else 'false',
            'quality_flag': record.quality_flag,
            'raw_payload_reference': record.raw_payload_reference or '',
            'precipitation_interval_start_utc': (
                record.precipitation_interval_start_utc or ''
            ),
            'precipitation_interval_end_utc': (
                record.precipitation_interval_end_utc or ''
            ),
            'precipitation_interval_minutes': WeatherCsvService._csv_value(
                record.precipitation_interval_minutes
            ),
        }

    @staticmethod
    def _csv_value(value: object | None) -> object:
        return '' if value is None else value
