"""Read model for the Tamil application-status dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from karuvottam.data_access import (
    DataAccess,
    DataAccessError,
    LocationRecord,
    PredictionRunRecord,
    WeatherObservationRecord,
)
from karuvottam.windows import KaruvottamWindow, KaruvottamWindowEngine


@dataclass(frozen=True)
class DashboardWindow:
    state: str
    state_tamil: str
    window: KaruvottamWindow


@dataclass(frozen=True)
class DashboardStatus:
    location_name: str
    latitude: float
    longitude: float
    timezone_name: str
    location_record: LocationRecord | None
    window: DashboardWindow
    latest_observation: WeatherObservationRecord | None
    latest_forecast: PredictionRunRecord | None
    database_available: bool
    warnings: tuple[str, ...]
    checked_at_local: datetime


class StatusDashboardService:
    """Combine configured, calculated, and persisted application status."""

    _ACCEPTABLE_QUALITY_FLAGS = {'valid', 'verified', 'calculated'}

    def __init__(
        self,
        data_access: DataAccess,
        window_engine: KaruvottamWindowEngine,
        *,
        location_name: str,
        latitude: float,
        longitude: float,
        timezone_name: str,
    ) -> None:
        self.data_access = data_access
        self.window_engine = window_engine
        self.location_name = location_name
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_name = timezone_name
        self.local_timezone = ZoneInfo(timezone_name)

    def build(self, now: datetime | None = None) -> DashboardStatus:
        checked_at = now or datetime.now(timezone.utc)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError('now must be timezone-aware')
        checked_at_local = checked_at.astimezone(self.local_timezone)
        dashboard_window = self._current_or_next_window(checked_at_local)

        location_record = None
        latest_observation = None
        latest_forecast = None
        database_available = True
        warnings: list[str] = []

        try:
            with self.data_access.transaction() as work:
                location_record = self._configured_location(
                    work.locations.list_active()
                )
                if location_record is not None:
                    latest_observation = (
                        work.weather_observations.latest_for_location(
                            location_record.id
                        )
                    )
                    latest_forecast = work.forecasts.latest_run(location_record.id)
        except DataAccessError:
            database_available = False
            warnings.append(
                'தரவுத்தளம் தயாராக இல்லை; migration-ஐ இயக்கி மீண்டும் முயற்சிக்கவும்.'
            )

        if database_available and location_record is None:
            warnings.append(
                'அமைக்கப்பட்ட இடம் செயலில் உள்ள இடமாகத் தரவுத்தளத்தில் இல்லை.'
            )
        if database_available and latest_observation is None:
            warnings.append('இந்த இடத்திற்கான வானிலைத் தரவு இன்னும் சேமிக்கப்படவில்லை.')
        elif latest_observation is not None:
            quality_parts = set(latest_observation.quality_flag.split('+'))
            if not quality_parts.issubset(self._ACCEPTABLE_QUALITY_FLAGS):
                warnings.append(
                    'சமீபத்திய வானிலைத் தரத்தின் தரநிலையைச் சரிபார்க்கவும்: '
                    f'{latest_observation.quality_flag}.'
                )
        if database_available and latest_forecast is None:
            warnings.append('முன்னறிவிப்பு ஓட்டம் இன்னும் உருவாக்கப்படவில்லை.')
        elif latest_forecast is not None and latest_forecast.status != 'validated':
            warnings.append(
                'சமீபத்திய முன்னறிவிப்பு இன்னும் சரிபார்க்கப்படவில்லை; '
                'ஆராய்ச்சி முடிவாக மட்டும் பயன்படுத்தவும்.'
            )

        return DashboardStatus(
            location_name=self.location_name,
            latitude=self.latitude,
            longitude=self.longitude,
            timezone_name=self.timezone_name,
            location_record=location_record,
            window=dashboard_window,
            latest_observation=latest_observation,
            latest_forecast=latest_forecast,
            database_available=database_available,
            warnings=tuple(warnings),
            checked_at_local=checked_at_local,
        )

    def _current_or_next_window(self, now_local: datetime) -> DashboardWindow:
        windows = sorted(
            (
                self.window_engine.generate(season_type, year)
                for year in range(now_local.year - 1, now_local.year + 3)
                for season_type in ('aadi', 'margazhi')
            ),
            key=lambda item: item.start_datetime_local,
        )
        for window in windows:
            if window.start_datetime_local <= now_local < window.end_datetime_local:
                return DashboardWindow('active', 'தற்போது நடைபெறுகிறது', window)
        for window in windows:
            if window.start_datetime_local > now_local:
                return DashboardWindow('upcoming', 'அடுத்து வருகிறது', window)
        raise RuntimeError('unable to determine the current or next window')

    def _configured_location(
        self,
        locations: tuple[LocationRecord, ...],
    ) -> LocationRecord | None:
        for location in locations:
            if (
                location.name == self.location_name
                and abs(location.latitude - self.latitude) < 0.000001
                and abs(location.longitude - self.longitude) < 0.000001
                and location.timezone_name == self.timezone_name
            ):
                return location
        return None
