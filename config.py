"""Validated application configuration loaded from environment variables."""

from dataclasses import dataclass
from datetime import date
from os import environ
from pathlib import Path
from typing import Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent


class ConfigurationError(ValueError):
    """Raised when application configuration is invalid."""


def _parse_float(values: Mapping[str, str], name: str, default: str) -> float:
    raw_value = values.get(name, default)
    try:
        return float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f'{name} must be a number') from exc


def _parse_int(values: Mapping[str, str], name: str, default: str) -> int:
    raw_value = values.get(name, default)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(f'{name} must be an integer') from exc


@dataclass(frozen=True)
class Settings:
    location_name: str
    latitude: float
    longitude: float
    elevation_m: float
    timezone_name: str
    chithirai_reference: str
    calendar_rule_version: str
    margazhi_alternation_anchor_year: int
    margazhi_alternation_anchor_phase: str
    weather_provider: str
    weather_model: str
    weather_api_base_url: str
    weather_api_key: str | None
    weather_timeout_seconds: float
    weather_retry_attempts: int
    weather_retry_backoff_seconds: float
    weather_raw_data_dir: Path
    database_path: Path
    port: int

    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def chithirai_reference_parts(self) -> tuple[int, int]:
        month, day = self.chithirai_reference.split('-', maxsplit=1)
        return int(month), int(day)

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> 'Settings':
        values = environ if values is None else values
        latitude = _parse_float(values, 'KARUVOTTAM_LATITUDE', '9.9040188')
        longitude = _parse_float(values, 'KARUVOTTAM_LONGITUDE', '77.8860417')
        elevation_m = _parse_float(values, 'KARUVOTTAM_ELEVATION_M', '0')
        port = _parse_int(values, 'KARUVOTTAM_PORT', '5000')
        weather_timeout_seconds = _parse_float(
            values, 'KARUVOTTAM_WEATHER_TIMEOUT_SECONDS', '30'
        )
        weather_retry_attempts = _parse_int(
            values, 'KARUVOTTAM_WEATHER_RETRY_ATTEMPTS', '3'
        )
        weather_retry_backoff_seconds = _parse_float(
            values, 'KARUVOTTAM_WEATHER_RETRY_BACKOFF_SECONDS', '1'
        )
        margazhi_anchor_year = _parse_int(
            values, 'KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_YEAR', '2026'
        )
        margazhi_anchor_phase = values.get(
            'KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_PHASE', 'new_moon'
        ).strip().lower()
        timezone_name = values.get('KARUVOTTAM_TIMEZONE', 'Asia/Kolkata')
        reference = values.get('KARUVOTTAM_CHITHIRAI_REFERENCE', '03-21')
        database_path_value = values.get(
            'KARUVOTTAM_DATABASE_PATH', 'data/karuvottam.sqlite3'
        ).strip()
        if not database_path_value:
            raise ConfigurationError('KARUVOTTAM_DATABASE_PATH must not be blank')
        database_path = Path(database_path_value).expanduser()
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        raw_data_dir = Path(
            values.get(
                'KARUVOTTAM_WEATHER_RAW_DATA_DIR', 'data/imports/weather/raw'
            )
        ).expanduser()
        if not raw_data_dir.is_absolute():
            raw_data_dir = PROJECT_ROOT / raw_data_dir

        if not -90 <= latitude <= 90:
            raise ConfigurationError('KARUVOTTAM_LATITUDE must be between -90 and 90')
        if not -180 <= longitude <= 180:
            raise ConfigurationError('KARUVOTTAM_LONGITUDE must be between -180 and 180')
        if not 1 <= port <= 65535:
            raise ConfigurationError('KARUVOTTAM_PORT must be between 1 and 65535')
        if weather_timeout_seconds <= 0:
            raise ConfigurationError(
                'KARUVOTTAM_WEATHER_TIMEOUT_SECONDS must be greater than zero'
            )
        if weather_retry_attempts < 1:
            raise ConfigurationError(
                'KARUVOTTAM_WEATHER_RETRY_ATTEMPTS must be at least 1'
            )
        if weather_retry_backoff_seconds < 0:
            raise ConfigurationError(
                'KARUVOTTAM_WEATHER_RETRY_BACKOFF_SECONDS must not be negative'
            )
        if margazhi_anchor_year < 1:
            raise ConfigurationError(
                'KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_YEAR must be positive'
            )
        if margazhi_anchor_phase not in {'new_moon', 'full_moon'}:
            raise ConfigurationError(
                'KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_PHASE must be '
                'new_moon or full_moon'
            )

        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ConfigurationError(
                f'KARUVOTTAM_TIMEZONE is not available: {timezone_name}'
            ) from exc

        try:
            month_text, day_text = reference.split('-', maxsplit=1)
            date(2000, int(month_text), int(day_text))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                'KARUVOTTAM_CHITHIRAI_REFERENCE must use MM-DD format'
            ) from exc

        return cls(
            location_name=values.get(
                'KARUVOTTAM_LOCATION_NAME',
                'பொருப்புமேட்டுப்பட்டி, உசிலம்பட்டி வட்டம், மதுரை மாவட்டம்',
            ),
            latitude=latitude,
            longitude=longitude,
            elevation_m=elevation_m,
            timezone_name=timezone_name,
            chithirai_reference=reference,
            calendar_rule_version=values.get('KARUVOTTAM_CALENDAR_RULE_VERSION', '2.0'),
            margazhi_alternation_anchor_year=margazhi_anchor_year,
            margazhi_alternation_anchor_phase=margazhi_anchor_phase,
            weather_provider=values.get('KARUVOTTAM_WEATHER_PROVIDER', 'open-meteo'),
            weather_model=values.get('KARUVOTTAM_WEATHER_MODEL', 'era5'),
            weather_api_base_url=values.get(
                'KARUVOTTAM_WEATHER_API_BASE_URL',
                'https://archive-api.open-meteo.com/v1/archive',
            ),
            weather_api_key=values.get('KARUVOTTAM_WEATHER_API_KEY') or None,
            weather_timeout_seconds=weather_timeout_seconds,
            weather_retry_attempts=weather_retry_attempts,
            weather_retry_backoff_seconds=weather_retry_backoff_seconds,
            weather_raw_data_dir=raw_data_dir.resolve(),
            database_path=database_path.resolve(),
            port=port,
        )


load_dotenv(dotenv_path=Path(__file__).with_name('.env'))
settings = Settings.from_env()
