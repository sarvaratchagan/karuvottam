"""Transactional repositories for Karuvottam persistence."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator, TypeVar

from karuvottam.calendar_engine import CalendarRule
from karuvottam.database import connect_database
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
    )


def _weather_observation_values(observation: WeatherObservation) -> tuple[object, ...]:
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

    def set_active(self, location_id: int, is_active: bool) -> bool:
        cursor = self._connection.execute(
            'UPDATE locations SET is_active = ? WHERE id = ?',
            (int(is_active), location_id),
        )
        return cursor.rowcount == 1


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


class KaruvottamWindowRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(
        self,
        window: KaruvottamWindow,
        *,
        trigger_event_id: int | None,
    ) -> KaruvottamWindowRecord:
        cursor = self._connection.execute(
            """
            INSERT INTO karuvottam_windows (
                season_type, season_year, start_datetime_local, end_datetime_local,
                duration_hours, trigger_event_id, rule_version, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
    ) -> KaruvottamWindowRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM karuvottam_windows
            WHERE season_type = ? AND season_year = ? AND rule_version = ?
            """,
            (season_type, season_year, rule_version),
        ).fetchone()
        return None if row is None else _window_from_row(row)


class WeatherObservationRepository:
    _INSERT_SQL = """
        INSERT INTO weather_observations (
            location_id, observed_at_utc, observed_at_local, temperature_c,
            relative_humidity_pct, precipitation_mm, cloud_cover_pct,
            wind_speed_kmh, wind_direction_deg, pressure_hpa, source,
            is_interpolated, quality_flag, raw_payload_reference
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


class UnitOfWork:
    """Repositories sharing one SQLite transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.locations = LocationRepository(connection)
        self.calendar_rules = CalendarRuleRepository(connection)
        self.lunar_events = LunarEventRepository(connection)
        self.karuvottam_windows = KaruvottamWindowRepository(connection)
        self.weather_observations = WeatherObservationRepository(connection)


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
