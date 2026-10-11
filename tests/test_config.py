from zoneinfo import ZoneInfo

import pytest

from config import PROJECT_ROOT, ConfigurationError, Settings


def test_default_settings_match_project_plan():
    settings = Settings.from_env({})

    assert settings.latitude == pytest.approx(9.9040188)
    assert settings.longitude == pytest.approx(77.8860417)
    assert settings.elevation_m == 0
    assert settings.timezone == ZoneInfo('Asia/Kolkata')
    assert settings.chithirai_reference_parts == (3, 21)
    assert settings.calendar_rule_version == '1.0'
    assert settings.weather_provider == 'open-meteo'
    assert settings.weather_model == 'era5'
    assert settings.weather_api_key is None
    assert settings.weather_timeout_seconds == 30
    assert settings.weather_retry_attempts == 3
    assert settings.weather_retry_backoff_seconds == 1
    assert settings.weather_raw_data_dir == PROJECT_ROOT / 'data/imports/weather/raw'
    assert settings.database_path == PROJECT_ROOT / 'data/karuvottam.sqlite3'
    assert settings.port == 5000


def test_environment_overrides_are_applied():
    settings = Settings.from_env(
        {
            'KARUVOTTAM_LOCATION_NAME': 'Test location',
            'KARUVOTTAM_LATITUDE': '10.5',
            'KARUVOTTAM_LONGITUDE': '78.25',
            'KARUVOTTAM_ELEVATION_M': '125.5',
            'KARUVOTTAM_TIMEZONE': 'UTC',
            'KARUVOTTAM_CHITHIRAI_REFERENCE': '03-22',
            'KARUVOTTAM_CALENDAR_RULE_VERSION': '2.0',
            'KARUVOTTAM_WEATHER_PROVIDER': 'test-provider',
            'KARUVOTTAM_WEATHER_MODEL': 'test-model',
            'KARUVOTTAM_WEATHER_API_BASE_URL': 'https://example.test/weather',
            'KARUVOTTAM_WEATHER_API_KEY': 'test-secret',
            'KARUVOTTAM_WEATHER_TIMEOUT_SECONDS': '15.5',
            'KARUVOTTAM_WEATHER_RETRY_ATTEMPTS': '4',
            'KARUVOTTAM_WEATHER_RETRY_BACKOFF_SECONDS': '0.25',
            'KARUVOTTAM_WEATHER_RAW_DATA_DIR': 'data/test-weather',
            'KARUVOTTAM_DATABASE_PATH': 'data/test.sqlite3',
            'KARUVOTTAM_PORT': '5050',
        }
    )

    assert settings.location_name == 'Test location'
    assert settings.latitude == 10.5
    assert settings.longitude == 78.25
    assert settings.elevation_m == 125.5
    assert settings.timezone_name == 'UTC'
    assert settings.chithirai_reference_parts == (3, 22)
    assert settings.calendar_rule_version == '2.0'
    assert settings.weather_provider == 'test-provider'
    assert settings.weather_model == 'test-model'
    assert settings.weather_api_base_url == 'https://example.test/weather'
    assert settings.weather_api_key == 'test-secret'
    assert settings.weather_timeout_seconds == 15.5
    assert settings.weather_retry_attempts == 4
    assert settings.weather_retry_backoff_seconds == 0.25
    assert settings.weather_raw_data_dir == PROJECT_ROOT / 'data/test-weather'
    assert settings.database_path == PROJECT_ROOT / 'data/test.sqlite3'
    assert settings.port == 5050


@pytest.mark.parametrize(
    ('name', 'value', 'message'),
    [
        ('KARUVOTTAM_LATITUDE', 'north', 'must be a number'),
        ('KARUVOTTAM_LATITUDE', '91', 'between -90 and 90'),
        ('KARUVOTTAM_LONGITUDE', '-181', 'between -180 and 180'),
        ('KARUVOTTAM_ELEVATION_M', 'high', 'must be a number'),
        ('KARUVOTTAM_TIMEZONE', 'Not/A_Zone', 'is not available'),
        ('KARUVOTTAM_CHITHIRAI_REFERENCE', 'March-21', 'must use MM-DD'),
        ('KARUVOTTAM_DATABASE_PATH', '', 'must not be blank'),
        ('KARUVOTTAM_WEATHER_TIMEOUT_SECONDS', '0', 'greater than zero'),
        ('KARUVOTTAM_WEATHER_RETRY_ATTEMPTS', '0', 'at least 1'),
        ('KARUVOTTAM_WEATHER_RETRY_BACKOFF_SECONDS', '-1', 'must not be negative'),
        ('KARUVOTTAM_PORT', 'zero', 'must be an integer'),
        ('KARUVOTTAM_PORT', '70000', 'between 1 and 65535'),
    ],
)
def test_invalid_settings_fail_with_clear_message(name, value, message):
    with pytest.raises(ConfigurationError, match=message):
        Settings.from_env({name: value})


def test_blank_api_key_is_not_treated_as_a_secret():
    settings = Settings.from_env({'KARUVOTTAM_WEATHER_API_KEY': ''})

    assert settings.weather_api_key is None
