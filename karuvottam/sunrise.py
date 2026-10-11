"""Local sunrise calculation for Karuvottam observation starts."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from importlib.metadata import version
from typing import Protocol
from zoneinfo import ZoneInfo

import astronomy

SETTLING_DAYS = 4


class SunriseUnavailable(RuntimeError):
    """Raised when sunrise cannot be calculated for the requested local date."""


class SunriseProvider(Protocol):
    source: str
    calculation_version: str

    def search_sunrise(
        self,
        start_utc: datetime,
        latitude: float,
        longitude: float,
        elevation_m: float,
    ) -> datetime | None: ...


class TimedTrigger(Protocol):
    event_datetime_utc: datetime


class AstronomyEngineSunriseProvider:
    source = 'Astronomy Engine'
    calculation_version = version('astronomy-engine')

    @staticmethod
    def search_sunrise(
        start_utc: datetime,
        latitude: float,
        longitude: float,
        elevation_m: float,
    ) -> datetime | None:
        start_utc = start_utc.astimezone(timezone.utc)
        start = astronomy.Time.Make(
            start_utc.year,
            start_utc.month,
            start_utc.day,
            start_utc.hour,
            start_utc.minute,
            start_utc.second + start_utc.microsecond / 1_000_000,
        )
        observer = astronomy.Observer(latitude, longitude, elevation_m)
        result = astronomy.SearchRiseSet(
            astronomy.Body.Sun,
            observer,
            astronomy.Direction.Rise,
            start,
            1.0,
        )
        if result is None:
            return None
        return result.Utc().replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class SunriseResult:
    target_local_date: date
    sunrise_datetime_utc: datetime
    sunrise_datetime_local: datetime
    latitude: float
    longitude: float
    elevation_m: float
    source: str
    calculation_version: str
    quality_flag: str = 'calculated'

    def as_record(self) -> dict[str, object]:
        return asdict(self)


class SunriseEngine:
    def __init__(
        self,
        latitude: float,
        longitude: float,
        elevation_m: float,
        local_timezone: ZoneInfo,
        provider: SunriseProvider | None = None,
    ) -> None:
        if not -90 <= latitude <= 90:
            raise ValueError('latitude must be between -90 and 90')
        if not -180 <= longitude <= 180:
            raise ValueError('longitude must be between -180 and 180')
        self.latitude = latitude
        self.longitude = longitude
        self.elevation_m = elevation_m
        self.local_timezone = local_timezone
        self.provider = provider or AstronomyEngineSunriseProvider()

    def sunrise_for_local_date(self, target_date: date) -> SunriseResult:
        local_midnight = datetime.combine(
            target_date,
            time.min,
            tzinfo=self.local_timezone,
        )
        start_utc = local_midnight.astimezone(timezone.utc)
        try:
            sunrise_utc = self.provider.search_sunrise(
                start_utc,
                self.latitude,
                self.longitude,
                self.elevation_m,
            )
        except Exception as exc:
            raise SunriseUnavailable('sunrise provider failed') from exc

        if sunrise_utc is None:
            raise SunriseUnavailable(f'no sunrise found for {target_date.isoformat()}')
        if sunrise_utc.tzinfo is None or sunrise_utc.utcoffset() is None:
            raise SunriseUnavailable('sunrise provider returned a naive timestamp')

        sunrise_utc = sunrise_utc.astimezone(timezone.utc)
        sunrise_local = sunrise_utc.astimezone(self.local_timezone)
        if sunrise_local.date() != target_date:
            raise SunriseUnavailable(
                f'provider result is outside local date {target_date.isoformat()}'
            )

        return SunriseResult(
            target_local_date=target_date,
            sunrise_datetime_utc=sunrise_utc,
            sunrise_datetime_local=sunrise_local,
            latitude=self.latitude,
            longitude=self.longitude,
            elevation_m=self.elevation_m,
            source=self.provider.source,
            calculation_version=self.provider.calculation_version,
        )

    def sunrise_after_settling_period(
        self,
        lunar_event: TimedTrigger,
        settling_days: int = SETTLING_DAYS,
    ) -> SunriseResult:
        if settling_days < 0:
            raise ValueError('settling_days must not be negative')
        event_local = lunar_event.event_datetime_utc.astimezone(self.local_timezone)
        target_date = event_local.date() + timedelta(days=settling_days)
        return self.sunrise_for_local_date(target_date)
