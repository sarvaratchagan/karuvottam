# Lunar Event Calculation

**Calculation provider:** Astronomy Engine 2.1.19

**Project timezone:** `Asia/Kolkata`

**Status:** Active for the MVP

## Selection rule

For Aadi of a requested modified Tamil year:

1. Calculate the month's Gregorian start using the versioned modified Tamil calendar rule.
2. Treat the start as local midnight in `Asia/Kolkata`.
3. Convert that instant to UTC.
4. Search independently for the next new moon and the next full moon.
5. Select whichever valid event occurs first after the month-start instant.
6. Retain the event type, UTC timestamp, local timestamp, provider, provider version, and quality flag.

First-quarter and third-quarter phases are not eligible trigger events. The calculation searches up to 40 days; no result or a provider failure produces an explicit unavailable state rather than a fabricated event.

The selected Aadi event is the final observation trigger.

For Margazhi, the requested phase alternates by year rather than choosing whichever phase occurs first. The default reproducibility anchor is 2026 = new moon (Amavasai), followed by 2027 = full moon (Pournami), then alternating. The engine searches for that requested phase after Margazhi 1 and uses its exact local timestamp as the trigger.

## Definitions and implementation source

Astronomy Engine defines new moon as a 0-degree geocentric ecliptic longitude separation between Moon and Sun, and full moon as 180 degrees. Its Python API provides `SearchMoonPhase` for these events and UTC conversion through `Time.Utc()`.

- [Astronomy Engine Python documentation](https://github.com/cosinekitty/astronomy/blob/master/source/python/README.md)
- [astronomy-engine 2.1.19 on PyPI](https://pypi.org/project/astronomy-engine/2.1.19/)

The dependency is pinned to 2.1.19 so recorded calculation versions remain reproducible. It is self-contained during calculation and does not require an external network request.

## Independent reference check

Integration tests compare selected 2026 events with the U.S. Naval Observatory's published UTC primary-phase table. A tolerance of two minutes is allowed because the sources may use different numerical models or rounding conventions.

- [U.S. Naval Observatory: 2026 primary Moon phases](https://aa.usno.navy.mil/calculated/moon/phases?year=2026)

Reference examples:

- Modified Aadi 2026 begins at `2026-06-21 00:00 Asia/Kolkata`; the selected event is the full moon near `2026-06-29 23:56 UTC`.
- Modified Margazhi 2026 begins at `2026-11-21 00:00 Asia/Kolkata`; under the default alternation anchor, its selected event is the new moon near `2026-12-09 00:52 UTC`.

## Persistence boundary

`LunarEvent.as_record()` exposes the fields required by the planned `lunar_events` database table. Database persistence will be added in T3.1; until then, the event object is the traceable calculation record used by the application.
