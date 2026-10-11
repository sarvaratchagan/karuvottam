from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.calendar_engine import CalendarRule
from karuvottam.data_access import (
    ConstraintViolationError,
    DataAccess,
    DataAccessError,
    DuplicateRecordError,
    WeatherObservation,
)
from karuvottam.database import migrate_database
from karuvottam.lunar_events import LunarEvent
from karuvottam.sunrise import SunriseResult
from karuvottam.windows import KaruvottamWindow


LOCAL_TIMEZONE = ZoneInfo('Asia/Kolkata')


@pytest.fixture
def data_access(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)
    return DataAccess(database_path)


def _lunar_event() -> LunarEvent:
    event_utc = datetime(2026, 7, 14, 9, 13, tzinfo=timezone.utc)
    return LunarEvent(
        event_type='new_moon',
        event_datetime_utc=event_utc,
        event_datetime_local=event_utc.astimezone(LOCAL_TIMEZONE),
        source='test-provider',
        calculation_version='1.0',
    )


def _window(event: LunarEvent) -> KaruvottamWindow:
    start = datetime(2026, 7, 18, 6, 1, tzinfo=LOCAL_TIMEZONE)
    sunrise = SunriseResult(
        target_local_date=start.date(),
        sunrise_datetime_utc=start.astimezone(timezone.utc),
        sunrise_datetime_local=start,
        latitude=9.9040188,
        longitude=77.8860417,
        elevation_m=0,
        source='test-provider',
        calculation_version='1.0',
    )
    return KaruvottamWindow(
        season_type='aadi',
        season_year=2026,
        start_datetime_local=start,
        end_datetime_local=start + timedelta(days=18),
        duration_hours=432,
        trigger_event=event,
        sunrise=sunrise,
        rule_version='1.0',
    )


def test_core_repositories_commit_and_read_records(data_access):
    rule = CalendarRule()
    event = _lunar_event()

    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9040188,
            longitude=77.8860417,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        stored_rule = work.calendar_rules.add(
            rule,
            rule_name='modified-tamil-calendar',
            description='March 21 is Chithirai 1',
            effective_from=date(2026, 1, 1),
        )
        stored_event = work.lunar_events.add(event)
        stored_window = work.karuvottam_windows.add(
            _window(event), trigger_event_id=stored_event.id
        )

    with data_access.transaction() as work:
        assert work.locations.get(location.id) == location
        assert work.locations.list_active() == (location,)
        assert work.calendar_rules.find(
            'modified-tamil-calendar', '1.0'
        ) == stored_rule
        assert work.lunar_events.get(stored_event.id) == stored_event
        assert work.karuvottam_windows.find('aadi', 2026, '1.0') == stored_window

    assert stored_event.event_datetime_utc.endswith('Z')
    assert stored_event.event_datetime_local.endswith('+05:30')
    assert stored_window.trigger_event_id == stored_event.id


def test_unhandled_application_error_rolls_back_the_transaction(data_access):
    with pytest.raises(RuntimeError, match='cancel operation'):
        with data_access.transaction() as work:
            work.locations.add(
                name='Rolled back',
                latitude=10,
                longitude=78,
                elevation_m=None,
                timezone_name='Asia/Kolkata',
            )
            raise RuntimeError('cancel operation')

    with data_access.transaction() as work:
        assert work.locations.list_active() == ()


def test_duplicate_error_is_mapped_and_rolls_back_all_writes(data_access):
    with data_access.transaction() as work:
        work.locations.add(
            name='Existing',
            latitude=10,
            longitude=78,
            elevation_m=None,
            timezone_name='Asia/Kolkata',
        )

    with pytest.raises(DuplicateRecordError, match='already exists'):
        with data_access.transaction() as work:
            work.locations.add(
                name='Must roll back',
                latitude=11,
                longitude=79,
                elevation_m=None,
                timezone_name='Asia/Kolkata',
            )
            work.locations.add(
                name='Existing',
                latitude=10,
                longitude=78,
                elevation_m=None,
                timezone_name='Asia/Kolkata',
            )

    with data_access.transaction() as work:
        assert [record.name for record in work.locations.list_active()] == ['Existing']


def test_constraint_errors_are_mapped_without_leaking_sql(data_access):
    with pytest.raises(ConstraintViolationError, match='database constraint'):
        with data_access.transaction() as work:
            work.locations.add(
                name='Invalid',
                latitude=100,
                longitude=78,
                elevation_m=None,
                timezone_name='Asia/Kolkata',
            )


def test_database_open_errors_are_mapped(tmp_path):
    database_directory = tmp_path / 'not-a-database-file'
    database_directory.mkdir()
    data_access = DataAccess(database_directory)

    with pytest.raises(DataAccessError, match='unable to open'):
        with data_access.transaction():
            pass


def test_weather_observations_are_normalized_and_queryable(data_access):
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        observed_local = datetime(2026, 1, 1, 6, 30, tzinfo=LOCAL_TIMEZONE)
        stored = work.weather_observations.add(
            WeatherObservation(
                location_id=location.id,
                observed_at_utc=observed_local,
                observed_at_local=observed_local,
                temperature_c=25.5,
                relative_humidity_pct=82,
                precipitation_mm=1.2,
                cloud_cover_pct=70,
                wind_speed_kmh=8,
                wind_direction_deg=90,
                pressure_hpa=1007,
                source='provider-a',
                quality_flag='verified',
                raw_payload_reference='payload/1',
            )
        )

    with data_access.transaction() as work:
        results = work.weather_observations.list_between(
            location.id,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            source='provider-a',
        )

    assert results == (stored,)
    assert stored.observed_at_utc == '2026-01-01T01:00:00Z'
    assert stored.observed_at_local == '2026-01-01T06:30:00+05:30'
    assert stored.is_interpolated is False


def test_naive_observation_timestamp_rolls_back(data_access):
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )

    with pytest.raises(ValueError, match='timezone-aware'):
        with data_access.transaction() as work:
            work.weather_observations.add(
                WeatherObservation(
                    location_id=location.id,
                    observed_at_utc=datetime(2026, 1, 1),
                    observed_at_local=datetime(2026, 1, 1),
                    source='provider-a',
                    quality_flag='unknown',
                )
            )

    with data_access.transaction() as work:
        assert work.weather_observations.list_between(
            location.id,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ) == ()
