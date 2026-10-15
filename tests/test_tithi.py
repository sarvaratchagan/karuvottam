from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.lunar_events import LunarEvent
from karuvottam.tithi import TITHI_NAMES, TithiEngine, TithiUnavailable


IST = ZoneInfo('Asia/Kolkata')


class FakePhaseProvider:
    source = 'Fake phase angles'
    calculation_version = 'test-1'

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def search_phase(self, angle, start_utc, limit_days):
        self.calls.append((angle, start_utc, limit_days))
        if self.error:
            raise self.error
        return self.result


def make_event(event_type, event_utc):
    return LunarEvent(
        event_type=event_type,
        event_datetime_utc=event_utc,
        event_datetime_local=event_utc.astimezone(IST),
        source='Fake lunar event',
        calculation_version='test-1',
    )


@pytest.mark.parametrize(
    ('event_type', 'angle', 'paksha', 'tamil_name'),
    [
        ('full_moon', 156.0, 'shukla', 'சுக்கில பட்ச சதுர்த்தசி தொடக்கம்'),
        ('new_moon', 336.0, 'krishna', 'கிருஷ்ண பட்ச சதுர்த்தசி தொடக்கம்'),
    ],
)
def test_chaturdashi_boundary_for_each_lunar_event(
    event_type,
    angle,
    paksha,
    tamil_name,
):
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc)
    boundary_utc = event_utc - timedelta(days=2)
    provider = FakePhaseProvider(boundary_utc)

    boundary = TithiEngine(IST, provider).chaturdashi_before(
        make_event(event_type, event_utc)
    )

    assert provider.calls == [(angle, event_utc, -5.0)]
    assert boundary.paksha == paksha
    assert boundary.tithi_number == 14
    assert boundary.tithi_name == 'சதுர்த்தசி'
    assert boundary.phase_angle_degrees == angle
    assert boundary.event_type_tamil == tamil_name
    assert boundary.event_datetime_utc == boundary_utc
    assert boundary.reference_lunar_event.event_type == event_type


def test_real_2026_aadi_chaturdashi_precedes_full_moon():
    from app import CALENDAR_RULE, LUNAR_EVENT_ENGINE

    event = LUNAR_EVENT_ENGINE.first_event_for_tamil_month(2026, 4, CALENDAR_RULE)
    boundary = TithiEngine(IST).chaturdashi_before(event)

    assert event.event_type == 'full_moon'
    assert boundary.paksha == 'shukla'
    assert boundary.phase_angle_degrees == 156.0
    assert boundary.event_datetime_utc == datetime(
        2026, 6, 27, 19, 14, 27, 446056, tzinfo=timezone.utc
    )
    assert boundary.event_datetime_utc < event.event_datetime_utc


def test_tithi_record_retains_reference_event():
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc)
    boundary = TithiEngine(
        IST,
        FakePhaseProvider(event_utc - timedelta(days=2)),
    ).chaturdashi_before(make_event('full_moon', event_utc))

    record = boundary.as_record()

    assert record['tithi_number'] == 14
    assert record['phase_angle_degrees'] == 156.0
    assert record['reference_lunar_event']['event_type'] == 'full_moon'
    assert record['source'] == 'Fake phase angles'


@pytest.mark.parametrize(
    ('provider', 'message'),
    [
        (FakePhaseProvider(), 'was not found'),
        (FakePhaseProvider(error=RuntimeError('offline')), 'provider failed'),
        (FakePhaseProvider(datetime(2026, 6, 27)), 'naive timestamp'),
        (
            FakePhaseProvider(datetime(2026, 6, 30, tzinfo=timezone.utc)),
            'must precede',
        ),
    ],
)
def test_invalid_boundary_results_are_unavailable(provider, message):
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc)

    with pytest.raises(TithiUnavailable, match=message):
        TithiEngine(IST, provider).chaturdashi_before(
            make_event('full_moon', event_utc)
        )


def test_unsupported_lunar_event_is_rejected():
    event_utc = datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match='unsupported lunar event'):
        TithiEngine(IST).chaturdashi_before(make_event('quarter_moon', event_utc))


def test_user_defined_tithi_names_are_complete():
    assert len(TITHI_NAMES) == 15
    assert TITHI_NAMES[0] == 'பிரதமை'
    assert TITHI_NAMES[13] == 'சதுர்த்தசி'
    assert TITHI_NAMES[14] == 'பௌர்ணமி / அமாவாசை'
