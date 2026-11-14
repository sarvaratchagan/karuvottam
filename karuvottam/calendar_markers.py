"""Map calculated Karuvottam window boundaries onto monthly calendar days."""

from dataclasses import dataclass
from datetime import date, datetime

from karuvottam.windows import KaruvottamWindowEngine, WindowUnavailable


@dataclass(frozen=True)
class WindowMarker:
    season_name: str
    boundary: str
    instant: datetime

    @property
    def label(self) -> str:
        boundary_tamil = 'தொடக்கம்' if self.boundary == 'start' else 'முடிவு'
        return f'கருவோட்டம் {boundary_tamil}'


@dataclass(frozen=True)
class WindowMarkers:
    by_date: dict[date, tuple[WindowMarker, ...]]
    unavailable: tuple[str, ...]


def markers_for_month(engine: KaruvottamWindowEngine,
                      start: date, end_exclusive: date) -> WindowMarkers:
    if end_exclusive <= start:
        raise ValueError('end date must follow start date')
    found: dict[date, list[WindowMarker]] = {}
    unavailable: list[str] = []
    # The previous year's Margazhi window can end in January. The current
    # year's Aadi and Margazhi windows can start/end within the viewed month.
    for season_year in range(start.year - 1, end_exclusive.year + 1):
        for season_type in ('aadi', 'margazhi'):
            try:
                window = engine.generate(season_type, season_year)
            except WindowUnavailable:
                unavailable.append(f'{season_type} {season_year}')
                continue
            for boundary, instant in (('start', window.start_datetime_local),
                                      ('end', window.end_datetime_local)):
                if start <= instant.date() < end_exclusive:
                    marker = WindowMarker(window.season_name_tamil, boundary, instant)
                    found.setdefault(instant.date(), []).append(marker)
    return WindowMarkers(
        {day: tuple(sorted(values, key=lambda value: value.instant))
         for day, values in found.items()},
        tuple(unavailable),
    )
