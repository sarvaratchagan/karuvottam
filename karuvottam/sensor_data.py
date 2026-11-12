"""Provenance-preserving hourly station/IoT CSV import."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from config import settings
from karuvottam.data_access import (
    DataAccess, DuplicateRecordError, WeatherObservation, WeatherStationRecord,
)
from karuvottam.weather_quality import WeatherQualityReport, WeatherQualityValidator


STATION_KEY_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
VALUE_FIELDS = (
    'temperature_c', 'relative_humidity_pct', 'precipitation_mm',
    'cloud_cover_pct', 'wind_speed_kmh', 'wind_direction_deg', 'pressure_hpa',
)
CSV_COLUMNS = (
    'observed_at_utc', 'recorded_at_utc', *VALUE_FIELDS,
    'precipitation_interval_start_utc', 'precipitation_interval_end_utc',
    'precipitation_interval_minutes',
)
MAX_CSV_BYTES = 5_000_000
MAX_ROWS = 10_000
MAX_SPAN = timedelta(days=31)


class StationDataError(ValueError):
    """Invalid station registry entry or observation document."""


@dataclass(frozen=True)
class StationRow:
    row_number: int
    observation: WeatherObservation | None
    recorded_at_utc: datetime | None
    row_sha256: str | None
    quality_flag: str
    issues: tuple[str, ...]
    accepted: bool


@dataclass(frozen=True)
class StationPreview:
    station: WeatherStationRecord
    payload_sha256: str
    raw_payload_reference: str
    raw_payload: bytes
    rows: tuple[StationRow, ...]
    quality_report: WeatherQualityReport | None

    @property
    def accepted_rows(self) -> int:
        return sum(row.accepted for row in self.rows)

    @property
    def rejected_rows(self) -> int:
        return len(self.rows) - self.accepted_rows


@dataclass(frozen=True)
class StationImportReport:
    station_id: int
    total_rows: int
    inserted_rows: int
    existing_rows: int
    rejected_rows: int
    payload_sha256: str
    raw_payload_reference: str


def _utc_time(raw: str, field: str, *, exact_hour: bool = True) -> datetime:
    if not raw or not raw.strip():
        raise StationDataError(f'{field} is required')
    try:
        value = datetime.fromisoformat(raw.strip().replace('Z', '+00:00'))
    except ValueError as exc:
        raise StationDataError(f'{field} must be ISO-8601') from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise StationDataError(f'{field} must include a timezone offset')
    value = value.astimezone(timezone.utc)
    if exact_hour and (value.minute or value.second or value.microsecond):
        raise StationDataError(f'{field} must fall on an exact UTC hour')
    return value


def _optional_float(raw: str | None, field: str) -> float | None:
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise StationDataError(f'{field} must be numeric or blank') from exc
    if not math.isfinite(value):
        raise StationDataError(f'{field} must be finite')
    return value


class StationDataService:
    def __init__(self, access: DataAccess, raw_root: Path,
                 validator: WeatherQualityValidator | None = None) -> None:
        self.access = access
        self.raw_root = Path(raw_root)
        self.validator = validator or WeatherQualityValidator()

    def register(self, *, location_id: int, station_key: str, name: str,
                 source_kind: str, provider: str, actor: str,
                 reason: str) -> WeatherStationRecord:
        if not STATION_KEY_PATTERN.fullmatch(station_key):
            raise StationDataError('station_key must use 1–64 ASCII letters, digits, dots, underscores, or hyphens')
        if not name.strip() or len(name) > 200 or not provider.strip() or len(provider) > 200:
            raise StationDataError('station name and provider must contain 1–200 characters')
        with self.access.transaction() as work:
            location = work.locations.get_active(location_id)
            if location is None:
                raise StationDataError('location_id must identify an active location')
            existing = next((item for item in work.weather_stations.list_for_location(location_id)
                             if item.station_key == station_key), None)
            station = work.weather_stations.register(
                location_id=location_id, station_key=station_key,
                name=name, source_kind=source_kind, provider=provider,
                latitude=location.latitude, longitude=location.longitude,
                timezone_name=location.timezone_name,
            )
            if existing is None:
                work.audit.add(actor=actor, action='station_registered',
                               record_type='weather_station', record_id=str(station.id),
                               reason=reason)
            return station

    def preview_csv(self, data: bytes, *, station_id: int) -> StationPreview:
        if not isinstance(data, bytes) or not data or len(data) > MAX_CSV_BYTES:
            raise StationDataError('station CSV must be 1–5,000,000 bytes')
        with self.access.transaction() as work:
            station = work.weather_stations.get(station_id)
            if station is None or not station.is_active or work.locations.get_active(station.location_id) is None:
                raise StationDataError('station and location must be active')
        try:
            content = data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise StationDataError('station CSV must be UTF-8') from exc
        try:
            reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
            headers = reader.fieldnames
        except csv.Error as exc:
            raise StationDataError('invalid station CSV header') from exc
        if headers is None or set(headers) != set(CSV_COLUMNS) or len(headers) != len(CSV_COLUMNS):
            raise StationDataError('station CSV header must contain exactly the documented columns')
        digest = hashlib.sha256(data).hexdigest()
        reference = f'stations/{station.id}/{digest}.csv'
        rows: list[StationRow] = []
        parsed: list[tuple[int, WeatherObservation, datetime, str]] = []
        try:
            for number, source_row in enumerate(reader, start=2):
                if number > MAX_ROWS + 1:
                    raise StationDataError('station CSV exceeds 10,000 rows')
                try:
                    if None in source_row:
                        raise StationDataError('row has more values than the header')
                    observation, recorded = self._parse_row(
                        source_row, station, reference,
                    )
                    normalized = {
                        'station_id': station.id,
                        'observed_at_utc': observation.observed_at_utc.isoformat(),
                        'recorded_at_utc': recorded.isoformat(),
                        **{field: getattr(observation, field) for field in VALUE_FIELDS},
                        'precipitation_interval_start_utc': (
                            observation.precipitation_interval_start_utc.isoformat()
                            if observation.precipitation_interval_start_utc else None),
                    }
                    row_sha = hashlib.sha256(json.dumps(
                        normalized, sort_keys=True, separators=(',', ':'),
                    ).encode()).hexdigest()
                    parsed.append((number, observation, recorded, row_sha))
                except StationDataError as exc:
                    rows.append(StationRow(number, None, None, None, 'invalid_csv',
                                           (str(exc),), False))
        except csv.Error as exc:
            raise StationDataError('invalid station CSV structure') from exc
        if not rows and not parsed:
            raise StationDataError('station CSV has no readings')
        quality = None
        if parsed:
            times = [item[1].observed_at_utc for item in parsed]
            if max(times) - min(times) > MAX_SPAN:
                raise StationDataError('one station CSV may span at most 31 days')
            quality = self.validator.validate(
                [item[1] for item in parsed],
                expected_start_utc=min(times),
                expected_end_utc=max(times) + timedelta(hours=1),
            )
            for (number, observation, recorded, row_sha), result in zip(
                parsed, quality.records, strict=True,
            ):
                rows.append(StationRow(
                    number, replace(observation, quality_flag=result.quality_flag),
                    recorded, row_sha, result.quality_flag, result.issue_codes,
                    not result.rejected,
                ))
        return StationPreview(station, digest, reference, data,
                              tuple(sorted(rows, key=lambda item: item.row_number)), quality)

    @staticmethod
    def _parse_row(row: dict[str, str | None], station: WeatherStationRecord,
                   reference: str) -> tuple[WeatherObservation, datetime]:
        observed = _utc_time(row['observed_at_utc'] or '', 'observed_at_utc')
        recorded = _utc_time(row['recorded_at_utc'] or '', 'recorded_at_utc',
                             exact_hour=False)
        if recorded < observed:
            raise StationDataError('recorded_at_utc must not precede observed_at_utc')
        values = {field: _optional_float(row[field], field) for field in VALUE_FIELDS}
        if all(value is None for value in values.values()):
            raise StationDataError('at least one measured field is required')
        interval = (
            row['precipitation_interval_start_utc'],
            row['precipitation_interval_end_utc'],
            row['precipitation_interval_minutes'],
        )
        if values['precipitation_mm'] is not None:
            if any(not value or not value.strip() for value in interval):
                raise StationDataError('rainfall requires a complete accumulation interval')
            start = _utc_time(interval[0], 'precipitation_interval_start_utc')
            end = _utc_time(interval[1], 'precipitation_interval_end_utc')
            if interval[2].strip() != '60' or end != observed or end - start != timedelta(hours=1):
                raise StationDataError('rainfall interval must be the preceding 60 minutes')
        else:
            if any(value and value.strip() for value in interval):
                raise StationDataError('rainfall interval requires precipitation_mm')
            start = end = None
        return WeatherObservation(
            location_id=station.location_id,
            observed_at_utc=observed,
            observed_at_local=observed.astimezone(ZoneInfo(station.timezone)),
            source=f'station:{station.station_key}',
            quality_flag='unvalidated_station',
            raw_payload_reference=reference,
            precipitation_interval_start_utc=start,
            precipitation_interval_end_utc=end,
            precipitation_interval_minutes=60 if start else None,
            **values,
        ), recorded

    def import_csv(self, data: bytes, *, station_id: int,
                   actor: str, reason: str) -> StationImportReport:
        if not actor.strip() or not reason.strip():
            raise StationDataError('actor and reason are required')
        preview = self.preview_csv(data, station_id=station_id)
        self._archive(preview)
        inserted = existing_count = 0
        with self.access.transaction() as work:
            station = work.weather_stations.get(station_id)
            if (station != preview.station or not station.is_active
                    or work.locations.get_active(station.location_id) is None):
                raise StationDataError('station metadata changed before import')
            batch_id = work.weather_stations.record_batch(
                station_id=station_id, payload_sha256=preview.payload_sha256,
                raw_payload_reference=preview.raw_payload_reference,
                actor=actor, total_rows=len(preview.rows),
                accepted_rows=preview.accepted_rows,
                rejected_rows=preview.rejected_rows,
            )
            for row in preview.rows:
                if not row.accepted:
                    continue
                assert row.observation and row.recorded_at_utc and row.row_sha256
                earlier = work.weather_stations.find_reading(
                    station_id, row.observation.observed_at_utc,
                )
                if earlier is not None:
                    if earlier.row_sha256 != row.row_sha256:
                        raise DuplicateRecordError('station reading revision conflicts with stored values')
                    existing_count += 1
                    continue
                if work.weather_observations.find_identity(
                    station.location_id, row.observation.observed_at_utc,
                    row.observation.source,
                ) is not None:
                    raise DuplicateRecordError('station source timestamp exists without reading provenance')
                observation = work.weather_observations.add(row.observation)
                work.weather_stations.add_reading(
                    station_id=station_id, observation_id=observation.id,
                    batch_id=batch_id,
                    observed_at_utc=row.observation.observed_at_utc,
                    recorded_at_utc=row.recorded_at_utc,
                    row_sha256=row.row_sha256,
                )
                inserted += 1
            if inserted:
                work.audit.add(actor=actor, action='station_weather_imported',
                               record_type='weather_station', record_id=str(station_id),
                               reason=f'{reason} (inserted {inserted} rows)')
        return StationImportReport(station_id, len(preview.rows), inserted,
                                   existing_count, preview.rejected_rows,
                                   preview.payload_sha256,
                                   preview.raw_payload_reference)

    def _archive(self, preview: StationPreview) -> Path:
        path = self.raw_root / preview.raw_payload_reference
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != preview.payload_sha256:
                raise StationDataError('station archive checksum mismatch')
            return path
        temporary = path.with_name(f'.{uuid4().hex}.tmp')
        try:
            temporary.write_bytes(preview.raw_payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=settings.database_path)
    parser.add_argument('--raw-dir', type=Path, default=settings.weather_raw_data_dir)
    commands = parser.add_subparsers(dest='command', required=True)
    register = commands.add_parser('register')
    register.add_argument('--location-id', type=int, required=True)
    register.add_argument('--station-key', required=True)
    register.add_argument('--name', required=True)
    register.add_argument('--kind', choices=('station', 'iot'), required=True)
    register.add_argument('--provider', required=True)
    register.add_argument('--actor', required=True)
    register.add_argument('--reason', required=True)
    for command in ('preview', 'import'):
        action = commands.add_parser(command)
        action.add_argument('--station-id', type=int, required=True)
        action.add_argument('--file', type=Path, required=True)
        if command == 'import':
            action.add_argument('--actor', required=True)
            action.add_argument('--reason', required=True)
    args = parser.parse_args()
    service = StationDataService(DataAccess(args.database), args.raw_dir)
    try:
        if args.command == 'register':
            station = service.register(
                location_id=args.location_id, station_key=args.station_key,
                name=args.name, source_kind=args.kind, provider=args.provider,
                actor=args.actor, reason=args.reason,
            )
            print(json.dumps(station.__dict__, ensure_ascii=False))
            return
        data = args.file.read_bytes()
        if args.command == 'preview':
            result = service.preview_csv(data, station_id=args.station_id)
            print(json.dumps({
                'station_id': args.station_id, 'total_rows': len(result.rows),
                'accepted_rows': result.accepted_rows,
                'rejected_rows': result.rejected_rows,
                'coverage_pct': result.quality_report.coverage_pct if result.quality_report else 0,
                'rows': [{'row': row.row_number, 'quality': row.quality_flag,
                          'issues': row.issues} for row in result.rows if not row.accepted],
            }, ensure_ascii=False))
        else:
            print(json.dumps(service.import_csv(
                data, station_id=args.station_id, actor=args.actor, reason=args.reason,
            ).__dict__, ensure_ascii=False))
    except (StationDataError, DuplicateRecordError, OSError, ValueError) as exc:
        parser.exit(1, f'Station data error: {exc}\n')


if __name__ == '__main__':
    main()
