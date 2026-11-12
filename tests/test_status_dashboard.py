from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.forecast_timeline import (
    ForecastTimelineEngine,
    unavailable_research_score,
)
from karuvottam.lunar_events import LunarEvent
from karuvottam.status_dashboard import StatusDashboardService
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')


class FixedWindowEngine:
    def generate(self, season_type: str, season_year: int) -> KaruvottamWindow:
        month = 7 if season_type == 'aadi' else 12
        duration_days = 18 if season_type == 'aadi' else 11
        event_type = 'full_moon' if season_type == 'aadi' else 'new_moon'
        start = datetime(season_year, month, 1, 6, tzinfo=IST)
        event = LunarEvent(
            event_type=event_type,
            event_datetime_utc=start.astimezone(timezone.utc),
            event_datetime_local=start,
            source='fixed-test-engine',
            calculation_version='1.0',
        )
        return KaruvottamWindow(
            season_type=season_type,
            season_year=season_year,
            start_datetime_local=start,
            end_datetime_local=start + timedelta(days=duration_days),
            duration_hours=duration_days * 24,
            trigger_event=event,
            sunrise=None,
            rule_version='test-rule-1.0',
        )


def _service(data_access: DataAccess) -> StatusDashboardService:
    return StatusDashboardService(
        data_access,
        FixedWindowEngine(),
        location_name='சோதனை இடம்',
        latitude=9.9,
        longitude=77.8,
        timezone_name='Asia/Kolkata',
    )


def test_dashboard_selects_active_then_next_window(tmp_path):
    database_path = tmp_path / 'dashboard.sqlite3'
    migrate_database(database_path)
    service = _service(DataAccess(database_path))

    active = service.build(datetime(2026, 7, 5, tzinfo=IST))
    upcoming = service.build(datetime(2026, 10, 16, tzinfo=IST))

    assert active.window.state == 'active'
    assert active.window.window.season_type == 'aadi'
    assert upcoming.window.state == 'upcoming'
    assert upcoming.window.window.season_type == 'margazhi'
    assert upcoming.window.window.season_year == 2026


def test_dashboard_reads_latest_weather_and_forecast(tmp_path):
    database_path = tmp_path / 'dashboard.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    window = FixedWindowEngine().generate('aadi', 2026)
    timeline = ForecastTimelineEngine(IST).generate(
        window,
        mapping_basis_end_local=datetime(2026, 12, 12, 6, tzinfo=IST),
        research_score=unavailable_research_score('test_no_input'),
        generated_at=datetime(2026, 12, 12, tzinfo=timezone.utc),
    )

    with data_access.transaction() as work:
        location = work.locations.add(
            name='சோதனை இடம்',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        for hour in (1, 2):
            observed_utc = datetime(2026, 10, 16, hour, tzinfo=timezone.utc)
            work.weather_observations.add(
                WeatherObservation(
                    location_id=location.id,
                    observed_at_utc=observed_utc,
                    observed_at_local=observed_utc.astimezone(IST),
                    source='test-provider',
                    quality_flag='valid',
                )
            )
        event = work.lunar_events.add(window.trigger_event)
        stored_window = work.karuvottam_windows.add(
            window,
            trigger_event_id=event.id,
        )
        stored_run = work.forecasts.add_timeline(
            timeline,
            input_window_id=stored_window.id,
        )

    status = _service(data_access).build(datetime(2026, 10, 16, 8, tzinfo=IST))

    assert status.location_record == location
    assert status.latest_observation.observed_at_utc == '2026-10-16T02:00:00Z'
    assert status.latest_forecast == stored_run
    assert 'வானிலைத் தரவு இன்னும் சேமிக்கப்படவில்லை' not in ' '.join(status.warnings)
    assert any('ஆராய்ச்சி முடிவாக மட்டும்' in warning for warning in status.warnings)


def test_dashboard_handles_unmigrated_database_without_failing(tmp_path):
    status = _service(DataAccess(tmp_path / 'unmigrated.sqlite3')).build(
        datetime(2026, 10, 16, tzinfo=IST)
    )

    assert status.database_available is False
    assert status.latest_observation is None
    assert status.latest_forecast is None
    assert any('migration' in warning for warning in status.warnings)
