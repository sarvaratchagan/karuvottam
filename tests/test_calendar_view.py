from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from karuvottam.calendar_engine import CalendarRule
from karuvottam.calendar_view import CalendarViewService
from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.lunar_events import LunarEvent
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')


class FixedWindowEngine:
    calendar_rule = CalendarRule(version='test-rule-1.0')
    margazhi_anchor_year = 2026
    margazhi_anchor_phase = 'new_moon'

    def margazhi_event_type_for_year(self, season_year: int) -> str:
        same_parity = (season_year - self.margazhi_anchor_year) % 2 == 0
        return 'new_moon' if same_parity else 'full_moon'

    def generate(self, season_type: str, season_year: int) -> KaruvottamWindow:
        month = 7 if season_type == 'aadi' else 12
        duration_days = 18 if season_type == 'aadi' else 11
        event_type = (
            'full_moon'
            if season_type == 'aadi'
            else self.margazhi_event_type_for_year(season_year)
        )
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
            rule_version=self.calendar_rule.version,
        )


def test_calendar_view_exposes_windows_and_alternation(tmp_path):
    database_path = tmp_path / 'calendar.sqlite3'
    migrate_database(database_path)
    view = CalendarViewService(
        DataAccess(database_path), FixedWindowEngine()
    ).build(2026)

    assert [item.window.season_type for item in view.windows] == [
        'aadi',
        'margazhi',
    ]
    assert [item.tamil_month_start.isoformat() for item in view.windows] == [
        '2026-06-21',
        '2026-11-21',
    ]
    assert [item.event_type for item in view.alternation] == [
        'new_moon',
        'full_moon',
        'new_moon',
        'full_moon',
        'new_moon',
    ]
    assert [item.year for item in view.alternation if item.selected] == [2026]
    assert view.anchor_phase_tamil == 'அமாவாசை'
    assert view.database_available is True


def test_calendar_view_links_matching_persisted_window(tmp_path):
    database_path = tmp_path / 'calendar.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    engine = FixedWindowEngine()
    aadi = engine.generate('aadi', 2026)

    with data_access.transaction() as work:
        location = work.locations.add(
            name='Calendar target', latitude=9.9, longitude=77.8,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        event = work.lunar_events.add(aadi.trigger_event)
        stored = work.karuvottam_windows.add(
            aadi, trigger_event_id=event.id, location_id=location.id,
        )

    view = CalendarViewService(data_access, engine).build(2026)

    assert view.windows[0].persisted == stored
    assert view.windows[1].persisted is None
    assert f'#{stored.id}' in view.windows[0].persistence_state_tamil


def test_calendar_view_handles_unmigrated_database(tmp_path):
    view = CalendarViewService(
        DataAccess(tmp_path / 'unmigrated.sqlite3'), FixedWindowEngine()
    ).build(2026)

    assert view.database_available is False
    assert view.persistence_warning is not None
    assert all(item.persisted is None for item in view.windows)
