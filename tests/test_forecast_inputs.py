from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.forecast_inputs import (
    StoredForecastInputService,
    source_window_hour_ends,
)
from karuvottam.lunar_events import LunarEvent
from karuvottam.research_scoring import ResearchScoringEngine
from karuvottam.weather_quality import WeatherQualityValidator
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')
SOURCE = 'open-meteo:era5'


def _window(start=None, hours=2):
    start = start or datetime(2020, 7, 1, 0, 13, tzinfo=IST)
    event = LunarEvent(
        event_type='new_moon',
        event_datetime_utc=start.astimezone(timezone.utc),
        event_datetime_local=start,
        source='test-lunar',
        calculation_version='test-1',
    )
    return KaruvottamWindow(
        season_type='aadi',
        season_year=start.year,
        start_datetime_local=start,
        end_datetime_local=start + timedelta(hours=hours),
        duration_hours=hours,
        trigger_event=event,
        sunrise=None,
        rule_version='test-rule',
    )


def _service(data_access):
    return StoredForecastInputService(
        data_access,
        ResearchScoringEngine(),
        WeatherQualityValidator(),
        location_name='Target',
        latitude=9.9,
        longitude=77.8,
        timezone_name='Asia/Kolkata',
        source=SOURCE,
    )


@pytest.fixture()
def stored_service(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
    return data_access, location, _service(data_access)


def _add_observation(data_access, location_id, hour_end_utc, *, source=SOURCE,
                     precipitation=1.0, interval_minutes=60):
    with data_access.transaction() as work:
        work.weather_observations.add(
            WeatherObservation(
                location_id=location_id,
                observed_at_utc=hour_end_utc,
                observed_at_local=hour_end_utc.astimezone(IST),
                source=source,
                quality_flag='valid',
                temperature_c=27,
                relative_humidity_pct=85,
                precipitation_mm=precipitation,
                cloud_cover_pct=80,
                wind_speed_kmh=20,
                wind_direction_deg=180,
                pressure_hpa=1005,
                precipitation_interval_start_utc=(
                    hour_end_utc - timedelta(minutes=interval_minutes)
                ),
                precipitation_interval_end_utc=hour_end_utc,
                precipitation_interval_minutes=interval_minutes,
            )
        )


def test_complete_stored_window_produces_available_research_score(stored_service):
    data_access, location, service = stored_service
    window = _window()
    first, last = source_window_hour_ends(window)
    _add_observation(data_access, location.id, first)
    _add_observation(data_access, location.id, last)

    result = service.score(window)

    assert result.research_score.is_available
    assert result.research_score.score == 73.5
    assert result.expected_hours == 2
    assert result.received_hours == 2
    assert result.coverage_pct == 100
    assert result.location_id == location.id


def test_missing_window_records_remain_explicitly_unavailable(stored_service):
    _, location, service = stored_service

    result = service.score(_window())

    assert result.research_score.score is None
    assert result.research_score.reason_codes == (
        'source_window_observations_not_found',
    )
    assert result.location_id == location.id
    assert result.coverage_pct == 0


def test_partial_window_coverage_does_not_create_score(stored_service):
    data_access, location, service = stored_service
    window = _window(hours=5)
    first, _ = source_window_hour_ends(window)
    _add_observation(data_access, location.id, first)

    result = service.score(window)

    assert result.research_score.score is None
    assert result.research_score.reason_codes == ('insufficient_time_coverage',)
    assert result.coverage_pct == 20


def test_wrong_source_is_not_used(stored_service):
    data_access, location, service = stored_service
    window = _window()
    first, _ = source_window_hour_ends(window)
    _add_observation(data_access, location.id, first, source='other:source')

    result = service.score(window)

    assert result.received_hours == 0
    assert result.research_score.reason_codes == (
        'source_window_observations_not_found',
    )


def test_incompatible_precipitation_interval_is_not_scored_as_rain(stored_service):
    data_access, location, service = stored_service
    window = _window()
    first, last = source_window_hour_ends(window)
    _add_observation(
        data_access,
        location.id,
        first,
        interval_minutes=30,
    )
    _add_observation(
        data_access,
        location.id,
        last,
        interval_minutes=30,
    )

    result = service.score(window)

    assert result.research_score.score is None
    assert result.research_score.reason_codes == (
        'insufficient_coverage:precipitation_mm',
    )


def test_unmigrated_database_returns_safe_unavailable_result(tmp_path):
    service = _service(DataAccess(tmp_path / 'unmigrated.sqlite3'))

    result = service.score(_window())

    assert result.research_score.reason_codes == ('weather_database_unavailable',)
    assert result.location_id is None
