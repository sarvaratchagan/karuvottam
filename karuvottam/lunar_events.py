"""Lunar phase selection for Karuvottam observation triggers."""

from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from importlib.metadata import version
from typing import Protocol
from zoneinfo import ZoneInfo

import astronomy

from karuvottam.calendar_engine import CalendarRule


NEW_MOON_ANGLE = 0.0
FULL_MOON_ANGLE = 180.0
DEFAULT_SEARCH_DAYS = 40.0
PHASE_ANGLES = {
    'new_moon': NEW_MOON_ANGLE,
    'full_moon': FULL_MOON_ANGLE,
}


class LunarEventUnavailable(RuntimeError):
    """Raised when a lunar event cannot be calculated."""


class PhaseProvider(Protocol):
    source: str
    calculation_version: str

    def search_phase(
        self,
        phase_angle: float,
        start_utc: datetime,
        limit_days: float,
    ) -> datetime | None: ...


class AstronomyEngineProvider:
    """Adapter around Astronomy Engine's geocentric moon-phase search."""

    source = 'Astronomy Engine'
    calculation_version = version('astronomy-engine')

    @staticmethod
    def search_phase(
        phase_angle: float,
        start_utc: datetime,
        limit_days: float,
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
        result = astronomy.SearchMoonPhase(phase_angle, start, limit_days)
        if result is None:
            return None
        return result.Utc().replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class LunarEvent:
    event_type: str
    event_datetime_utc: datetime
    event_datetime_local: datetime
    source: str
    calculation_version: str
    quality_flag: str = 'calculated'

    @property
    def event_type_tamil(self) -> str:
        return 'அமாவாசை' if self.event_type == 'new_moon' else 'பௌர்ணமி'

    def as_record(self) -> dict[str, object]:
        """Return fields ready for the future lunar_events persistence table."""
        return asdict(self)


class LunarEventEngine:
    def __init__(
        self,
        local_timezone: ZoneInfo,
        provider: PhaseProvider | None = None,
    ) -> None:
        self.local_timezone = local_timezone
        self.provider = provider or AstronomyEngineProvider()

    def first_new_or_full_after(self, start_local: datetime) -> LunarEvent:
        if start_local.tzinfo is None or start_local.utcoffset() is None:
            raise ValueError('start_local must be timezone-aware')

        start_utc = start_local.astimezone(timezone.utc)
        try:
            candidates = [
                ('new_moon', self.provider.search_phase(
                    NEW_MOON_ANGLE,
                    start_utc,
                    DEFAULT_SEARCH_DAYS,
                )),
                ('full_moon', self.provider.search_phase(
                    FULL_MOON_ANGLE,
                    start_utc,
                    DEFAULT_SEARCH_DAYS,
                )),
            ]
        except Exception as exc:
            raise LunarEventUnavailable('lunar phase provider failed') from exc

        available = []
        for event_type, event_time in candidates:
            if event_time is None:
                continue
            if event_time.tzinfo is None or event_time.utcoffset() is None:
                raise LunarEventUnavailable('lunar phase provider returned a naive timestamp')
            event_time = event_time.astimezone(timezone.utc)
            if event_time > start_utc:
                available.append((event_type, event_time))
        if not available:
            raise LunarEventUnavailable(
                f'no new or full moon found within {DEFAULT_SEARCH_DAYS:g} days'
            )

        event_type, event_utc = min(available, key=lambda candidate: candidate[1])
        return LunarEvent(
            event_type=event_type,
            event_datetime_utc=event_utc,
            event_datetime_local=event_utc.astimezone(self.local_timezone),
            source=self.provider.source,
            calculation_version=self.provider.calculation_version,
        )

    def first_phase_after(
        self,
        start_local: datetime,
        event_type: str,
    ) -> LunarEvent:
        """Return the first requested principal lunar phase after a local instant."""
        if start_local.tzinfo is None or start_local.utcoffset() is None:
            raise ValueError('start_local must be timezone-aware')
        try:
            phase_angle = PHASE_ANGLES[event_type]
        except KeyError as exc:
            raise ValueError(f'unsupported lunar event type: {event_type}') from exc

        start_utc = start_local.astimezone(timezone.utc)
        try:
            event_time = self.provider.search_phase(
                phase_angle,
                start_utc,
                DEFAULT_SEARCH_DAYS,
            )
        except Exception as exc:
            raise LunarEventUnavailable('lunar phase provider failed') from exc

        if event_time is None:
            raise LunarEventUnavailable(
                f'no {event_type} found within {DEFAULT_SEARCH_DAYS:g} days'
            )
        if event_time.tzinfo is None or event_time.utcoffset() is None:
            raise LunarEventUnavailable('lunar phase provider returned a naive timestamp')
        event_utc = event_time.astimezone(timezone.utc)
        if event_utc <= start_utc:
            raise LunarEventUnavailable(
                f'lunar phase provider returned {event_type} before search start'
            )
        return LunarEvent(
            event_type=event_type,
            event_datetime_utc=event_utc,
            event_datetime_local=event_utc.astimezone(self.local_timezone),
            source=self.provider.source,
            calculation_version=self.provider.calculation_version,
        )

    def first_event_for_tamil_month(
        self,
        tamil_year: int,
        tamil_month: int,
        calendar_rule: CalendarRule,
    ) -> LunarEvent:
        month_start = calendar_rule.to_gregorian(tamil_year, tamil_month, 1)
        start_local = datetime.combine(
            month_start,
            time.min,
            tzinfo=self.local_timezone,
        )
        return self.first_new_or_full_after(start_local)

    def phase_for_tamil_month(
        self,
        tamil_year: int,
        tamil_month: int,
        calendar_rule: CalendarRule,
        event_type: str,
    ) -> LunarEvent:
        """Return the requested phase after the configured Tamil month begins."""
        month_start = calendar_rule.to_gregorian(tamil_year, tamil_month, 1)
        start_local = datetime.combine(
            month_start,
            time.min,
            tzinfo=self.local_timezone,
        )
        return self.first_phase_after(start_local, event_type)
