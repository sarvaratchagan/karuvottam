from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.calendar_engine import CalendarRule
from karuvottam.lunar_events import (
    AstronomyEngineProvider,
    LunarEventEngine,
    LunarEventUnavailable,
)


IST = ZoneInfo('Asia/Kolkata')
RULE = CalendarRule(reference_month=3, reference_day=21, version='1.0')


class FakeProvider:
    source = 'Fake phases'
    calculation_version = 'test-1'

    def __init__(self, new_moon=None, full_moon=None, error=None):
        self.new_moon = new_moon
        self.full_moon = full_moon
        self.error = error

    def search_phase(self, phase_angle, start_utc, limit_days):
        if self.error:
            raise self.error
        return self.new_moon if phase_angle == 0.0 else self.full_moon


def test_selects_earliest_new_or_full_moon():
    start = datetime(2026, 6, 21, tzinfo=IST)
    provider = FakeProvider(
        new_moon=start.astimezone(timezone.utc) + timedelta(days=2),
        full_moon=start.astimezone(timezone.utc) + timedelta(days=5),
    )

    event = LunarEventEngine(IST, provider).first_new_or_full_after(start)

    assert event.event_type == 'new_moon'
    assert event.event_type_tamil == 'அமாவாசை'
    assert event.event_datetime_utc == provider.new_moon
    assert event.event_datetime_local.tzinfo == IST
    assert event.source == 'Fake phases'
    assert event.calculation_version == 'test-1'
    assert event.quality_flag == 'calculated'


def test_event_record_contains_provenance_fields():
    start = datetime(2026, 6, 21, tzinfo=IST)
    event_time = start.astimezone(timezone.utc) + timedelta(days=1)
    event = LunarEventEngine(
        IST,
        FakeProvider(new_moon=event_time),
    ).first_new_or_full_after(start)

    assert event.as_record() == {
        'event_type': 'new_moon',
        'event_datetime_utc': event_time,
        'event_datetime_local': event_time.astimezone(IST),
        'source': 'Fake phases',
        'calculation_version': 'test-1',
        'quality_flag': 'calculated',
    }


def test_month_lookup_uses_modified_tamil_month_start():
    provider = FakeProvider(
        full_moon=datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc),
    )
    engine = LunarEventEngine(IST, provider)

    event = engine.first_event_for_tamil_month(2026, 4, RULE)

    assert event.event_type == 'full_moon'
    assert event.event_datetime_local == datetime(2026, 6, 30, 5, 27, tzinfo=IST)


def test_specific_phase_lookup_uses_requested_phase_and_month_start():
    event_time = datetime(2026, 12, 9, 0, 52, tzinfo=timezone.utc)
    provider = FakeProvider(new_moon=event_time)

    event = LunarEventEngine(IST, provider).phase_for_tamil_month(
        2026, 9, RULE, 'new_moon'
    )

    assert event.event_type == 'new_moon'
    assert event.event_datetime_utc == event_time


def test_unknown_specific_phase_is_rejected():
    with pytest.raises(ValueError, match='unsupported lunar event type'):
        LunarEventEngine(IST).first_phase_after(
            datetime(2026, 11, 21, tzinfo=IST), 'quarter_moon'
        )


def test_real_aadi_event_agrees_with_usno_to_two_minutes():
    event = LunarEventEngine(IST).first_event_for_tamil_month(2026, 4, RULE)
    usno_full_moon = datetime(2026, 6, 29, 23, 56, tzinfo=timezone.utc)

    assert event.event_type == 'full_moon'
    assert abs(event.event_datetime_utc - usno_full_moon) <= timedelta(minutes=2)
    assert event.source == 'Astronomy Engine'
    assert event.calculation_version == '2.1.19'


def test_real_margazhi_event_agrees_with_usno_to_two_minutes():
    event = LunarEventEngine(IST).first_event_for_tamil_month(2026, 9, RULE)
    usno_full_moon = datetime(2026, 11, 24, 14, 53, tzinfo=timezone.utc)

    assert event.event_type == 'full_moon'
    assert abs(event.event_datetime_utc - usno_full_moon) <= timedelta(minutes=2)


def test_naive_start_time_is_rejected():
    with pytest.raises(ValueError, match='timezone-aware'):
        LunarEventEngine(IST).first_new_or_full_after(datetime(2026, 6, 21))


def test_missing_events_raise_unavailable_error():
    start = datetime(2026, 6, 21, tzinfo=IST)

    with pytest.raises(LunarEventUnavailable, match='no new or full moon'):
        LunarEventEngine(IST, FakeProvider()).first_new_or_full_after(start)


def test_provider_failure_is_wrapped_as_unavailable():
    start = datetime(2026, 6, 21, tzinfo=IST)

    with pytest.raises(LunarEventUnavailable, match='provider failed'):
        LunarEventEngine(
            IST,
            FakeProvider(error=RuntimeError('offline')),
        ).first_new_or_full_after(start)


def test_naive_provider_timestamp_is_unavailable():
    start = datetime(2026, 6, 21, tzinfo=IST)

    with pytest.raises(LunarEventUnavailable, match='naive timestamp'):
        LunarEventEngine(
            IST,
            FakeProvider(new_moon=datetime(2026, 6, 22)),
        ).first_new_or_full_after(start)


def test_astronomy_provider_returns_aware_utc_time():
    start = datetime(2026, 6, 20, 18, 30, tzinfo=timezone.utc)

    result = AstronomyEngineProvider.search_phase(180.0, start, 40.0)

    assert result is not None
    assert result.tzinfo == timezone.utc
