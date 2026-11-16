"""Public-page-matched Sidhariyal month dates for the calendar UI.

The public monthly page does not expose its calculation algorithm. These
Gregorian month starts were checked against its 2026 and 2027 year views.
Future years use the same observed civil-date pattern and are labelled as
projections in the UI; this module is not used by the forecast rule engine.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from karuvottam.calendar_engine import TAMIL_MONTHS


RULE_VERSION = 'sidhariyal-public-2026-2027-pattern-v1'
# Month 1 is Chithirai. Months 11 and 12 belong to the next Gregorian year.
MONTH_STARTS = (
    (3, 21), (4, 20), (5, 21), (6, 21), (7, 23), (8, 23),
    (9, 23), (10, 23), (11, 22), (12, 22), (1, 20), (2, 19),
)
WEEKDAYS_TAMIL = ('ஞாயிறு', 'திங்கள்', 'செவ்வாய்', 'புதன்', 'வியாழன்', 'வெள்ளி', 'சனி')


@dataclass(frozen=True)
class SidhariyalDay:
    gregorian: date
    day: int
    month: int
    month_name: str
    year: int


@dataclass(frozen=True)
class SidhariyalMonth:
    year: int
    month: int
    month_name: str
    start: date
    end_exclusive: date
    weeks: tuple[tuple[SidhariyalDay | None, ...], ...]
    previous_year: int
    previous_month: int
    next_year: int
    next_month: int
    verified: bool


class SidhariyalCalendar:
    """Generate a Sunday-first month grid without fetching a remote page."""

    @staticmethod
    def month_start(year: int, month: int) -> date:
        if not 1 <= year <= 9998 or not 1 <= month <= 12:
            raise ValueError('invalid Sidhariyal year or month')
        civil_month, civil_day = MONTH_STARTS[month - 1]
        return date(year + (month >= 11), civil_month, civil_day)

    def from_gregorian(self, day: date) -> SidhariyalDay:
        if not 2 <= day.year <= 9998:
            raise ValueError('date outside supported calendar range')
        year = day.year if day >= self.month_start(day.year, 1) else day.year - 1
        for month in range(12, 0, -1):
            start = self.month_start(year, month)
            if day >= start:
                return SidhariyalDay(day, (day - start).days + 1,
                                     month, TAMIL_MONTHS[month - 1], year)
        raise ValueError('date outside supported calendar range')

    def build(self, year: int, month: int) -> SidhariyalMonth:
        start = self.month_start(year, month)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        end = self.month_start(next_year, next_month)
        # Python uses Monday=0; display Sunday in the first column.
        offset = (start.weekday() + 1) % 7
        cells: list[SidhariyalDay | None] = [None] * offset
        for index in range((end - start).days):
            civil_day = start + timedelta(days=index)
            cells.append(SidhariyalDay(civil_day, index + 1, month,
                                      TAMIL_MONTHS[month - 1], year))
        cells.extend([None] * (-len(cells) % 7))
        weeks = tuple(tuple(cells[i:i + 7]) for i in range(0, len(cells), 7))
        return SidhariyalMonth(year, month, TAMIL_MONTHS[month - 1], start, end,
                               weeks, prev_year, prev_month, next_year, next_month,
                               year in (2026, 2027))
