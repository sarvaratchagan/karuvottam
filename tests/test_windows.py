from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.calendar_engine import CalendarRule
from karuvottam.lunar_events import LunarEvent, LunarEventUnavailable
from karuvottam.sunrise import SunriseResult, SunriseUnavailable
from karuvottam.tithi import TithiBoundary, TithiUnavailable
from karuvottam.windows import KaruvottamWindowEngine, WindowUnavailable


IST = ZoneInfo('Asia/Kolkata')
RULE = CalendarRule(reference_month=3, reference_day=21, version='1.0')


def make_event():
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc)
    return LunarEvent(
        event_type='full_moon',
        event_datetime_utc=event_utc,
        event_datetime_local=event_utc.astimezone(IST),
        source='Fake phases',
        calculation_version='test-1',
    )


def make_sunrise():
    sunrise_utc = datetime(2026, 7, 4, 0, 32, tzinfo=timezone.utc)
    return SunriseResult(
        target_local_date=date(2026, 7, 4),
        sunrise_datetime_utc=sunrise_utc,
        sunrise_datetime_local=sunrise_utc.astimezone(IST),
        latitude=9.9040188,
        longitude=77.8860417,
        elevation_m=0,
        source='Fake sunrise',
        calculation_version='test-1',
    )


def make_tithi_boundary():
    event = make_event()
    boundary_utc = datetime(2026, 6, 27, 19, 14, tzinfo=timezone.utc)
    return TithiBoundary(
        paksha='shukla',
        tithi_number=14,
        tithi_name='சதுர்த்தசி',
        phase_angle_degrees=156.0,
        event_datetime_utc=boundary_utc,
        event_datetime_local=boundary_utc.astimezone(IST),
        reference_lunar_event=event,
        source='Fake tithi',
        calculation_version='test-1',
    )


class FakeLunarEngine:
    def __init__(self, event=None, error=None):
        self.event = event or make_event()
        self.error = error
        self.calls = []

    def first_event_for_tamil_month(self, year, month, rule):
        self.calls.append((year, month, rule.version))
        if self.error:
            raise self.error
        return self.event


class FakeSunriseEngine:
    def __init__(self, sunrise=None, error=None):
        self.sunrise = sunrise or make_sunrise()
        self.error = error

    def sunrise_after_settling_period(self, event):
        if self.error:
            raise self.error
        return self.sunrise


class FakeTithiEngine:
    def __init__(self, boundary=None, error=None):
        self.boundary = boundary or make_tithi_boundary()
        self.error = error
        self.calls = []

    def chaturdashi_before(self, event):
        self.calls.append(event)
        if self.error:
            raise self.error
        return self.boundary


@pytest.mark.parametrize(
    ('season_type', 'tamil_month', 'hours'),
    [('aadi', 4, 432), ('margazhi', 9, 248)],
)
def test_window_duration_and_month_selection(season_type, tamil_month, hours):
    lunar = FakeLunarEngine()
    tithi = FakeTithiEngine()
    engine = KaruvottamWindowEngine(RULE, lunar, tithi, FakeSunriseEngine())

    window = engine.generate(season_type, 2026)

    assert lunar.calls == [(2026, tamil_month, '1.0')]
    assert len(tithi.calls) == (1 if season_type == 'aadi' else 0)
    assert window.start_datetime_local == make_sunrise().sunrise_datetime_local
    assert window.end_datetime_local - window.start_datetime_local == timedelta(hours=hours)
    assert window.duration_hours == hours
    assert window.rule_version == '1.0'
    assert window.status == 'calculated'


def test_window_record_retains_complete_provenance():
    window = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(),
        FakeTithiEngine(),
        FakeSunriseEngine(),
    ).generate('aadi', 2026)

    record = window.as_record()

    assert record['season_type'] == 'aadi'
    assert record['season_year'] == 2026
    assert record['duration_hours'] == 432
    assert record['trigger_event']['source'] == 'Fake tithi'
    assert record['trigger_event']['reference_lunar_event']['source'] == 'Fake phases'
    assert record['sunrise']['source'] == 'Fake sunrise'


def test_generate_year_returns_both_seasons():
    windows = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(),
        FakeTithiEngine(),
        FakeSunriseEngine(),
    ).generate_year(2026)

    assert set(windows) == {'aadi', 'margazhi'}


def test_lunar_failure_becomes_window_unavailable():
    engine = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(error=LunarEventUnavailable('no data')),
        FakeTithiEngine(),
        FakeSunriseEngine(),
    )

    with pytest.raises(WindowUnavailable, match='aadi window for 2026'):
        engine.generate('aadi', 2026)


def test_sunrise_failure_becomes_window_unavailable():
    engine = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(),
        FakeTithiEngine(),
        FakeSunriseEngine(error=SunriseUnavailable('no sunrise')),
    )

    with pytest.raises(WindowUnavailable, match='margazhi window for 2026'):
        engine.generate('margazhi', 2026)


def test_aadi_tithi_failure_becomes_window_unavailable():
    engine = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(),
        FakeTithiEngine(error=TithiUnavailable('no boundary')),
        FakeSunriseEngine(),
    )

    with pytest.raises(WindowUnavailable, match='aadi window for 2026'):
        engine.generate('aadi', 2026)


@pytest.mark.parametrize('season_type', ['thai', '', 'AADI'])
def test_unknown_season_is_rejected(season_type):
    engine = KaruvottamWindowEngine(
        RULE,
        FakeLunarEngine(),
        FakeTithiEngine(),
        FakeSunriseEngine(),
    )

    with pytest.raises(ValueError, match='unsupported season'):
        engine.generate(season_type, 2026)


def test_real_2026_aadi_window_uses_calculated_sunrise():
    from app import WINDOW_ENGINE

    window = WINDOW_ENGINE.generate('aadi', 2026)

    assert window.start_datetime_local == datetime(
        2026, 7, 2, 6, 1, 44, 785915, tzinfo=IST
    )
    assert window.trigger_event.event_type == 'shukla_chaturdashi_start'
    assert window.end_datetime_local - window.start_datetime_local == timedelta(days=18)


def test_real_2026_margazhi_window_is_248_hours():
    from app import WINDOW_ENGINE

    window = WINDOW_ENGINE.generate('margazhi', 2026)

    assert window.start_datetime_local.date() == date(2026, 11, 28)
    assert window.end_datetime_local - window.start_datetime_local == timedelta(hours=248)
