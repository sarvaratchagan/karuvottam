"""Generation of complete Karuvottam observation windows."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from karuvottam.calendar_engine import CalendarRule
from karuvottam.lunar_events import LunarEvent, LunarEventEngine, LunarEventUnavailable
from karuvottam.sunrise import SunriseResult


SEASON_DEFINITIONS = {
    'aadi': {'tamil_month': 4, 'duration_hours': 18 * 24, 'name_tamil': 'ஆடி'},
    'margazhi': {'tamil_month': 9, 'duration_hours': 11 * 24, 'name_tamil': 'மார்கழி'},
}


class WindowUnavailable(RuntimeError):
    """Raised when an observation window cannot be generated."""


@dataclass(frozen=True)
class KaruvottamWindow:
    season_type: str
    season_year: int
    start_datetime_local: datetime
    end_datetime_local: datetime
    duration_hours: int
    trigger_event: LunarEvent
    sunrise: SunriseResult | None
    rule_version: str
    status: str = 'calculated'

    @property
    def season_name_tamil(self) -> str:
        return SEASON_DEFINITIONS[self.season_type]['name_tamil']

    def as_record(self) -> dict[str, object]:
        """Return the fields needed by the planned window persistence layer."""
        return {
            'season_type': self.season_type,
            'season_year': self.season_year,
            'start_datetime_local': self.start_datetime_local,
            'end_datetime_local': self.end_datetime_local,
            'duration_hours': self.duration_hours,
            'trigger_event': self.trigger_event.as_record(),
            'sunrise': self.sunrise.as_record() if self.sunrise else None,
            'rule_version': self.rule_version,
            'status': self.status,
        }


class KaruvottamWindowEngine:
    def __init__(
        self,
        calendar_rule: CalendarRule,
        lunar_engine: LunarEventEngine,
        margazhi_anchor_year: int = 2026,
        margazhi_anchor_phase: str = 'new_moon',
    ) -> None:
        if margazhi_anchor_year < 1:
            raise ValueError('margazhi_anchor_year must be positive')
        if margazhi_anchor_phase not in {'new_moon', 'full_moon'}:
            raise ValueError('margazhi_anchor_phase must be new_moon or full_moon')
        self.calendar_rule = calendar_rule
        self.lunar_engine = lunar_engine
        self.margazhi_anchor_year = margazhi_anchor_year
        self.margazhi_anchor_phase = margazhi_anchor_phase

    def margazhi_event_type_for_year(self, season_year: int) -> str:
        """Alternate the Margazhi trigger phase every civil/Tamil season year."""
        same_parity = (season_year - self.margazhi_anchor_year) % 2 == 0
        if same_parity:
            return self.margazhi_anchor_phase
        return 'full_moon' if self.margazhi_anchor_phase == 'new_moon' else 'new_moon'

    def generate(self, season_type: str, season_year: int) -> KaruvottamWindow:
        try:
            definition = SEASON_DEFINITIONS[season_type]
        except KeyError as exc:
            raise ValueError(f'unsupported season type: {season_type}') from exc
        if season_year < 1:
            raise ValueError('season_year must be positive')

        try:
            if season_type == 'aadi':
                trigger_event = self.lunar_engine.first_event_for_tamil_month(
                    season_year,
                    definition['tamil_month'],
                    self.calendar_rule,
                )
            else:
                trigger_event = self.lunar_engine.phase_for_tamil_month(
                    season_year,
                    definition['tamil_month'],
                    self.calendar_rule,
                    self.margazhi_event_type_for_year(season_year),
                )
        except LunarEventUnavailable as exc:
            raise WindowUnavailable(
                f'unable to generate {season_type} window for {season_year}'
            ) from exc

        duration_hours = definition['duration_hours']
        start = trigger_event.event_datetime_local
        end = start + timedelta(hours=duration_hours)
        return KaruvottamWindow(
            season_type=season_type,
            season_year=season_year,
            start_datetime_local=start,
            end_datetime_local=end,
            duration_hours=duration_hours,
            trigger_event=trigger_event,
            sunrise=None,
            rule_version=self.calendar_rule.version,
        )

    def generate_year(self, season_year: int) -> dict[str, KaruvottamWindow]:
        return {
            season_type: self.generate(season_type, season_year)
            for season_type in SEASON_DEFINITIONS
        }
