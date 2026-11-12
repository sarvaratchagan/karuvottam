from datetime import datetime, timezone

import pytest

from karuvottam.data_access import WeatherObservation
from karuvottam.rain_categories import (
    CLASSIFICATION_BASIS,
    THRESHOLD_VERSION,
    RainCategoryEngine,
)


@pytest.mark.parametrize(
    ('amount', 'expected_category', 'expected_tamil'),
    [
        (0.0, 'no_rain', 'மழையின்மை'),
        (0.099999, 'no_rain', 'மழையின்மை'),
        (0.1, 'drizzle', 'தூறல் / இலேசான மழை'),
        (2.499999, 'drizzle', 'தூறல் / இலேசான மழை'),
        (2.5, 'moderate', 'மிதமான மழை'),
        (7.499999, 'moderate', 'மிதமான மழை'),
        (7.5, 'heavy', 'கனமழை'),
        (500.0, 'heavy', 'கனமழை'),
    ],
)
def test_exact_hourly_boundary_values(amount, expected_category, expected_tamil):
    result = RainCategoryEngine().classify(amount, 60)

    assert result.status == 'classified'
    assert result.category == expected_category
    assert result.label_tamil == expected_tamil
    assert result.interval_minutes == 60
    assert result.threshold_version == THRESHOLD_VERSION
    assert result.classification_basis == CLASSIFICATION_BASIS
    assert 'probability' not in result.classification_basis


@pytest.mark.parametrize(
    ('amount', 'interval', 'reason'),
    [
        (None, 60, 'missing_precipitation'),
        (1.0, None, 'missing_interval'),
        (1.0, 30, 'unsupported_interval'),
        (1.0, 1440, 'unsupported_interval'),
    ],
)
def test_missing_or_unsupported_input_is_unavailable(amount, interval, reason):
    result = RainCategoryEngine().classify(amount, interval)

    assert not result.is_available
    assert result.category is None
    assert result.label_tamil == 'தரவு இல்லை'
    assert result.reason_code == reason


@pytest.mark.parametrize(
    ('amount', 'interval', 'message'),
    [
        (-0.01, 60, 'finite non-negative'),
        (float('nan'), 60, 'finite non-negative'),
        (float('inf'), 60, 'finite non-negative'),
        (True, 60, 'finite non-negative'),
        (1.0, 0, 'positive'),
        (1.0, 60.0, 'integer'),
        (1.0, True, 'integer'),
    ],
)
def test_invalid_values_fail_explicitly(amount, interval, message):
    with pytest.raises(ValueError, match=message):
        RainCategoryEngine().classify(amount, interval)


def test_weather_observation_adapter_uses_declared_interval():
    observed = datetime(2026, 7, 1, tzinfo=timezone.utc)
    observation = WeatherObservation(
        location_id=1,
        observed_at_utc=observed,
        observed_at_local=observed,
        source='test',
        quality_flag='valid',
        precipitation_mm=2.5,
        precipitation_interval_minutes=60,
    )

    result = RainCategoryEngine().classify_observation(observation)

    assert result.category == 'moderate'


def test_drizzle_label_has_explicit_amount_proxy_caveat():
    result = RainCategoryEngine().classify(0.5, 60)

    assert result.category == 'drizzle'
    assert result.caveat == (
        'amount_based_light_rain_proxy_not_observed_droplet_classification'
    )
