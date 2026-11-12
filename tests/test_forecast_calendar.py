import csv
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from karuvottam.calendar_engine import CalendarRule
from karuvottam.forecast_calendar import ForecastCalendarService
from karuvottam.forecast_timeline import (
    ForecastTimelineEngine,
    unavailable_research_score,
)
from karuvottam.lunar_events import LunarEvent
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')


def _timeline():
    start = datetime(2026, 6, 30, 5, 27, tzinfo=IST)
    event = LunarEvent(
        event_type='full_moon',
        event_datetime_utc=start.astimezone(timezone.utc),
        event_datetime_local=start,
        source='test',
        calculation_version='1.0',
    )
    window = KaruvottamWindow(
        season_type='aadi',
        season_year=2026,
        start_datetime_local=start,
        end_datetime_local=start + timedelta(days=18),
        duration_hours=432,
        trigger_event=event,
        sunrise=None,
        rule_version='2.0',
    )
    return ForecastTimelineEngine(IST).generate(
        window,
        mapping_basis_end_local=datetime(2026, 12, 20, 6, 22, tzinfo=IST),
        research_score=unavailable_research_score('test_no_input'),
        generated_at=datetime(2026, 12, 20, tzinfo=timezone.utc),
    )


def test_calendar_groups_complete_day_week_and_month_views():
    service = ForecastCalendarService(CalendarRule(version='2.0'))
    timeline = _timeline()

    day = service.build(timeline, 'day')
    week = service.build(timeline, 'week')
    month = service.build(timeline, 'month')

    assert len(day.periods) == 180
    assert len(week.periods) == 26
    assert len(week.periods[-1].entries) == 5
    assert len(month.periods) == 7
    assert month.periods[0].title == 'டிசம்பர் 2026'
    assert month.periods[-1].title == 'ஜூன் 2027'
    assert sum(len(period.entries) for period in month.periods) == 180
    assert all(period.probability_display is None for period in week.periods)
    assert week.periods[0].no_data_days == 7


def test_forecast_csv_preserves_tamil_and_nullable_evidence_fields():
    service = ForecastCalendarService(CalendarRule(version='2.0'))
    csv_text = service.export_csv(_timeline())
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert len(rows) == 180
    assert rows[0]['target_date'] == '2026-12-21'
    assert rows[0]['tamil_date'] == 'தை 1 / 2026'
    assert rows[0]['status'] == 'no_data'
    assert rows[0]['rain_probability_pct'] == ''
    assert rows[0]['rain_category'] == ''
    assert rows[0]['quality_flag'] == 'unavailable'
    assert rows[0]['reason_codes'] == 'test_no_input'
    assert rows[0]['timeline_model_version'] == 'daily-timeline-1.0'


def test_calendar_exposes_probability_and_category_only_when_present():
    timeline = _timeline()
    first = replace(
        timeline.entries[0],
        status='experimental',
        rain_probability_pct=35.0,
        rain_category='drizzle',
    )
    timeline = replace(timeline, entries=(first, *timeline.entries[1:]))

    week = ForecastCalendarService(CalendarRule(version='2.0')).build(
        timeline,
        'week',
    )

    assert week.periods[0].probability_display == '35%'
    assert week.periods[0].categories_tamil == ('தூறல் / இலேசான மழை',)
