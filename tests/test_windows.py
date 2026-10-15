from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.calendar_engine import CalendarRule
from karuvottam.lunar_events import LunarEvent, LunarEventUnavailable
from karuvottam.windows import KaruvottamWindowEngine, WindowUnavailable


IST = ZoneInfo('Asia/Kolkata')
RULE = CalendarRule(reference_month=3, reference_day=21, version='2.0')


def make_event(event_type='full_moon', days=0):
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc) + timedelta(days=days)
    return LunarEvent(
        event_type=event_type,
        event_datetime_utc=event_utc,
        event_datetime_local=event_utc.astimezone(IST),
        source='Fake phases',
        calculation_version='test-1',
    )


class FakeLunarEngine:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def first_event_for_tamil_month(self, year, month, rule):
        self.calls.append(('first', year, month, rule.version))
        if self.error:
            raise self.error
        return make_event()

    def phase_for_tamil_month(self, year, month, rule, event_type):
        self.calls.append(('phase', year, month, rule.version, event_type))
        if self.error:
            raise self.error
        return make_event(event_type)


@pytest.mark.parametrize(
    ('season_type', 'tamil_month', 'hours'),
    [('aadi', 4, 432), ('margazhi', 9, 264)],
)
def test_window_begins_at_lunar_event_and_uses_configured_duration(
    season_type, tamil_month, hours
):
    lunar = FakeLunarEngine()
    engine = KaruvottamWindowEngine(RULE, lunar)

    window = engine.generate(season_type, 2026)

    assert window.start_datetime_local == window.trigger_event.event_datetime_local
    assert window.end_datetime_local - window.start_datetime_local == timedelta(hours=hours)
    assert window.duration_hours == hours
    assert window.sunrise is None
    assert window.rule_version == '2.0'
    assert window.status == 'calculated'
    assert lunar.calls[0][2] == tamil_month


def test_aadi_uses_first_new_or_full_moon_after_june_21_month_start():
    lunar = FakeLunarEngine()

    KaruvottamWindowEngine(RULE, lunar).generate('aadi', 2026)

    assert lunar.calls == [('first', 2026, 4, '2.0')]


def test_margazhi_phase_alternates_from_configured_anchor():
    lunar = FakeLunarEngine()
    engine = KaruvottamWindowEngine(
        RULE,
        lunar,
        margazhi_anchor_year=2026,
        margazhi_anchor_phase='new_moon',
    )

    first = engine.generate('margazhi', 2026)
    second = engine.generate('margazhi', 2027)
    earlier = engine.generate('margazhi', 2025)

    assert first.trigger_event.event_type == 'new_moon'
    assert second.trigger_event.event_type == 'full_moon'
    assert earlier.trigger_event.event_type == 'full_moon'
    assert lunar.calls == [
        ('phase', 2026, 9, '2.0', 'new_moon'),
        ('phase', 2027, 9, '2.0', 'full_moon'),
        ('phase', 2025, 9, '2.0', 'full_moon'),
    ]


def test_window_record_retains_lunar_provenance_without_sunrise():
    window = KaruvottamWindowEngine(RULE, FakeLunarEngine()).generate('aadi', 2026)

    record = window.as_record()

    assert record['duration_hours'] == 432
    assert record['trigger_event']['source'] == 'Fake phases'
    assert record['sunrise'] is None


def test_generate_year_returns_both_seasons():
    windows = KaruvottamWindowEngine(RULE, FakeLunarEngine()).generate_year(2026)

    assert set(windows) == {'aadi', 'margazhi'}


def test_lunar_failure_becomes_window_unavailable():
    engine = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(error=LunarEventUnavailable('no data')),
    )

    with pytest.raises(WindowUnavailable, match='aadi window for 2026'):
        engine.generate('aadi', 2026)


@pytest.mark.parametrize('season_type', ['thai', '', 'AADI'])
def test_unknown_season_is_rejected(season_type):
    with pytest.raises(ValueError, match='unsupported season'):
        KaruvottamWindowEngine(RULE, FakeLunarEngine()).generate(season_type, 2026)


@pytest.mark.parametrize(
    ('anchor_year', 'anchor_phase', 'message'),
    [(0, 'new_moon', 'positive'), (2026, 'quarter_moon', 'new_moon or full_moon')],
)
def test_invalid_margazhi_anchor_is_rejected(anchor_year, anchor_phase, message):
    with pytest.raises(ValueError, match=message):
        KaruvottamWindowEngine(RULE, FakeLunarEngine(), anchor_year, anchor_phase)


def test_real_2026_aadi_window_starts_at_first_principal_phase():
    from app import WINDOW_ENGINE

    window = WINDOW_ENGINE.generate('aadi', 2026)

    assert window.start_datetime_local == datetime(
        2026, 6, 30, 5, 27, 17, 744216, tzinfo=IST
    )
    assert window.trigger_event.event_type == 'full_moon'
    assert window.end_datetime_local - window.start_datetime_local == timedelta(days=18)


def test_real_2026_margazhi_window_uses_new_moon_for_11_days():
    from app import WINDOW_ENGINE

    window = WINDOW_ENGINE.generate('margazhi', 2026)

    assert window.trigger_event.event_type == 'new_moon'
    assert window.start_datetime_local.date().year == 2026
    assert window.start_datetime_local.date().month == 12
    assert window.end_datetime_local - window.start_datetime_local == timedelta(days=11)
