"""Astronomical daily details for the Sidhariyal-style month grid.

These are independent Astronomy Engine calculations, not copied Sidhariyal
almanac values. Tithi is defined by geocentric lunar elongation at local
sunrise; rise/set times use the selected location and its local time zone.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from importlib.metadata import version
from math import floor
from zoneinfo import ZoneInfo

import astronomy

from karuvottam.tithi import TITHI_NAMES


SOURCE = 'Astronomy Engine'
CALCULATION_VERSION = version('astronomy-engine')


@dataclass(frozen=True)
class LunarPhaseDetail:
    name: str
    instant: datetime


@dataclass(frozen=True)
class AlmanacDay:
    gregorian: date
    dawn: datetime | None
    sunrise: datetime | None
    sunset: datetime | None
    dusk: datetime | None
    tithi_slot: int | None
    tithi_number: int | None
    tithi_name: str | None
    paksha_name: str | None
    tithi_end: datetime | None
    repeated_tithi: bool
    skipped_tithis: tuple[str, ...]
    phases: tuple[LunarPhaseDetail, ...]

    @property
    def tithi_label(self) -> str | None:
        if self.tithi_number is None or self.paksha_name is None:
            return None
        return f'{self.tithi_number}ம் {self.paksha_name}'


def _slot_label(slot: int) -> str:
    return f'{slot % 15 + 1}ம் {"வளர்பிறை" if slot < 15 else "தேய்பிறை"}'


def sunrise_tithi_change(previous_slot: int | None,
                        current_slot: int | None) -> tuple[bool, tuple[str, ...]]:
    """Identify tithis repeated or skipped between consecutive sunrises."""
    if previous_slot is None or current_slot is None:
        return False, ()
    if not 0 <= previous_slot < 30 or not 0 <= current_slot < 30:
        raise ValueError('tithi slot must be between 0 and 29')
    distance = (current_slot - previous_slot) % 30
    if distance == 0:
        return True, ()
    return False, tuple(_slot_label((previous_slot + offset) % 30)
                        for offset in range(1, distance))


def _astro_time(instant: datetime) -> astronomy.Time:
    utc = instant.astimezone(timezone.utc)
    return astronomy.Time.Make(utc.year, utc.month, utc.day, utc.hour,
                               utc.minute, utc.second + utc.microsecond / 1_000_000)


class CalendarAlmanac:
    def __init__(self, latitude: float, longitude: float, elevation_m: float,
                 timezone_name: str) -> None:
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError('invalid location coordinates')
        self.observer = astronomy.Observer(latitude, longitude, elevation_m)
        self.zone = ZoneInfo(timezone_name)

    def _rise_set(self, day: date, direction: astronomy.Direction) -> datetime | None:
        midnight = datetime.combine(day, time.min, tzinfo=self.zone)
        result = astronomy.SearchRiseSet(astronomy.Body.Sun, self.observer,
                                         direction, _astro_time(midnight), 1.0)
        if result is None:
            return None
        local = result.Utc().replace(tzinfo=timezone.utc).astimezone(self.zone)
        return local if local.date() == day else None

    def _twilight(self, day: date, direction: astronomy.Direction) -> datetime | None:
        midnight = datetime.combine(day, time.min, tzinfo=self.zone)
        result = astronomy.SearchAltitude(astronomy.Body.Sun, self.observer,
                                           direction, _astro_time(midnight), 1.0, -6.0)
        if result is None:
            return None
        local = result.Utc().replace(tzinfo=timezone.utc).astimezone(self.zone)
        return local if local.date() == day else None

    def _tithi(self, sunrise: datetime | None) -> tuple[int | None, int | None, str | None, str | None, datetime | None]:
        if sunrise is None:
            return None, None, None, None, None
        angle = astronomy.MoonPhase(_astro_time(sunrise))
        slot = min(29, floor(angle / 12.0))
        paksha = 'வளர்பிறை' if slot < 15 else 'தேய்பிறை'
        number = slot % 15 + 1
        name = ('பௌர்ணமி' if slot == 14 else
                'அமாவாசை' if slot == 29 else TITHI_NAMES[number - 1])
        next_angle = ((slot + 1) * 12) % 360
        boundary = astronomy.SearchMoonPhase(next_angle, _astro_time(sunrise), 3.0)
        end = (boundary.Utc().replace(tzinfo=timezone.utc).astimezone(self.zone)
               if boundary is not None else None)
        return slot, number, name, paksha, end

    def _phases(self, start: datetime, end: datetime) -> dict[date, list[LunarPhaseDetail]]:
        events: dict[date, list[LunarPhaseDetail]] = {}
        for angle, name in ((0.0, 'அமாவாசை'), (180.0, 'பௌர்ணமி')):
            cursor = start - timedelta(seconds=1)
            while True:
                result = astronomy.SearchMoonPhase(angle, _astro_time(cursor), 40.0)
                if result is None:
                    break
                instant = result.Utc().replace(tzinfo=timezone.utc).astimezone(self.zone)
                if instant >= end:
                    break
                if instant >= start:
                    events.setdefault(instant.date(), []).append(LunarPhaseDetail(name, instant))
                cursor = instant + timedelta(seconds=1)
        return events

    def build(self, start: date, end_exclusive: date) -> dict[date, AlmanacDay]:
        if end_exclusive <= start:
            raise ValueError('end date must follow start date')
        start_local = datetime.combine(start, time.min, tzinfo=self.zone)
        end_local = datetime.combine(end_exclusive, time.min, tzinfo=self.zone)
        phases = self._phases(start_local, end_local)
        details: dict[date, AlmanacDay] = {}
        previous_sunrise = self._rise_set(start - timedelta(days=1), astronomy.Direction.Rise)
        previous_slot = (min(29, floor(astronomy.MoonPhase(_astro_time(previous_sunrise)) / 12.0))
                         if previous_sunrise is not None else None)
        day = start
        while day < end_exclusive:
            dawn = self._twilight(day, astronomy.Direction.Rise)
            sunrise = self._rise_set(day, astronomy.Direction.Rise)
            sunset = self._rise_set(day, astronomy.Direction.Set)
            dusk = self._twilight(day, astronomy.Direction.Set)
            slot, number, name, paksha, tithi_end = self._tithi(sunrise)
            repeated, skipped = sunrise_tithi_change(previous_slot, slot)
            details[day] = AlmanacDay(day, dawn, sunrise, sunset, dusk, slot, number,
                                      name, paksha, tithi_end, repeated, skipped,
                                      tuple(phases.get(day, ())))
            previous_slot = slot
            day += timedelta(days=1)
        return details
