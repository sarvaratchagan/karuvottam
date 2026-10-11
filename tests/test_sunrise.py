from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.lunar_events import LunarEvent
from karuvottam.sunrise import SunriseEngine, SunriseUnavailable


IST = ZoneInfo('Asia/Kolkata')
LATITUDE = 9.9040188
LONGITUDE = 77.8860417


class FakeSunriseProvider:
    source = 'Fake sunrise'
    calculation_version = 'test-1'

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def search_sunrise(self, start_utc, latitude, longitude, elevation_m):
        self.calls.append((start_utc, latitude, longitude, elevation_m))
        if self.error:
            raise self.error
        return self.result


def make_lunar_event(event_utc):
    return LunarEvent(
        event_type='full_moon',
        event_datetime_utc=event_utc,
        event_datetime_local=event_utc.astimezone(IST),
        source='Fake phases',
        calculation_version='test-1',
    )


def test_settling_period_uses_four_local_calendar_days():
    event = make_lunar_event(datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc))
    sunrise_utc = datetime(2026, 7, 4, 0, 32, tzinfo=timezone.utc)
    provider = FakeSunriseProvider(result=sunrise_utc)
    engine = SunriseEngine(LATITUDE, LONGITUDE, 0, IST, provider)

    result = engine.sunrise_after_settling_period(event)

    assert event.event_datetime_local.date() == date(2026, 6, 30)
    assert result.target_local_date == date(2026, 7, 4)
    assert result.sunrise_datetime_local == datetime(2026, 7, 4, 6, 2, tzinfo=IST)
    assert provider.calls[0][0] == datetime(2026, 7, 3, 18, 30, tzinfo=timezone.utc)


def test_sunrise_record_contains_location_and_provenance():
    provider = FakeSunriseProvider(
        result=datetime(2026, 7, 4, 0, 32, tzinfo=timezone.utc)
    )
    result = SunriseEngine(
        LATITUDE,
        LONGITUDE,
        25,
        IST,
        provider,
    ).sunrise_for_local_date(date(2026, 7, 4))

    assert result.as_record() == {
        'target_local_date': date(2026, 7, 4),
        'sunrise_datetime_utc': datetime(2026, 7, 4, 0, 32, tzinfo=timezone.utc),
        'sunrise_datetime_local': datetime(2026, 7, 4, 6, 2, tzinfo=IST),
        'latitude': LATITUDE,
        'longitude': LONGITUDE,
        'elevation_m': 25,
        'source': 'Fake sunrise',
        'calculation_version': 'test-1',
        'quality_flag': 'calculated',
    }


def test_real_target_location_sunrise_is_stable_to_one_minute():
    result = SunriseEngine(
        LATITUDE,
        LONGITUDE,
        0,
        IST,
    ).sunrise_for_local_date(date(2026, 7, 4))
    expected = datetime(2026, 7, 4, 0, 32, tzinfo=timezone.utc)

    assert abs(result.sunrise_datetime_utc - expected) <= timedelta(minutes=1)
    assert result.sunrise_datetime_local.date() == date(2026, 7, 4)
    assert result.source == 'Astronomy Engine'
    assert result.calculation_version == '2.1.19'


@pytest.mark.parametrize(
    ('provider', 'message'),
    [
        (FakeSunriseProvider(), 'no sunrise found'),
        (
            FakeSunriseProvider(result=datetime(2026, 7, 4, 0, 32)),
            'naive timestamp',
        ),
        (
            FakeSunriseProvider(
                result=datetime(2026, 7, 5, 0, 32, tzinfo=timezone.utc)
            ),
            'outside local date',
        ),
        (FakeSunriseProvider(error=RuntimeError('offline')), 'provider failed'),
    ],
)
def test_unavailable_sunrise_conditions_are_explicit(provider, message):
    engine = SunriseEngine(LATITUDE, LONGITUDE, 0, IST, provider)

    with pytest.raises(SunriseUnavailable, match=message):
        engine.sunrise_for_local_date(date(2026, 7, 4))


def test_negative_settling_period_is_rejected():
    event = make_lunar_event(datetime(2026, 6, 29, 23, 57, tzinfo=timezone.utc))

    with pytest.raises(ValueError, match='must not be negative'):
        SunriseEngine(
            LATITUDE,
            LONGITUDE,
            0,
            IST,
        ).sunrise_after_settling_period(event, settling_days=-1)


@pytest.mark.parametrize(
    ('latitude', 'longitude', 'message'),
    [(91, 0, 'latitude'), (0, 181, 'longitude')],
)
def test_invalid_coordinates_are_rejected(latitude, longitude, message):
    with pytest.raises(ValueError, match=message):
        SunriseEngine(latitude, longitude, 0, IST)
