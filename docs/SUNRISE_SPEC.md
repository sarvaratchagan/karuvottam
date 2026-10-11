# Local Sunrise and Four-Day Settling Rule

**Calculation provider:** Astronomy Engine 2.1.19

**Project location:** `9.9040188, 77.8860417`

**Project timezone:** `Asia/Kolkata`

## Settling-period convention

The selected trigger is first converted to the project timezone. For Aadi the trigger is the preceding Chaturdashi start; for Margazhi it is the selected lunar event. Its local calendar date is the reference date. The target sunrise date is:

`selected trigger local date + 4 calendar days`

The observation start is the sunrise calculated for that target local date. It is not midnight and it is not the lunar event timestamp plus exactly 96 hours. This convention is versioned here so later changes to the interpretation can be reviewed and tested explicitly.

Example using the revised 2026 Aadi trigger:

- Reference full moon: approximately `2026-06-30 05:27 Asia/Kolkata`
- Shukla Chaturdashi start: approximately `2026-06-28 00:44 Asia/Kolkata`
- Settling target date: `2026-07-02`
- Local sunrise: approximately `2026-07-02 06:01 Asia/Kolkata`

## Sunrise calculation

The calculation uses Astronomy Engine's `SearchRiseSet` function with the Sun, `Direction.Rise`, the configured observer coordinates and elevation, and a search beginning at local midnight converted to UTC. The search is limited to the requested local date.

Astronomy Engine defines sunrise using the first visible top edge of the Sun and accounts for apparent solar radius and typical atmospheric refraction. Its documentation notes that actual refraction varies with weather, so this remains a calculated standard sunrise rather than a direct observation.

- [Astronomy Engine `SearchRiseSet` documentation](https://github.com/cosinekitty/astronomy/blob/master/source/python/README.md#searchrisesetbody-observer-direction-starttime-limitdays-metersaboveground--00--optionaltime)

## Data and failure behavior

Each result retains the target local date, UTC and local sunrise timestamps, coordinates, elevation, provider, provider version, and quality flag. Missing results, provider errors, naive timestamps, and results outside the requested local date produce an explicit unavailable state. Midnight is never substituted for a missing sunrise.

The default elevation is currently zero metres until a verified elevation for the target site is supplied. It is configurable through `KARUVOTTAM_ELEVATION_M`.
