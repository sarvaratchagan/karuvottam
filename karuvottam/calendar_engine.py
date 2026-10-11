"""Versioned modified Tamil calendar used by this project.

This module converts dates between the Gregorian calendar and a
project-specific Tamil calendar. The Tamil New Year reference date
(Chithirai 1) and calendar rule version are configurable.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta


# Tamil month names in chronological order.
# The month index in this tuple corresponds to Tamil month numbers 1–12.
TAMIL_MONTHS = (
    'சித்திரை',
    'வைகாசி',
    'ஆனி',
    'ஆடி',
    'ஆவணி',
    'புரட்டாசி',
    'ஐப்பசி',
    'கார்த்திகை',
    'மார்கழி',
    'தை',
    'மாசி',
    'பங்குனி',
)


def _add_months(value: date, months: int) -> date:
    """Add calendar months to a date while preserving a valid day.

    If the original day does not exist in the target month, use the
    last valid day of that month. For example, adding one month to
    January 31 results in February 28 or 29, depending on the year.
    """
    # Convert the year and month into a single, zero-based month index.
    absolute_month = value.year * 12 + value.month - 1 + months

    # Convert the absolute month index back into a year and month.
    year, zero_based_month = divmod(absolute_month, 12)
    month = zero_based_month + 1

    # Prevent an invalid date by limiting the day to the target month's length.
    day = min(value.day, monthrange(year, month)[1])

    return date(year, month, day)


@dataclass(frozen=True)
class TamilDate:
    """Represent a date in the project's modified Tamil calendar.

    Attributes:
        year: Tamil calendar year, based on the configured reference date.
        month: Tamil month number, from 1 to 12.
        day: Day number within the Tamil month, starting at 1.
        month_name: Tamil name of the month.
        rule_version: Version of the calendar rules used for conversion.
    """

    year: int
    month: int
    day: int
    month_name: str
    rule_version: str

    def format_tamil(self) -> str:
        """Return the Tamil date in a human-readable format."""
        return f'{self.month_name} {self.day} / {self.year}'


@dataclass(frozen=True)
class CalendarRule:
    """Define the rules for converting Gregorian dates to Tamil dates.

    The reference month and day determine the start of each Tamil year.
    By default, Chithirai 1 is assumed to fall on March 21. This is a
    project-specific calendar convention, not a claim about the
    traditionally observed or officially published Tamil calendar.

    The version identifies the rule set used for a conversion.
    """

    # Gregorian month used as the beginning of the Tamil calendar year.
    reference_month: int = 3

    # Gregorian day used as Chithirai 1.
    reference_day: int = 21

    # Identifier for this set of calendar rules.
    version: str = '1.0'

    def __post_init__(self) -> None:
        """Validate the reference date and calendar rule version."""
        # Use a non-leap reference year to validate the month and day.
        # This also rejects February 29 as a fixed annual reference date.
        try:
            date(2000, self.reference_month, self.reference_day)
        except ValueError as exc:
            raise ValueError(
                'invalid Chithirai reference month and day'
            ) from exc

        # Require a non-empty version identifier.
        if not self.version.strip():
            raise ValueError('calendar rule version must not be blank')

    @property
    def reference_label(self) -> str:
        """Return the configured reference date as MM-DD."""
        return f'{self.reference_month:02d}-{self.reference_day:02d}'

    def year_start(self, tamil_year: int) -> date:
        """Return the Gregorian date on which the Tamil year begins."""
        return date(
            tamil_year,
            self.reference_month,
            self.reference_day,
        )

    def month_boundaries(self, tamil_year: int) -> tuple[date, ...]:
        """Calculate the Gregorian start dates of all Tamil months.

        Returns 13 boundary dates: the start of each of the 12 months
        and the start of the following Tamil year. These boundaries
        make it possible to calculate month lengths and convert dates.
        """
        start = self.year_start(tamil_year)

        # Generate month boundaries at offsets 0 through 12.
        # The final boundary marks the end of the Tamil calendar year.
        return tuple(_add_months(start, offset) for offset in range(13))

    def month_length(self, tamil_year: int, month: int) -> int:
        """Return the number of days in a specified Tamil month."""
        # Ensure that the requested month number is within 1–12.
        self._validate_month(month)

        boundaries = self.month_boundaries(tamil_year)

        # The difference between consecutive boundaries gives the
        # number of days in the requested month.
        return (boundaries[month] - boundaries[month - 1]).days

    def from_gregorian(self, value: date) -> TamilDate:
        """Convert a Gregorian date into the modified Tamil calendar."""
        # Determine whether the Gregorian date falls before or after
        # the configured Tamil New Year reference date in that year.
        current_year_start = self.year_start(value.year)
        tamil_year = (
            value.year if value >= current_year_start else value.year - 1
        )

        # Calculate all month boundaries for the identified Tamil year.
        boundaries = self.month_boundaries(tamil_year)

        # Find the month whose start is inclusive and whose end is exclusive.
        # This ensures that a boundary date belongs to the new month.
        for index, (start, end) in enumerate(
            zip(boundaries, boundaries[1:]),
            start=1,
        ):
            if start <= value < end:
                return TamilDate(
                    year=tamil_year,
                    month=index,
                    # Month days are numbered from 1 rather than 0.
                    day=(value - start).days + 1,
                    month_name=TAMIL_MONTHS[index - 1],
                    # Record which calendar rule version produced this date.
                    rule_version=self.version,
                )

        # This should not occur when the year and month boundaries are valid.
        raise ValueError(
            f'date is outside calculated Tamil year: {value.isoformat()}'
        )

    def to_gregorian(self, tamil_year: int, month: int, day: int) -> date:
        """Convert a Tamil calendar date into a Gregorian date.

        Raises:
            ValueError: If the month or day is outside the valid range.
        """
        # Validate the month before accessing its boundaries.
        self._validate_month(month)

        # Determine the valid day range for the specified Tamil month.
        length = self.month_length(tamil_year, month)

        # Reject day numbers that do not exist in the requested month.
        if not 1 <= day <= length:
            raise ValueError(
                f'day must be between 1 and {length} for this Tamil month'
            )

        # Get the Gregorian start date of the requested Tamil month.
        start = self.month_boundaries(tamil_year)[month - 1]

        # Add the zero-based day offset to obtain the Gregorian date.
        return start + timedelta(days=day - 1)

    @staticmethod
    def _validate_month(month: int) -> None:
        """Raise ValueError if the Tamil month number is outside 1–12."""
        if not 1 <= month <= len(TAMIL_MONTHS):
            raise ValueError('Tamil month must be between 1 and 12')