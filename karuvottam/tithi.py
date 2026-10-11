"""Tithi boundary calculation for project-defined Karuvottam triggers."""

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from karuvottam.lunar_events import (
    AstronomyEngineProvider,
    LunarEvent,
    PhaseProvider,
)


TITHI_NAMES = (
    'பிரதமை',
    'த்விதியை',
    'த்ருதியை',
    'சதுர்த்தி',
    'பஞ்சமி',
    'ஷஷ்டி',
    'ஸப்தமி',
    'அஷ்டமி',
    'நவமி',
    'தசமி',
    'ஏகாதசி',
    'துவாதசி',
    'த்ரயோதசி',
    'சதுர்த்தசி',
    'பௌர்ணமி / அமாவாசை',
)

SHUKLA_CHATURDASHI_START_ANGLE = 156.0
KRISHNA_CHATURDASHI_START_ANGLE = 336.0
BACKWARD_SEARCH_DAYS = -5.0


class TithiUnavailable(RuntimeError):
    """Raised when the required tithi boundary cannot be calculated."""


@dataclass(frozen=True)
class TithiBoundary:
    paksha: str
    tithi_number: int
    tithi_name: str
    phase_angle_degrees: float
    event_datetime_utc: datetime
    event_datetime_local: datetime
    reference_lunar_event: LunarEvent
    source: str
    calculation_version: str
    quality_flag: str = 'calculated'

    @property
    def event_type(self) -> str:
        return f'{self.paksha}_chaturdashi_start'

    @property
    def event_type_tamil(self) -> str:
        paksha_name = 'சுக்கில பட்ச' if self.paksha == 'shukla' else 'கிருஷ்ண பட்ச'
        return f'{paksha_name} {self.tithi_name} தொடக்கம்'

    def as_record(self) -> dict[str, object]:
        return {
            'event_type': self.event_type,
            'paksha': self.paksha,
            'tithi_number': self.tithi_number,
            'tithi_name': self.tithi_name,
            'phase_angle_degrees': self.phase_angle_degrees,
            'event_datetime_utc': self.event_datetime_utc,
            'event_datetime_local': self.event_datetime_local,
            'reference_lunar_event': self.reference_lunar_event.as_record(),
            'source': self.source,
            'calculation_version': self.calculation_version,
            'quality_flag': self.quality_flag,
        }


class TithiEngine:
    def __init__(
        self,
        local_timezone: ZoneInfo,
        provider: PhaseProvider | None = None,
    ) -> None:
        self.local_timezone = local_timezone
        self.provider = provider or AstronomyEngineProvider()

    def chaturdashi_before(self, lunar_event: LunarEvent) -> TithiBoundary:
        if lunar_event.event_type == 'full_moon':
            paksha = 'shukla'
            angle = SHUKLA_CHATURDASHI_START_ANGLE
        elif lunar_event.event_type == 'new_moon':
            paksha = 'krishna'
            angle = KRISHNA_CHATURDASHI_START_ANGLE
        else:
            raise ValueError(f'unsupported lunar event: {lunar_event.event_type}')

        event_utc = lunar_event.event_datetime_utc.astimezone(timezone.utc)
        try:
            boundary_utc = self.provider.search_phase(
                angle,
                event_utc,
                BACKWARD_SEARCH_DAYS,
            )
        except Exception as exc:
            raise TithiUnavailable('tithi phase provider failed') from exc

        if boundary_utc is None:
            raise TithiUnavailable('Chaturdashi start was not found before lunar event')
        if boundary_utc.tzinfo is None or boundary_utc.utcoffset() is None:
            raise TithiUnavailable('tithi phase provider returned a naive timestamp')

        boundary_utc = boundary_utc.astimezone(timezone.utc)
        if boundary_utc >= event_utc:
            raise TithiUnavailable('Chaturdashi start must precede the lunar event')

        return TithiBoundary(
            paksha=paksha,
            tithi_number=14,
            tithi_name=TITHI_NAMES[13],
            phase_angle_degrees=angle,
            event_datetime_utc=boundary_utc,
            event_datetime_local=boundary_utc.astimezone(self.local_timezone),
            reference_lunar_event=lunar_event,
            source=self.provider.source,
            calculation_version=self.provider.calculation_version,
        )
