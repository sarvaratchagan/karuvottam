"""Read model for the traceable Karuvottam calendar page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from karuvottam.data_access import (
    DataAccess,
    DataAccessError,
    KaruvottamWindowRecord,
)
from karuvottam.windows import KaruvottamWindow, KaruvottamWindowEngine


PHASE_NAMES_TAMIL = {
    'new_moon': 'அமாவாசை',
    'full_moon': 'பௌர்ணமி',
}


@dataclass(frozen=True)
class CalendarWindowItem:
    window: KaruvottamWindow
    tamil_month_start: date
    persisted: KaruvottamWindowRecord | None

    @property
    def persistence_state_tamil(self) -> str:
        if self.persisted is None:
            return 'கணக்கிடப்பட்டது; இன்னும் சேமிக்கப்படவில்லை'
        return f'தரவுத்தளத்தில் சேமிக்கப்பட்டது · பதிவு #{self.persisted.id}'


@dataclass(frozen=True)
class AlternationItem:
    year: int
    event_type: str
    event_type_tamil: str
    selected: bool


@dataclass(frozen=True)
class CalendarView:
    year: int
    windows: tuple[CalendarWindowItem, ...]
    alternation: tuple[AlternationItem, ...]
    anchor_year: int
    anchor_phase: str
    anchor_phase_tamil: str
    calendar_reference: str
    calendar_rule_version: str
    database_available: bool
    persistence_warning: str | None


class CalendarViewService:
    """Generate calendar windows and attach any matching stored records."""

    def __init__(
        self,
        data_access: DataAccess,
        window_engine: KaruvottamWindowEngine,
    ) -> None:
        self.data_access = data_access
        self.window_engine = window_engine

    def build(self, year: int) -> CalendarView:
        if year < 1:
            raise ValueError('year must be positive')

        generated = tuple(
            self.window_engine.generate(season_type, year)
            for season_type in ('aadi', 'margazhi')
        )
        persisted_by_type: dict[str, KaruvottamWindowRecord | None] = {
            window.season_type: None for window in generated
        }
        database_available = True
        persistence_warning = None
        try:
            with self.data_access.transaction() as work:
                for window in generated:
                    persisted_by_type[window.season_type] = (
                        work.karuvottam_windows.find(
                            window.season_type,
                            window.season_year,
                            window.rule_version,
                        )
                    )
        except DataAccessError:
            database_available = False
            persistence_warning = (
                'தரவுத்தளம் தயாராக இல்லாததால் சேமிப்பு நிலையைச் சரிபார்க்க முடியவில்லை. '
                'காட்டப்படும் காலங்கள் விதிகளிலிருந்து புதிதாகக் கணக்கிடப்பட்டவை.'
            )

        calendar_rule = self.window_engine.calendar_rule
        windows = tuple(
            CalendarWindowItem(
                window=window,
                tamil_month_start=calendar_rule.to_gregorian(
                    year,
                    4 if window.season_type == 'aadi' else 9,
                    1,
                ),
                persisted=persisted_by_type[window.season_type],
            )
            for window in generated
        )
        alternation = tuple(
            self._alternation_item(candidate_year, year)
            for candidate_year in range(year - 2, year + 3)
        )
        anchor_phase = self.window_engine.margazhi_anchor_phase
        return CalendarView(
            year=year,
            windows=windows,
            alternation=alternation,
            anchor_year=self.window_engine.margazhi_anchor_year,
            anchor_phase=anchor_phase,
            anchor_phase_tamil=PHASE_NAMES_TAMIL[anchor_phase],
            calendar_reference=calendar_rule.reference_label,
            calendar_rule_version=calendar_rule.version,
            database_available=database_available,
            persistence_warning=persistence_warning,
        )

    def _alternation_item(self, year: int, selected_year: int) -> AlternationItem:
        event_type = self.window_engine.margazhi_event_type_for_year(year)
        return AlternationItem(
            year=year,
            event_type=event_type,
            event_type_tamil=PHASE_NAMES_TAMIL[event_type],
            selected=year == selected_year,
        )
