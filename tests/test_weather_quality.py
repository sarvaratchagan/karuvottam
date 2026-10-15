from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from karuvottam.data_access import WeatherObservation
from karuvottam.weather_quality import WeatherQualityValidator


START = datetime(2025, 7, 1, tzinfo=timezone.utc)


def _observation(hour=0, **overrides):
    observed = START + timedelta(hours=hour)
    values = {
        'location_id': 1,
        'observed_at_utc': observed,
        'observed_at_local': observed,
        'temperature_c': 27.0,
        'relative_humidity_pct': 75.0,
        'precipitation_mm': 1.2,
        'cloud_cover_pct': 80.0,
        'wind_speed_kmh': 12.0,
        'wind_direction_deg': 220.0,
        'pressure_hpa': 1005.0,
        'source': 'open-meteo:era5',
        'quality_flag': 'unvalidated_reanalysis',
    }
    values.update(overrides)
    return WeatherObservation(**values)


def test_complete_valid_window_has_full_coverage():
    report = WeatherQualityValidator().validate(
        [_observation(0), _observation(1)],
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=2),
    )

    assert report.overall_quality_flag == 'valid'
    assert report.expected_hours == 2
    assert report.received_records == 2
    assert report.unique_hours == 2
    assert report.accepted_records == 2
    assert report.rejected_records == 0
    assert report.valid_records == 2
    assert report.coverage_pct == 100.0
    assert report.missing_hours == ()
    assert [record.quality_flag for record in report.records] == ['valid', 'valid']


def test_missing_range_and_interpolation_flags_are_preserved():
    observations = [
        _observation(0, pressure_hpa=None),
        _observation(1, temperature_c=80),
        _observation(2, is_interpolated=True),
    ]

    report = WeatherQualityValidator().validate(
        observations,
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=3),
    )

    assert [record.quality_flag for record in report.records] == [
        'missing',
        'out_of_range',
        'interpolated',
    ]
    assert report.field_missing_counts == {'pressure_hpa': 1}
    assert report.field_out_of_range_counts == {'temperature_c': 1}
    assert report.missing_value_records == 1
    assert report.out_of_range_records == 1
    assert report.interpolated_records == 1
    assert report.rejected_records == 1
    assert report.overall_quality_flag == 'invalid'


def test_duplicate_rows_and_missing_hours_are_reported_separately():
    first = _observation(0)
    duplicate = replace(first, precipitation_mm=2.0)
    report = WeatherQualityValidator().validate(
        [first, duplicate, _observation(2)],
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=3),
    )

    assert [record.quality_flag for record in report.records] == [
        'valid',
        'duplicate',
        'valid',
    ]
    assert report.duplicate_records == 1
    assert report.rejected_records == 1
    assert report.unique_hours == 2
    assert report.coverage_pct == 66.67
    assert report.missing_hours == (START + timedelta(hours=1),)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), '27'])
def test_non_finite_and_non_numeric_values_are_out_of_range(value):
    report = WeatherQualityValidator().validate(
        [_observation(temperature_c=value)],
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=1),
    )

    assert report.records[0].quality_flag == 'out_of_range'
    assert report.records[0].issue_codes == ('out_of_range:temperature_c',)


@pytest.mark.parametrize(
    'field_name, value',
    [
        ('temperature_c', 65.1),
        ('relative_humidity_pct', 100.1),
        ('precipitation_mm', -0.1),
        ('cloud_cover_pct', 100.1),
        ('wind_speed_kmh', 300.1),
        ('wind_direction_deg', 360.1),
        ('pressure_hpa', 799.9),
    ],
)
def test_each_weather_field_has_an_enforced_range(field_name, value):
    report = WeatherQualityValidator().validate(
        [_observation(**{field_name: value})],
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=1),
    )

    assert report.records[0].issue_codes == (f'out_of_range:{field_name}',)
    assert report.field_out_of_range_counts == {field_name: 1}


def test_record_outside_requested_window_is_rejected():
    report = WeatherQualityValidator().validate(
        [_observation(hour=2)],
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=1),
    )

    assert report.records[0].quality_flag == 'outside_window'
    assert report.records[0].rejected is True
    assert report.unique_hours == 0
    assert report.coverage_pct == 0.0
    assert report.missing_hours == (START,)


def test_quality_window_requires_aware_exact_hours():
    validator = WeatherQualityValidator()

    with pytest.raises(ValueError, match='timezone-aware'):
        validator.validate(
            [],
            expected_start_utc=datetime(2025, 7, 1),
            expected_end_utc=START + timedelta(hours=1),
        )
    with pytest.raises(ValueError, match='exact hour'):
        validator.validate(
            [],
            expected_start_utc=START,
            expected_end_utc=START + timedelta(minutes=90),
        )
