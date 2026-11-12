"""Transactional repositories for Karuvottam persistence."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, TypeVar

from karuvottam.calendar_engine import CalendarRule
from karuvottam.database import connect_database
from karuvottam.event_model import EventAdvisory, EventTrackPoint, utc_timestamp
from karuvottam.lunar_events import LunarEvent
from karuvottam.windows import KaruvottamWindow


class DataAccessError(RuntimeError):
    """Base error exposed by the data-access boundary."""


class DuplicateRecordError(DataAccessError):
    """Raised when a domain identity or idempotency key already exists."""


class ConstraintViolationError(DataAccessError):
    """Raised when persisted data violates a database constraint."""


RecordT = TypeVar('RecordT')


def _created(record: RecordT | None) -> RecordT:
    if record is None:
        raise DataAccessError('created record could not be reloaded')
    return record


@dataclass(frozen=True)
class LocationRecord:
    id: int
    name: str
    latitude: float
    longitude: float
    elevation_m: float | None
    timezone_name: str
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class LocationRulesRecord:
    location_id: int
    chithirai_reference: str
    rule_version: str
    margazhi_anchor_year: int
    margazhi_anchor_phase: str


@dataclass(frozen=True)
class CalendarRuleRecord:
    id: int
    rule_name: str
    rule_version: str
    chithirai_reference_date: str
    description: str
    effective_from: str
    created_at: str


@dataclass(frozen=True)
class LunarEventRecord:
    id: int
    event_type: str
    event_datetime_utc: str
    event_datetime_local: str
    source: str
    calculation_version: str
    quality_flag: str


@dataclass(frozen=True)
class KaruvottamWindowRecord:
    id: int
    location_id: int | None
    season_type: str
    season_year: int
    start_datetime_local: str
    end_datetime_local: str
    duration_hours: float
    trigger_event_id: int | None
    rule_version: str
    status: str
    created_at: str


@dataclass(frozen=True)
class WeatherObservation:
    location_id: int
    observed_at_utc: datetime
    observed_at_local: datetime
    source: str
    quality_flag: str
    temperature_c: float | None = None
    relative_humidity_pct: float | None = None
    precipitation_mm: float | None = None
    cloud_cover_pct: float | None = None
    wind_speed_kmh: float | None = None
    wind_direction_deg: float | None = None
    pressure_hpa: float | None = None
    is_interpolated: bool = False
    raw_payload_reference: str | None = None
    precipitation_interval_start_utc: datetime | None = None
    precipitation_interval_end_utc: datetime | None = None
    precipitation_interval_minutes: int | None = None


@dataclass(frozen=True)
class WeatherObservationRecord:
    id: int
    location_id: int
    observed_at_utc: str
    observed_at_local: str
    temperature_c: float | None
    relative_humidity_pct: float | None
    precipitation_mm: float | None
    cloud_cover_pct: float | None
    wind_speed_kmh: float | None
    wind_direction_deg: float | None
    pressure_hpa: float | None
    source: str
    is_interpolated: bool
    quality_flag: str
    raw_payload_reference: str | None
    precipitation_interval_start_utc: str | None
    precipitation_interval_end_utc: str | None
    precipitation_interval_minutes: int | None


@dataclass(frozen=True)
class WeatherStationRecord:
    id: int
    location_id: int
    station_key: str
    name: str
    source_kind: str
    provider: str
    latitude: float
    longitude: float
    timezone: str
    is_active: bool
    created_at: str


@dataclass(frozen=True)
class StationReadingRecord:
    id: int
    station_id: int
    observation_id: int
    batch_id: int
    observed_at_utc: str
    recorded_at_utc: str
    row_sha256: str


@dataclass(frozen=True)
class PredictionRunRecord:
    id: int
    location_id: int | None
    season_type: str
    season_year: int
    prediction_start: str
    prediction_end: str
    input_window_id: int | None
    rule_version: str
    model_version: str
    status: str
    source_window_key: str | None
    mapping_basis_end_local: str | None
    score_model_version: str | None
    category_threshold_version: str | None
    quality_flag: str | None
    generated_at: str | None
    created_at: str


@dataclass(frozen=True)
class PredictionRecord:
    id: int
    prediction_run_id: int
    target_datetime_local: str
    rain_probability_pct: float | None
    predicted_rain_mm: float | None
    rain_category: str | None
    prediction_method: str
    model_version: str
    generated_at: str
    status: str
    research_score: float | None
    quality_flag: str | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class AuditRecord:
    id: int
    actor: str
    action: str
    record_type: str
    record_id: str | None
    reason: str
    created_at: str


@dataclass(frozen=True)
class WeatherEventRecord:
    id: int
    event_key: str
    event_type: str
    provider_classification: str
    intensity: str | None
    source: str
    source_reference: str | None
    issued_at: str
    retrieved_at: str
    center_latitude: float | None
    center_longitude: float | None
    central_pressure_hpa: float | None
    maximum_wind_kmh: float | None
    quality_flag: str
    classification_basis: str
    classification_rule_version: str | None
    source_url: str | None


@dataclass(frozen=True)
class EventTrackPointRecord:
    id: int
    weather_event_id: int
    valid_at: str
    issued_at: str | None
    latitude: float
    longitude: float
    point_type: str
    source: str
    movement_distance_km: float | None
    movement_speed_kmh: float | None
    movement_direction_deg: float | None
    target_distance_km: float | None
    quality_flag: str


@dataclass(frozen=True)
class ClimateIndexRecord:
    id: int
    index_type: str
    index_value: float
    classification: str | None
    period_start: str
    period_end: str
    issued_at: str
    provider: str
    data_version: str
    quality_flag: str
    retrieved_at: str | None
    source_url: str | None
    source_sha256: str | None
    issue_time_basis: str


def _aware_iso(value: datetime, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{field_name} must be timezone-aware')
    return value.isoformat(timespec='seconds')


def _utc_iso(value: datetime, field_name: str) -> str:
    _aware_iso(value, field_name)
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace(
        '+00:00', 'Z'
    )


def _location_from_row(row: sqlite3.Row) -> LocationRecord:
    return LocationRecord(
        id=row['id'],
        name=row['name'],
        latitude=row['latitude'],
        longitude=row['longitude'],
        elevation_m=row['elevation_m'],
        timezone_name=row['timezone'],
        is_active=bool(row['is_active']),
        created_at=row['created_at'],
    )


def _calendar_rule_from_row(row: sqlite3.Row) -> CalendarRuleRecord:
    return CalendarRuleRecord(
        id=row['id'],
        rule_name=row['rule_name'],
        rule_version=row['rule_version'],
        chithirai_reference_date=row['chithirai_reference_date'],
        description=row['description'],
        effective_from=row['effective_from'],
        created_at=row['created_at'],
    )


def _lunar_event_from_row(row: sqlite3.Row) -> LunarEventRecord:
    return LunarEventRecord(
        id=row['id'],
        event_type=row['event_type'],
        event_datetime_utc=row['event_datetime_utc'],
        event_datetime_local=row['event_datetime_local'],
        source=row['source'],
        calculation_version=row['calculation_version'],
        quality_flag=row['quality_flag'],
    )


def _window_from_row(row: sqlite3.Row) -> KaruvottamWindowRecord:
    return KaruvottamWindowRecord(
        id=row['id'],
        location_id=row['location_id'],
        season_type=row['season_type'],
        season_year=row['season_year'],
        start_datetime_local=row['start_datetime_local'],
        end_datetime_local=row['end_datetime_local'],
        duration_hours=row['duration_hours'],
        trigger_event_id=row['trigger_event_id'],
        rule_version=row['rule_version'],
        status=row['status'],
        created_at=row['created_at'],
    )


def _weather_observation_from_row(row: sqlite3.Row) -> WeatherObservationRecord:
    return WeatherObservationRecord(
        id=row['id'],
        location_id=row['location_id'],
        observed_at_utc=row['observed_at_utc'],
        observed_at_local=row['observed_at_local'],
        temperature_c=row['temperature_c'],
        relative_humidity_pct=row['relative_humidity_pct'],
        precipitation_mm=row['precipitation_mm'],
        cloud_cover_pct=row['cloud_cover_pct'],
        wind_speed_kmh=row['wind_speed_kmh'],
        wind_direction_deg=row['wind_direction_deg'],
        pressure_hpa=row['pressure_hpa'],
        source=row['source'],
        is_interpolated=bool(row['is_interpolated']),
        quality_flag=row['quality_flag'],
        raw_payload_reference=row['raw_payload_reference'],
        precipitation_interval_start_utc=row[
            'precipitation_interval_start_utc'
        ],
        precipitation_interval_end_utc=row['precipitation_interval_end_utc'],
        precipitation_interval_minutes=row['precipitation_interval_minutes'],
    )


def _prediction_run_from_row(row: sqlite3.Row) -> PredictionRunRecord:
    return PredictionRunRecord(
        id=row['id'],
        location_id=row['location_id'],
        season_type=row['season_type'],
        season_year=row['season_year'],
        prediction_start=row['prediction_start'],
        prediction_end=row['prediction_end'],
        input_window_id=row['input_window_id'],
        rule_version=row['rule_version'],
        model_version=row['model_version'],
        status=row['status'],
        source_window_key=row['source_window_key'],
        mapping_basis_end_local=row['mapping_basis_end_local'],
        score_model_version=row['score_model_version'],
        category_threshold_version=row['category_threshold_version'],
        quality_flag=row['quality_flag'],
        generated_at=row['generated_at'],
        created_at=row['created_at'],
    )


def _prediction_from_row(row: sqlite3.Row) -> PredictionRecord:
    return PredictionRecord(
        id=row['id'],
        prediction_run_id=row['prediction_run_id'],
        target_datetime_local=row['target_datetime_local'],
        rain_probability_pct=row['rain_probability_pct'],
        predicted_rain_mm=row['predicted_rain_mm'],
        rain_category=row['rain_category'],
        prediction_method=row['prediction_method'],
        model_version=row['model_version'],
        generated_at=row['generated_at'],
        status=row['status'],
        research_score=row['research_score'],
        quality_flag=row['quality_flag'],
        reason_codes=tuple(json.loads(row['reason_codes'] or '[]')),
    )


def _weather_observation_values(observation: WeatherObservation) -> tuple[object, ...]:
    _aware_iso(observation.observed_at_utc, 'observed_at_utc')
    _aware_iso(observation.observed_at_local, 'observed_at_local')
    observed_utc = observation.observed_at_utc.astimezone(timezone.utc)
    observed_local_as_utc = observation.observed_at_local.astimezone(timezone.utc)
    if observed_utc != observed_local_as_utc:
        raise ValueError(
            'observed_at_utc and observed_at_local must represent the same instant'
        )

    interval_values = (
        observation.precipitation_interval_start_utc,
        observation.precipitation_interval_end_utc,
        observation.precipitation_interval_minutes,
    )
    if any(value is None for value in interval_values) and any(
        value is not None for value in interval_values
    ):
        raise ValueError('precipitation interval fields must be provided together')

    interval_start: str | None = None
    interval_end: str | None = None
    if all(value is not None for value in interval_values):
        start = observation.precipitation_interval_start_utc
        end = observation.precipitation_interval_end_utc
        minutes = observation.precipitation_interval_minutes
        assert start is not None and end is not None and minutes is not None
        _aware_iso(start, 'precipitation_interval_start_utc')
        _aware_iso(end, 'precipitation_interval_end_utc')
        if minutes <= 0:
            raise ValueError('precipitation_interval_minutes must be positive')
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        if end_utc != observed_utc:
            raise ValueError(
                'precipitation interval end must equal observed_at_utc'
            )
        if end_utc - start_utc != timedelta(minutes=minutes):
            raise ValueError(
                'precipitation interval duration does not match its timestamps'
            )
        interval_start = _utc_iso(start, 'precipitation_interval_start_utc')
        interval_end = _utc_iso(end, 'precipitation_interval_end_utc')

    return (
        observation.location_id,
        _utc_iso(observation.observed_at_utc, 'observed_at_utc'),
        _aware_iso(observation.observed_at_local, 'observed_at_local'),
        observation.temperature_c,
        observation.relative_humidity_pct,
        observation.precipitation_mm,
        observation.cloud_cover_pct,
        observation.wind_speed_kmh,
        observation.wind_direction_deg,
        observation.pressure_hpa,
        observation.source,
        int(observation.is_interpolated),
        observation.quality_flag,
        observation.raw_payload_reference,
        interval_start,
        interval_end,
        observation.precipitation_interval_minutes,
    )


class LocationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        *,
        name: str,
        latitude: float,
        longitude: float,
        elevation_m: float | None,
        timezone_name: str,
        is_active: bool = True,
    ) -> LocationRecord:
        cursor = self._connection.execute(
            """
            INSERT INTO locations (
                name, latitude, longitude, elevation_m, timezone, is_active
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, latitude, longitude, elevation_m, timezone_name, int(is_active)),
        )
        return _created(self.get(cursor.lastrowid))

    def get(self, location_id: int) -> LocationRecord | None:
        row = self._connection.execute(
            'SELECT * FROM locations WHERE id = ?', (location_id,)
        ).fetchone()
        return None if row is None else _location_from_row(row)

    def list_active(self) -> tuple[LocationRecord, ...]:
        rows = self._connection.execute(
            'SELECT * FROM locations WHERE is_active = 1 ORDER BY name, id'
        ).fetchall()
        return tuple(_location_from_row(row) for row in rows)

    def get_active(self, location_id: int) -> LocationRecord | None:
        row = self._connection.execute(
            'SELECT * FROM locations WHERE id = ? AND is_active = 1', (location_id,)
        ).fetchone()
        return None if row is None else _location_from_row(row)

    def rules(self, location_id: int) -> LocationRulesRecord | None:
        row = self._connection.execute(
            'SELECT * FROM location_rules WHERE location_id = ?', (location_id,)
        ).fetchone()
        return None if row is None else LocationRulesRecord(**dict(row))

    def set_rules(
        self, location_id: int, *, chithirai_reference: str,
        rule_version: str, margazhi_anchor_year: int,
        margazhi_anchor_phase: str,
    ) -> LocationRulesRecord:
        if self.get_active(location_id) is None:
            raise ValueError('location_id must identify an active location')
        if not rule_version.strip() or margazhi_anchor_year < 1:
            raise ValueError('invalid location rule version or anchor year')
        if margazhi_anchor_phase not in ('new_moon', 'full_moon'):
            raise ValueError('invalid Margazhi anchor phase')
        try:
            month, day = chithirai_reference.split('-', 1)
            date(2000, int(month), int(day))
        except (TypeError, ValueError) as exc:
            raise ValueError('chithirai_reference must use MM-DD') from exc
        self._connection.execute('''
            INSERT INTO location_rules (
                location_id, chithirai_reference, rule_version,
                margazhi_anchor_year, margazhi_anchor_phase
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(location_id) DO UPDATE SET
                chithirai_reference=excluded.chithirai_reference,
                rule_version=excluded.rule_version,
                margazhi_anchor_year=excluded.margazhi_anchor_year,
                margazhi_anchor_phase=excluded.margazhi_anchor_phase
        ''', (location_id, chithirai_reference, rule_version,
              margazhi_anchor_year, margazhi_anchor_phase))
        return self.rules(location_id)

    def set_active(
        self, location_id: int, is_active: bool, *, actor: str, reason: str
    ) -> bool:
        # An unchanged value is not a manual edit and receives no audit entry.
        cursor = self._connection.execute(
            'UPDATE locations SET is_active = ? WHERE id = ? AND is_active != ?',
            (int(is_active), location_id, int(is_active)),
        )
        if cursor.rowcount == 1:
            AuditRepository(self._connection).add(
                actor=actor,
                action='location_activated' if is_active else 'location_deactivated',
                record_type='location',
                record_id=str(location_id),
                reason=reason,
            )
            return True
        return False


class CalendarRuleRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        rule: CalendarRule,
        *,
        rule_name: str,
        description: str,
        effective_from: date,
    ) -> CalendarRuleRecord:
        cursor = self._connection.execute(
            """
            INSERT INTO calendar_rules (
                rule_name, rule_version, chithirai_reference_date,
                description, effective_from
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                rule_name,
                rule.version,
                rule.reference_label,
                description,
                effective_from.isoformat(),
            ),
        )
        return _created(self.get(cursor.lastrowid))

    def get(self, rule_id: int) -> CalendarRuleRecord | None:
        row = self._connection.execute(
            'SELECT * FROM calendar_rules WHERE id = ?', (rule_id,)
        ).fetchone()
        return None if row is None else _calendar_rule_from_row(row)

    def find(self, rule_name: str, rule_version: str) -> CalendarRuleRecord | None:
        row = self._connection.execute(
            'SELECT * FROM calendar_rules WHERE rule_name = ? AND rule_version = ?',
            (rule_name, rule_version),
        ).fetchone()
        return None if row is None else _calendar_rule_from_row(row)


class LunarEventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, event: LunarEvent) -> LunarEventRecord:
        cursor = self._connection.execute(
            """
            INSERT INTO lunar_events (
                event_type, event_datetime_utc, event_datetime_local,
                source, calculation_version, quality_flag
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_type,
                _utc_iso(event.event_datetime_utc, 'event_datetime_utc'),
                _aware_iso(event.event_datetime_local, 'event_datetime_local'),
                event.source,
                event.calculation_version,
                event.quality_flag,
            ),
        )
        return _created(self.get(cursor.lastrowid))

    def get(self, event_id: int) -> LunarEventRecord | None:
        row = self._connection.execute(
            'SELECT * FROM lunar_events WHERE id = ?', (event_id,)
        ).fetchone()
        return None if row is None else _lunar_event_from_row(row)

    def find(self, event: LunarEvent) -> LunarEventRecord | None:
        row = self._connection.execute(
            'SELECT * FROM lunar_events WHERE event_type = ? AND '
            'event_datetime_utc = ? AND source = ? AND calculation_version = ?',
            (
                event.event_type,
                _utc_iso(event.event_datetime_utc, 'event_datetime_utc'),
                event.source,
                event.calculation_version,
            ),
        ).fetchone()
        return None if row is None else _lunar_event_from_row(row)


class KaruvottamWindowRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        window: KaruvottamWindow,
        *,
        trigger_event_id: int | None,
        location_id: int | None = None,
    ) -> KaruvottamWindowRecord:
        if location_id is None:
            active = LocationRepository(self._connection).list_active()
            if len(active) != 1:
                raise ValueError('location_id is required when multiple locations are active')
            location_id = active[0].id
        if LocationRepository(self._connection).get_active(location_id) is None:
            raise ValueError('location_id must identify an active location')
        cursor = self._connection.execute(
            """
            INSERT INTO karuvottam_windows (
                location_id, season_type, season_year, start_datetime_local, end_datetime_local,
                duration_hours, trigger_event_id, rule_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                location_id,
                window.season_type,
                window.season_year,
                _aware_iso(window.start_datetime_local, 'start_datetime_local'),
                _aware_iso(window.end_datetime_local, 'end_datetime_local'),
                window.duration_hours,
                trigger_event_id,
                window.rule_version,
                window.status,
            ),
        )
        return _created(self.get(cursor.lastrowid))

    def get(self, window_id: int) -> KaruvottamWindowRecord | None:
        row = self._connection.execute(
            'SELECT * FROM karuvottam_windows WHERE id = ?', (window_id,)
        ).fetchone()
        return None if row is None else _window_from_row(row)

    def find(
        self,
        season_type: str,
        season_year: int,
        rule_version: str,
        location_id: int | None = None,
    ) -> KaruvottamWindowRecord | None:
        if location_id is None:
            active = LocationRepository(self._connection).list_active()
            if not active:
                return None
            if len(active) != 1:
                raise ValueError('location_id is required when multiple locations are active')
            location_id = active[0].id
        row = self._connection.execute(
            """
            SELECT * FROM karuvottam_windows
            WHERE location_id = ? AND season_type = ? AND season_year = ? AND rule_version = ?
            """,
            (location_id, season_type, season_year, rule_version),
        ).fetchone()
        return None if row is None else _window_from_row(row)


class WeatherObservationRepository:
    _INSERT_SQL = """
        INSERT INTO weather_observations (
            location_id, observed_at_utc, observed_at_local, temperature_c,
            relative_humidity_pct, precipitation_mm, cloud_cover_pct,
            wind_speed_kmh, wind_direction_deg, pressure_hpa, source,
            is_interpolated, quality_flag, raw_payload_reference,
            precipitation_interval_start_utc, precipitation_interval_end_utc,
            precipitation_interval_minutes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, observation: WeatherObservation) -> WeatherObservationRecord:
        cursor = self._connection.execute(
            self._INSERT_SQL,
            _weather_observation_values(observation),
        )
        return _created(self.get(cursor.lastrowid))

    def add_if_absent(
        self, observation: WeatherObservation
    ) -> tuple[WeatherObservationRecord, bool]:
        cursor = self._connection.execute(
            self._INSERT_SQL
            + ' ON CONFLICT(location_id, observed_at_utc, source) DO NOTHING',
            _weather_observation_values(observation),
        )
        if cursor.rowcount == 1:
            return _created(self.get(cursor.lastrowid)), True
        existing = self.find_identity(
            observation.location_id,
            observation.observed_at_utc,
            observation.source,
        )
        return _created(existing), False

    def get(self, observation_id: int) -> WeatherObservationRecord | None:
        row = self._connection.execute(
            'SELECT * FROM weather_observations WHERE id = ?', (observation_id,)
        ).fetchone()
        return None if row is None else _weather_observation_from_row(row)

    def find_identity(
        self,
        location_id: int,
        observed_at_utc: datetime,
        source: str,
    ) -> WeatherObservationRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM weather_observations
            WHERE location_id = ? AND observed_at_utc = ? AND source = ?
            """,
            (location_id, _utc_iso(observed_at_utc, 'observed_at_utc'), source),
        ).fetchone()
        return None if row is None else _weather_observation_from_row(row)

    def latest_for_location(
        self,
        location_id: int,
        *,
        source: str | None = None,
    ) -> WeatherObservationRecord | None:
        """Return the newest stored observation for one location."""
        if location_id < 1:
            raise ValueError('location_id must be positive')
        if source is None:
            row = self._connection.execute(
                """
                SELECT * FROM weather_observations
                WHERE location_id = ?
                ORDER BY observed_at_utc DESC, id DESC
                LIMIT 1
                """,
                (location_id,),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT * FROM weather_observations
                WHERE location_id = ? AND source = ?
                ORDER BY observed_at_utc DESC, id DESC
                LIMIT 1
                """,
                (location_id, source),
            ).fetchone()
        return None if row is None else _weather_observation_from_row(row)

    def list_sources_for_location(self, location_id: int) -> tuple[str, ...]:
        """Return distinct observation sources available for one location."""
        if location_id < 1:
            raise ValueError('location_id must be positive')
        rows = self._connection.execute(
            """
            SELECT DISTINCT source FROM weather_observations
            WHERE location_id = ?
            ORDER BY source
            """,
            (location_id,),
        ).fetchall()
        return tuple(row['source'] for row in rows)

    def list_between(
        self,
        location_id: int,
        start_utc: datetime,
        end_utc: datetime,
        *,
        source: str | None = None,
    ) -> tuple[WeatherObservationRecord, ...]:
        start = _utc_iso(start_utc, 'start_utc')
        end = _utc_iso(end_utc, 'end_utc')
        if end < start:
            raise ValueError('end_utc must not precede start_utc')
        if source is None:
            rows = self._connection.execute(
                """
                SELECT * FROM weather_observations
                WHERE location_id = ? AND observed_at_utc BETWEEN ? AND ?
                ORDER BY observed_at_utc, source, id
                """,
                (location_id, start, end),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM weather_observations
                WHERE location_id = ? AND observed_at_utc BETWEEN ? AND ?
                  AND source = ?
                ORDER BY observed_at_utc, id
                """,
                (location_id, start, end, source),
            ).fetchall()
        return tuple(_weather_observation_from_row(row) for row in rows)


class WeatherStationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WeatherStationRecord:
        return WeatherStationRecord(**{**dict(row), 'is_active': bool(row['is_active'])})

    def register(self, *, location_id: int, station_key: str, name: str,
                 source_kind: str, provider: str, latitude: float,
                 longitude: float, timezone_name: str) -> WeatherStationRecord:
        location = LocationRepository(self._connection).get_active(location_id)
        if location is None:
            raise ValueError('station location must be active')
        if (abs(location.latitude - latitude) > 0.000001
                or abs(location.longitude - longitude) > 0.000001
                or location.timezone_name != timezone_name):
            raise ValueError('station coordinates and timezone must match its location')
        if source_kind not in ('station', 'iot'):
            raise ValueError('source_kind must be station or iot')
        if not station_key or not name.strip() or not provider.strip():
            raise ValueError('station key, name, and provider are required')
        cursor = self._connection.execute('''
            INSERT INTO weather_stations (
                location_id, station_key, name, source_kind, provider,
                latitude, longitude, timezone
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(location_id, station_key) DO NOTHING
        ''', (location_id, station_key, name.strip(), source_kind,
              provider.strip(), latitude, longitude, timezone_name))
        row = self._connection.execute(
            'SELECT * FROM weather_stations WHERE location_id = ? AND station_key = ?',
            (location_id, station_key),
        ).fetchone()
        record = self._from_row(row)
        if cursor.rowcount == 0 and (
            record.name != name.strip() or record.source_kind != source_kind
            or record.provider != provider.strip()
            or record.latitude != latitude or record.longitude != longitude
            or record.timezone != timezone_name
        ):
            raise DuplicateRecordError('station identity conflicts with stored metadata')
        return record

    def get(self, station_id: int) -> WeatherStationRecord | None:
        row = self._connection.execute(
            'SELECT * FROM weather_stations WHERE id = ?', (station_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def list_for_location(self, location_id: int) -> tuple[WeatherStationRecord, ...]:
        rows = self._connection.execute(
            'SELECT * FROM weather_stations WHERE location_id = ? ORDER BY name, id',
            (location_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def find_reading(self, station_id: int, observed_at_utc: datetime
                     ) -> StationReadingRecord | None:
        row = self._connection.execute('''
            SELECT * FROM station_readings
            WHERE station_id = ? AND observed_at_utc = ?
        ''', (station_id, _utc_iso(observed_at_utc, 'observed_at_utc'))).fetchone()
        return StationReadingRecord(**dict(row)) if row else None

    def record_batch(self, *, station_id: int, payload_sha256: str,
                     raw_payload_reference: str, actor: str,
                     total_rows: int, accepted_rows: int, rejected_rows: int
                     ) -> int:
        self._connection.execute('''
            INSERT INTO station_import_batches (
                station_id, payload_sha256, raw_payload_reference, actor,
                total_rows, accepted_rows, rejected_rows
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(station_id, payload_sha256) DO NOTHING
        ''', (station_id, payload_sha256, raw_payload_reference, actor,
              total_rows, accepted_rows, rejected_rows))
        row = self._connection.execute('''
            SELECT id, raw_payload_reference FROM station_import_batches
            WHERE station_id = ? AND payload_sha256 = ?
        ''', (station_id, payload_sha256)).fetchone()
        if row['raw_payload_reference'] != raw_payload_reference:
            raise DuplicateRecordError('station batch checksum conflicts with stored archive')
        return row['id']

    def add_reading(self, *, station_id: int, observation_id: int,
                    batch_id: int, observed_at_utc: datetime,
                    recorded_at_utc: datetime, row_sha256: str) -> StationReadingRecord:
        cursor = self._connection.execute('''
            INSERT INTO station_readings (
                station_id, observation_id, batch_id, observed_at_utc,
                recorded_at_utc, row_sha256
            ) VALUES (?, ?, ?, ?, ?, ?)
        ''', (station_id, observation_id, batch_id,
              _utc_iso(observed_at_utc, 'observed_at_utc'),
              _utc_iso(recorded_at_utc, 'recorded_at_utc'), row_sha256))
        row = self._connection.execute(
            'SELECT * FROM station_readings WHERE id = ?', (cursor.lastrowid,),
        ).fetchone()
        return StationReadingRecord(**dict(row))


class ForecastRepository:
    """Persist complete timeline runs and their daily outputs atomically."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_timeline(
        self,
        timeline,
        *,
        input_window_id: int,
        actor: str = 'system:forecast-generator',
        reason: str = 'Explicit forecast generation',
    ) -> PredictionRunRecord:
        if input_window_id < 1:
            raise ValueError('input_window_id must be positive')
        input_window = self._connection.execute(
            'SELECT location_id FROM karuvottam_windows WHERE id = ?',
            (input_window_id,),
        ).fetchone()
        if input_window is None or input_window['location_id'] is None:
            raise ValueError('input window must identify a location')
        cursor = self._connection.execute(
            """
            INSERT INTO prediction_runs (
                location_id, season_type, season_year, prediction_start, prediction_end,
                input_window_id, rule_version, model_version, status,
                source_window_key, mapping_basis_end_local, score_model_version,
                category_threshold_version, quality_flag, generated_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                input_window['location_id'],
                timeline.season_type,
                timeline.season_year,
                timeline.prediction_start.isoformat(),
                timeline.prediction_end.isoformat(),
                input_window_id,
                timeline.rule_version,
                timeline.timeline_model_version,
                timeline.status,
                timeline.source_window_key,
                _aware_iso(
                    timeline.mapping_basis_end_local,
                    'mapping_basis_end_local',
                ),
                timeline.score_model_version,
                timeline.category_threshold_version,
                timeline.quality_flag,
                _aware_iso(timeline.generated_at, 'generated_at'),
                'Experimental research index; not a calibrated probability.',
            ),
        )
        run_id = cursor.lastrowid
        self._connection.executemany(
            """
            INSERT INTO predictions (
                prediction_run_id, target_datetime_local,
                rain_probability_pct, predicted_rain_mm, rain_category,
                data_quality_score, prediction_method, model_version,
                generated_at, status, research_score, quality_flag,
                reason_codes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    run_id,
                    _aware_iso(entry.target_datetime_local, 'target_datetime_local'),
                    entry.rain_probability_pct,
                    entry.predicted_rain_mm,
                    entry.rain_category,
                    None,
                    entry.prediction_method,
                    entry.timeline_model_version,
                    _aware_iso(entry.generated_at, 'generated_at'),
                    entry.status,
                    entry.research_score,
                    entry.quality_flag,
                    json.dumps(entry.reason_codes, separators=(',', ':')),
                )
                for entry in timeline.entries
            ),
        )
        AuditRepository(self._connection).add(
            actor=actor,
            action='forecast_generated',
            record_type='prediction_run',
            record_id=str(run_id),
            reason=reason,
        )
        return _created(self.get_run(run_id))

    def get_run(self, run_id: int) -> PredictionRunRecord | None:
        row = self._connection.execute(
            'SELECT * FROM prediction_runs WHERE id = ?',
            (run_id,),
        ).fetchone()
        return None if row is None else _prediction_run_from_row(row)

    def latest_run(self, location_id: int | None = None) -> PredictionRunRecord | None:
        """Return the most recently generated forecast run."""
        row = self._connection.execute(
            """
            SELECT * FROM prediction_runs
            WHERE (? IS NULL OR location_id = ?)
            ORDER BY COALESCE(generated_at, created_at) DESC, id DESC
            LIMIT 1
            """,
            (location_id, location_id),
        ).fetchone()
        return None if row is None else _prediction_run_from_row(row)

    def list_entries(self, run_id: int) -> tuple[PredictionRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM predictions
            WHERE prediction_run_id = ?
            ORDER BY target_datetime_local, id
            """,
            (run_id,),
        ).fetchall()
        return tuple(_prediction_from_row(row) for row in rows)


class WeatherEventRepository:
    """Keep each source bulletin and its distinct track paths immutable."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def record_advisory(self, advisory: EventAdvisory) -> tuple[WeatherEventRecord, bool]:
        advisory.validate()
        values = (
            advisory.event_key, advisory.event_type,
            advisory.provider_classification, advisory.intensity,
            advisory.source, advisory.source_reference,
            utc_timestamp(advisory.issued_at, 'issued_at'),
            utc_timestamp(advisory.retrieved_at, 'retrieved_at'),
            advisory.center_latitude, advisory.center_longitude,
            advisory.central_pressure_hpa, advisory.maximum_wind_kmh,
            advisory.quality_flag, advisory.classification_basis,
            advisory.classification_rule_version, advisory.source_url,
        )
        cursor = self._connection.execute(
            '''INSERT INTO weather_events (
                event_key, event_type, provider_classification, intensity,
                source, source_reference, issued_at, retrieved_at,
                center_latitude, center_longitude, central_pressure_hpa,
                maximum_wind_kmh, quality_flag, classification_basis,
                classification_rule_version, source_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, event_key, issued_at) DO NOTHING''',
            values,
        )
        if cursor.rowcount == 1:
            return self.get(cursor.lastrowid), True
        existing = self.find_issue(
            advisory.source, advisory.event_key,
            utc_timestamp(advisory.issued_at, 'issued_at'),
        )
        if existing is None:
            raise DataAccessError('event advisory could not be reloaded')
        # Keep the first retrieval and CSV subset URL; later fetches may differ.
        expected = values[:7] + values[8:-1]
        actual = (
            existing.event_key, existing.event_type,
            existing.provider_classification, existing.intensity,
            existing.source, existing.source_reference, existing.issued_at,
            existing.center_latitude, existing.center_longitude,
            existing.central_pressure_hpa, existing.maximum_wind_kmh,
            existing.quality_flag, existing.classification_basis,
            existing.classification_rule_version,
        )
        if actual != expected:
            raise DuplicateRecordError('event advisory issue conflicts with stored content')
        return existing, False

    def get(self, advisory_id: int) -> WeatherEventRecord:
        row = self._connection.execute(
            'SELECT * FROM weather_events WHERE id = ?', (advisory_id,)
        ).fetchone()
        if row is None:
            raise DataAccessError('event advisory could not be reloaded')
        return WeatherEventRecord(**dict(row))

    def find_issue(
        self, source: str, event_key: str, issued_at: str
    ) -> WeatherEventRecord | None:
        row = self._connection.execute(
            'SELECT * FROM weather_events WHERE source = ? AND event_key = ? '
            'AND issued_at = ?',
            (source, event_key, issued_at),
        ).fetchone()
        return None if row is None else WeatherEventRecord(**dict(row))

    def history(self, source: str, event_key: str) -> tuple[WeatherEventRecord, ...]:
        rows = self._connection.execute(
            'SELECT * FROM weather_events WHERE source = ? AND event_key = ? '
            'ORDER BY issued_at, id',
            (source, event_key),
        ).fetchall()
        return tuple(WeatherEventRecord(**dict(row)) for row in rows)

    def latest_in_year(
        self, source: str, year: int, *, limit: int = 100
    ) -> tuple[WeatherEventRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError('limit must be between 1 and 500')
        rows = self._connection.execute(
            '''SELECT e.* FROM weather_events e
            JOIN (
                SELECT event_key, MAX(issued_at) AS last_issue
                FROM weather_events
                WHERE source = ? AND issued_at >= ? AND issued_at < ?
                GROUP BY event_key
            ) latest ON e.event_key = latest.event_key
                AND e.issued_at = latest.last_issue
            WHERE e.source = ?
            ORDER BY e.issued_at DESC, e.id DESC LIMIT ?''',
            (source, f'{year:04d}-01-01', f'{year + 1:04d}-01-01', source, limit),
        ).fetchall()
        return tuple(WeatherEventRecord(**dict(row)) for row in rows)

    def latest_year(self, source: str) -> int | None:
        row = self._connection.execute(
            'SELECT MAX(substr(issued_at, 1, 4)) AS year '
            'FROM weather_events WHERE source = ?', (source,)
        ).fetchone()
        return int(row['year']) if row['year'] is not None else None

    def event_keys_in_years(
        self, source: str, start_year: int, end_year: int,
    ) -> tuple[str, ...]:
        """Return event identities by first issue, without page-size truncation."""
        if end_year < start_year:
            raise ValueError('end_year must not precede start_year')
        rows = self._connection.execute(
            '''SELECT event_key, MIN(issued_at) AS first_issue
            FROM weather_events WHERE source = ?
            GROUP BY event_key
            HAVING first_issue >= ? AND first_issue < ?
            ORDER BY first_issue, event_key''',
            (source, f'{start_year:04d}-01-01', f'{end_year + 1:04d}-01-01'),
        ).fetchall()
        return tuple(row['event_key'] for row in rows)

    def record_point(
        self, advisory_id: int, point: EventTrackPoint
    ) -> tuple[EventTrackPointRecord, bool]:
        point.validate()
        advisory = self.get(advisory_id)
        issued_at = (
            utc_timestamp(point.issued_at, 'issued_at')
            if point.issued_at is not None else None
        )
        if issued_at is not None and issued_at != advisory.issued_at:
            raise ValueError('track point issued_at must match its advisory')
        valid_at = utc_timestamp(point.valid_at, 'valid_at')
        cursor = self._connection.execute(
            '''INSERT INTO event_track_points (
                weather_event_id, valid_at, issued_at, latitude,
                longitude, point_type, source, quality_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(weather_event_id, point_type, valid_at, source) DO NOTHING''',
            (
                advisory_id, valid_at, issued_at, point.latitude,
                point.longitude, point.point_type, point.source,
                point.quality_flag,
            ),
        )
        if cursor.rowcount == 1:
            return self.get_point(cursor.lastrowid), True
        row = self._connection.execute(
            'SELECT * FROM event_track_points WHERE weather_event_id = ? '
            'AND point_type = ? AND valid_at = ? AND source = ?',
            (advisory_id, point.point_type, valid_at, point.source),
        ).fetchone()
        if row is None:
            raise DataAccessError('event track point could not be reloaded')
        existing = EventTrackPointRecord(**dict(row))
        if (
            existing.issued_at, existing.latitude, existing.longitude,
            existing.quality_flag,
        ) != (issued_at, point.latitude, point.longitude, point.quality_flag):
            raise DuplicateRecordError('event track point conflicts with stored content')
        return existing, False

    def get_point(self, point_id: int) -> EventTrackPointRecord:
        row = self._connection.execute(
            'SELECT * FROM event_track_points WHERE id = ?', (point_id,)
        ).fetchone()
        if row is None:
            raise DataAccessError('event track point could not be reloaded')
        return EventTrackPointRecord(**dict(row))

    def points(self, advisory_id: int) -> tuple[EventTrackPointRecord, ...]:
        rows = self._connection.execute(
            'SELECT * FROM event_track_points WHERE weather_event_id = ? '
            'ORDER BY point_type, valid_at, id', (advisory_id,)
        ).fetchall()
        return tuple(EventTrackPointRecord(**dict(row)) for row in rows)


class ClimateIndexRepository:
    """Append-only monthly and three-month climate-index revisions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def has_digest(self, index_type: str, digest: str) -> bool:
        return self._connection.execute(
            'SELECT 1 FROM climate_indices WHERE index_type = ? '
            'AND source_sha256 = ? LIMIT 1', (index_type, digest),
        ).fetchone() is not None

    def record(
        self, *, index_type: str, index_value: float,
        classification: str | None, period_start: date, period_end: date,
        issued_at: datetime, retrieved_at: datetime,
        provider: str, data_version: str, quality_flag: str,
        source_url: str, source_sha256: str, issue_time_basis: str,
    ) -> tuple[ClimateIndexRecord, bool]:
        import math

        if index_type not in ('iod_dmi', 'enso_oni'):
            raise ValueError('unsupported climate index type')
        if not math.isfinite(index_value) or period_end < period_start:
            raise ValueError('invalid climate index value or period')
        for name, value in (
            ('provider', provider), ('data_version', data_version),
            ('quality_flag', quality_flag), ('source_url', source_url),
            ('source_sha256', source_sha256), ('issue_time_basis', issue_time_basis),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'{name} is required')
        issued = _utc_iso(issued_at, 'issued_at')
        retrieved = _utc_iso(retrieved_at, 'retrieved_at')
        values = (
            index_type, index_value, classification,
            period_start.isoformat(), period_end.isoformat(), issued,
            provider, data_version, quality_flag, retrieved,
            source_url, source_sha256, issue_time_basis,
        )
        cursor = self._connection.execute(
            '''INSERT INTO climate_indices (
                index_type, index_value, classification, period_start,
                period_end, issued_at, provider, data_version, quality_flag,
                retrieved_at, source_url, source_sha256, issue_time_basis
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(index_type, period_start, period_end, provider, issued_at)
            DO NOTHING''', values,
        )
        if cursor.rowcount == 1:
            return self.get(cursor.lastrowid), True
        row = self._connection.execute(
            'SELECT * FROM climate_indices WHERE index_type = ? AND '
            'period_start = ? AND period_end = ? AND provider = ? AND issued_at = ?',
            (index_type, values[3], values[4], provider, issued),
        ).fetchone()
        if row is None:
            raise DataAccessError('climate index could not be reloaded')
        existing = ClimateIndexRecord(**dict(row))
        if (
            existing.index_value, existing.classification, existing.data_version,
            existing.quality_flag, existing.source_url, existing.source_sha256,
            existing.issue_time_basis,
        ) != (
            index_value, classification, data_version, quality_flag,
            source_url, source_sha256, issue_time_basis,
        ):
            raise DuplicateRecordError('climate index revision conflicts with stored content')
        return existing, False

    def get(self, record_id: int) -> ClimateIndexRecord:
        row = self._connection.execute(
            'SELECT * FROM climate_indices WHERE id = ?', (record_id,)
        ).fetchone()
        if row is None:
            raise DataAccessError('climate index could not be reloaded')
        return ClimateIndexRecord(**dict(row))

    def latest(self, index_type: str) -> ClimateIndexRecord | None:
        row = self._connection.execute(
            'SELECT * FROM climate_indices WHERE index_type = ? '
            'ORDER BY period_end DESC, issued_at DESC, id DESC LIMIT 1',
            (index_type,),
        ).fetchone()
        return None if row is None else ClimateIndexRecord(**dict(row))

    def recent(self, index_type: str, *, limit: int = 24) -> tuple[ClimateIndexRecord, ...]:
        if not 1 <= limit <= 100:
            raise ValueError('limit must be between 1 and 100')
        rows = self._connection.execute(
            'SELECT * FROM climate_indices WHERE index_type = ? '
            'ORDER BY period_end DESC, issued_at DESC, id DESC LIMIT ?',
            (index_type, limit),
        ).fetchall()
        return tuple(ClimateIndexRecord(**dict(row)) for row in rows)


class AuditRepository:
    """Append-only, bounded audit events stored with the affected transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self, *, actor: str, action: str, record_type: str,
        record_id: str | None, reason: str,
    ) -> AuditRecord:
        for name, value, maximum in (
            ('actor', actor, 128), ('action', action, 64),
            ('record_type', record_type, 64), ('reason', reason, 500),
        ):
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise ValueError(f'{name} must be nonblank and at most {maximum} characters')
            if any(character in value for character in '\r\n\x00'):
                raise ValueError(f'{name} must not contain control characters')
        if record_id is not None and (
            not isinstance(record_id, str) or not record_id.strip()
            or len(record_id) > 128
        ):
            raise ValueError('record_id must be nonblank and at most 128 characters')
        cursor = self._connection.execute(
            'INSERT INTO audit_logs (actor, action, record_type, record_id, reason) '
            'VALUES (?, ?, ?, ?, ?)',
            (actor.strip(), action.strip(), record_type.strip(), record_id, reason.strip()),
        )
        return self.get(cursor.lastrowid)

    def get(self, audit_id: int) -> AuditRecord:
        row = self._connection.execute(
            'SELECT * FROM audit_logs WHERE id = ?', (audit_id,)
        ).fetchone()
        if row is None:
            raise DataAccessError('audit entry could not be reloaded')
        return AuditRecord(**dict(row))

    def list_recent(self, *, limit: int = 100) -> tuple[AuditRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError('limit must be between 1 and 500')
        rows = self._connection.execute(
            'SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
        return tuple(AuditRecord(**dict(row)) for row in rows)


class UnitOfWork:
    """Repositories sharing one SQLite transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.locations = LocationRepository(connection)
        self.calendar_rules = CalendarRuleRepository(connection)
        self.lunar_events = LunarEventRepository(connection)
        self.karuvottam_windows = KaruvottamWindowRepository(connection)
        self.weather_observations = WeatherObservationRepository(connection)
        self.weather_stations = WeatherStationRepository(connection)
        self.forecasts = ForecastRepository(connection)
        self.weather_events = WeatherEventRepository(connection)
        self.climate_indices = ClimateIndexRepository(connection)
        self.audit = AuditRepository(connection)


def _translate_integrity_error(error: sqlite3.IntegrityError) -> DataAccessError:
    message = str(error)
    if 'UNIQUE constraint failed' in message:
        return DuplicateRecordError('record already exists')
    return ConstraintViolationError('record violates a database constraint')


class DataAccess:
    """Create explicit commit-or-rollback units of work."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = database_path

    @contextmanager
    def transaction(self) -> Iterator[UnitOfWork]:
        try:
            connection = connect_database(self.database_path)
        except sqlite3.DatabaseError as exc:
            raise DataAccessError('unable to open the application database') from exc

        try:
            connection.execute('BEGIN')
            yield UnitOfWork(connection)
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise _translate_integrity_error(exc) from exc
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise DataAccessError('database operation failed') from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
