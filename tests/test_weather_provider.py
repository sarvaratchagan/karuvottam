from datetime import date

import pytest

from karuvottam.weather_provider import (
    EXPECTED_HOURLY_UNITS,
    OPEN_METEO_ERA5,
    REQUIRED_HOURLY_VARIABLES,
    selected_historical_provider,
)


def test_selected_provider_contract_covers_every_required_hourly_field():
    assert OPEN_METEO_ERA5.hourly_variables == REQUIRED_HOURLY_VARIABLES
    assert set(REQUIRED_HOURLY_VARIABLES) == {
        'temperature_2m',
        'relative_humidity_2m',
        'precipitation',
        'cloud_cover',
        'wind_speed_10m',
        'wind_direction_10m',
        'pressure_msl',
    }
    assert set(EXPECTED_HOURLY_UNITS) == {'time', *REQUIRED_HOURLY_VARIABLES}


def test_selected_provider_is_pinned_to_consistent_era5_utc_data():
    assert OPEN_METEO_ERA5.key == 'open-meteo'
    assert OPEN_METEO_ERA5.model == 'era5'
    assert OPEN_METEO_ERA5.request_timezone == 'UTC'
    assert OPEN_METEO_ERA5.coverage_start == date(1940, 1, 1)
    assert OPEN_METEO_ERA5.update_delay_days == 5
    assert OPEN_METEO_ERA5.data_kind == 'reanalysis'


def test_provider_resolution_rejects_unapproved_model_or_endpoint():
    assert selected_historical_provider(
        'open-meteo',
        'era5',
        'https://archive-api.open-meteo.com/v1/archive',
    ) is OPEN_METEO_ERA5

    with pytest.raises(ValueError, match='requires model=era5'):
        selected_historical_provider(
            'open-meteo',
            'era5_land',
            'https://archive-api.open-meteo.com/v1/archive',
        )
    with pytest.raises(ValueError, match='unexpected'):
        selected_historical_provider(
            'open-meteo',
            'era5',
            'https://example.test/archive',
        )
