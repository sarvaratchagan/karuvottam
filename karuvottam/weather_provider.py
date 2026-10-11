"""Approved historical-weather provider contract for the MVP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping


REQUIRED_HOURLY_VARIABLES = (
    'temperature_2m',
    'relative_humidity_2m',
    'precipitation',
    'cloud_cover',
    'wind_speed_10m',
    'wind_direction_10m',
    'pressure_msl',
)

EXPECTED_HOURLY_UNITS: Mapping[str, str] = MappingProxyType(
    {
        'time': 'iso8601',
        'temperature_2m': '°C',
        'relative_humidity_2m': '%',
        'precipitation': 'mm',
        'cloud_cover': '%',
        'wind_speed_10m': 'km/h',
        'wind_direction_10m': '°',
        'pressure_msl': 'hPa',
    }
)


@dataclass(frozen=True)
class HistoricalWeatherProvider:
    key: str
    display_name: str
    base_url: str
    model: str
    request_timezone: str
    coverage_start: date
    nominal_resolution: str
    update_delay_days: int
    hourly_variables: tuple[str, ...]
    expected_units: Mapping[str, str]
    data_kind: str
    attribution: str
    documentation_url: str


OPEN_METEO_ERA5 = HistoricalWeatherProvider(
    key='open-meteo',
    display_name='Open-Meteo Historical Weather API (ERA5)',
    base_url='https://archive-api.open-meteo.com/v1/archive',
    model='era5',
    request_timezone='UTC',
    coverage_start=date(1940, 1, 1),
    nominal_resolution='0.25° (~25 km)',
    update_delay_days=5,
    hourly_variables=REQUIRED_HOURLY_VARIABLES,
    expected_units=EXPECTED_HOURLY_UNITS,
    data_kind='reanalysis',
    attribution='Weather data by Open-Meteo.com; ERA5 reanalysis',
    documentation_url='https://open-meteo.com/en/docs/historical-weather-api',
)


def selected_historical_provider(
    provider_key: str,
    model: str,
    base_url: str,
) -> HistoricalWeatherProvider:
    """Resolve and validate the provider approved by T2.1."""
    if provider_key != OPEN_METEO_ERA5.key:
        raise ValueError(f'unsupported historical weather provider: {provider_key}')
    if model != OPEN_METEO_ERA5.model:
        raise ValueError(
            'the selected Open-Meteo historical contract requires model=era5'
        )
    if base_url.rstrip('/') != OPEN_METEO_ERA5.base_url:
        raise ValueError('unexpected Open-Meteo historical API base URL')
    return OPEN_METEO_ERA5
