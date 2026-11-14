"""NASA POWER contract and provider-comparison guardrails."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from karuvottam.provider_comparison import (
    NasaPowerHourlyClient, POWER_PARAMETERS, POWER_UNITS,
    _daily_rain, _window, parse_power_payload,
)
from karuvottam.weather_client import HttpResponse
from zoneinfo import ZoneInfo


def power_response(year=2024):
    first = datetime(year, 1, 1, tzinfo=timezone.utc)
    last = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    stamps = [(first + timedelta(hours=offset)).strftime('%Y%m%d%H')
              for offset in range(int((last - first) / timedelta(hours=1)))]
    values = {name: {stamp: value for stamp in stamps} for name, value in {
        'T2M': 28.0, 'RH2M': 70.0, 'PRECTOTCORR': 1.0,
        'CLOUD_AMT': 40.0, 'WS10M': 2.0, 'WD10M': 90.0,
        'PS': 99.0,
    }.items()}
    return {
        'header': {'time_standard': 'UTC', 'start': f'{year}0101',
                   'end': f'{year}1231', 'fill_value': -999.0,
                   'api': {'version': 'test'}, 'sources': ['MERRA2']},
        'geometry': {'coordinates': [77.886, 9.904, 200]},
        'properties': {'parameter': values},
        'parameters': {name: {'units': POWER_UNITS[name]}
                       for name in POWER_PARAMETERS},
    }


def encode(payload):
    return json.dumps(payload).encode()


def test_power_parser_checks_hourly_contract_and_fill_values():
    payload = power_response()
    payload['properties']['parameter']['PRECTOTCORR']['2024010100'] = -999
    parsed = parse_power_payload(encode(payload), year=2024,
                                 latitude=9.9040188, longitude=77.8860417)
    assert len(parsed.hourly) == 8784  # leap-year UTC hours
    assert parsed.missing_by_parameter['PRECTOTCORR'] == 1
    assert parsed.hourly[datetime(2024, 1, 1, tzinfo=timezone.utc)]['PRECTOTCORR'] is None
    assert parsed.invalid_by_parameter['PRECTOTCORR'] == 0


@pytest.mark.parametrize('mutation', ('solar_time', 'wrong_unit', 'extra_hour', 'wrong_location'))
def test_power_parser_rejects_incompatible_payloads(mutation):
    payload = power_response()
    if mutation == 'solar_time':
        payload['header']['time_standard'] = 'LST'
    elif mutation == 'wrong_unit':
        payload['parameters']['WS10M']['units'] = 'km/h'
    elif mutation == 'extra_hour':
        payload['properties']['parameter']['T2M']['2025010100'] = 28.0
    else:
        payload['geometry']['coordinates'] = [90.0, 20.0, 200]
    with pytest.raises(ValueError):
        parse_power_payload(encode(payload), year=2024,
                            latitude=9.9040188, longitude=77.8860417)


def test_missing_power_hour_is_reported_as_a_gap():
    payload = power_response()
    del payload['properties']['parameter']['T2M']['2024010100']
    parsed = parse_power_payload(encode(payload), year=2024,
                                 latitude=9.9040188, longitude=77.8860417)
    assert parsed.missing_by_parameter['T2M'] == 1


def test_corrupt_cached_payload_is_rejected(tmp_path):
    payload = encode(power_response())

    class Transport:
        def get(self, base_url, parameters, timeout_seconds):
            return HttpResponse(200, payload, {}, base_url)

    client = NasaPowerHourlyClient(transport=Transport())
    client.fetch_year(2024, 9.9040188, 77.8860417, tmp_path)
    (tmp_path / 'nasa-power-hourly-2024.json').write_bytes(payload + b' ')
    with pytest.raises(ValueError, match='checksum mismatch'):
        client.fetch_year(2024, 9.9040188, 77.8860417, tmp_path)


def test_daily_rain_requires_all_hours_and_preserves_local_day():
    parsed = parse_power_payload(encode(power_response()), year=2024,
                                 latitude=9.9040188, longitude=77.8860417)
    hourly = dict(parsed.hourly)
    zone = ZoneInfo('Asia/Kolkata')
    result = _daily_rain(hourly, datetime(2024, 1, 2).date(), zone)
    assert result['observed'] == 24
    assert result['precipitation_mm'] == 24.0
    assert _daily_rain(hourly, datetime(2024, 1, 2).date(), zone,
                       hour_shift=1)['precipitation_mm'] == 24.0
    source_window = _window(hourly,
                            datetime(2024, 1, 2, 5, 30, tzinfo=zone),
                            datetime(2024, 1, 2, 7, 30, tzinfo=zone))
    assert source_window['precipitation_mm'] == 2.0
    assert source_window['wind_speed_kmh'] == 7.2
    hourly[datetime(2024, 1, 1, 19, tzinfo=timezone.utc)] = {
        **hourly[datetime(2024, 1, 1, 19, tzinfo=timezone.utc)],
        'PRECTOTCORR': None,
    }
    assert _daily_rain(hourly, datetime(2024, 1, 2).date(), zone)['quality'] == 'warning'
