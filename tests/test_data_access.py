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
from karuvottam.forecast_timeline import ForecastTimelineEngine
from karuvottam.lunar_events import LunarEvent
from karuvottam.research_scoring import ResearchScore
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
        interval_end = observed_local.astimezone(timezone.utc)
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
                precipitation_interval_start_utc=interval_end - timedelta(hours=1),
                precipitation_interval_end_utc=interval_end,
                precipitation_interval_minutes=60,
            )
        )

    with data_access.transaction() as work:
        results = work.weather_observations.list_between(
            location.id,
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            datetime(2026, 1, 2, tzinfo=timezone.utc),
            source='provider-a',
        )
        latest = work.weather_observations.latest_for_location(location.id)

    assert results == (stored,)
    assert latest == stored
    assert stored.observed_at_utc == '2026-01-01T01:00:00Z'
    assert stored.observed_at_local == '2026-01-01T06:30:00+05:30'
    assert stored.precipitation_interval_start_utc == '2026-01-01T00:00:00Z'
    assert stored.precipitation_interval_end_utc == '2026-01-01T01:00:00Z'
    assert stored.precipitation_interval_minutes == 60
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


def test_weather_timestamp_representations_must_be_consistent(data_access):
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )

    with pytest.raises(ValueError, match='same instant'):
        with data_access.transaction() as work:
            work.weather_observations.add(
                WeatherObservation(
                    location_id=location.id,
                    observed_at_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    observed_at_local=datetime(
                        2026, 1, 1, 6, 30, tzinfo=LOCAL_TIMEZONE
                    ),
                    source='provider-a',
                    quality_flag='unknown',
                )
            )


@pytest.mark.parametrize(
    'start, end, minutes, message',
    [
        (None, datetime(2026, 1, 1, tzinfo=timezone.utc), 60, 'provided together'),
        (
            datetime(2025, 12, 31, 23, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            60,
            'end must equal',
        ),
        (
            datetime(2025, 12, 31, 22, tzinfo=timezone.utc),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            60,
            'duration does not match',
        ),
    ],
)
def test_precipitation_interval_is_validated(
    data_access, start, end, minutes, message
):
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )

    observed = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match=message):
        with data_access.transaction() as work:
            work.weather_observations.add(
                WeatherObservation(
                    location_id=location.id,
                    observed_at_utc=observed,
                    observed_at_local=observed.astimezone(LOCAL_TIMEZONE),
                    source='provider-a',
                    quality_flag='unknown',
                    precipitation_interval_start_utc=start,
                    precipitation_interval_end_utc=end,
                    precipitation_interval_minutes=minutes,
                )
            )


def test_forecast_timeline_is_persisted_with_source_window_link(data_access):
    event = _lunar_event()
    source_window = _window(event)
    score = ResearchScore(
        status='available',
        score=73.5,
        maximum_score=100.0,
        model_version='research-index-1.0',
        label='experimental_research_index_not_probability',
        quality_flag='valid',
        reason_codes=(),
        components=(),
    )
    timeline = ForecastTimelineEngine(LOCAL_TIMEZONE).generate(
        source_window,
        mapping_basis_end_local=datetime(
            2026, 12, 20, 6, 22, tzinfo=LOCAL_TIMEZONE
        ),
        research_score=score,
        generated_at=datetime(2026, 12, 20, 1, tzinfo=timezone.utc),
    )

    with data_access.transaction() as work:
        stored_event = work.lunar_events.add(event)
        stored_window = work.karuvottam_windows.add(
            source_window,
            trigger_event_id=stored_event.id,
        )
        stored_run = work.forecasts.add_timeline(
            timeline,
            input_window_id=stored_window.id,
        )

    with data_access.transaction() as work:
        reloaded_run = work.forecasts.get_run(stored_run.id)
        latest_run = work.forecasts.latest_run()
        entries = work.forecasts.list_entries(stored_run.id)

    assert reloaded_run == stored_run
    assert latest_run == stored_run
    assert stored_run.input_window_id == stored_window.id
    assert stored_run.source_window_key == 'aadi:2026:1.0'
    assert stored_run.model_version == 'daily-timeline-1.0'
    assert len(entries) == 180
    assert entries[0].status == 'experimental'
    assert entries[0].research_score == 73.5
    assert entries[0].rain_probability_pct is None
    assert entries[0].predicted_rain_mm is None
    assert entries[0].rain_category is None
    assert entries[0].reason_codes == ('rain_amount_model_not_defined',)
