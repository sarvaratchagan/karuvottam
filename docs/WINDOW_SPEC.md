# Karuvottam Observation Window Generation

**Rule version:** 2.0 (inherited from the configured calendar rule)

**Boundary convention:** half-open `[start, end)`

## Generation rules

### Aadi

1. Under the project calendar, Aadi 1 is June 21: the day after the configured end of the Sun's northward movement/Mithuna transition.
2. Search after local midnight at Aadi 1 for the first new moon or full moon.
3. Use that lunar event's exact `Asia/Kolkata` timestamp as the included observation start.
4. Add 432 hours (18 full days) to obtain the excluded end.

### Margazhi

1. Resolve Margazhi 1 (November 21 with the default calendar rule).
2. Select the required new moon or full moon after that boundary. The phase alternates every year.
3. Use that event's exact local timestamp as the included observation start.
4. Observe continuously, day and night, for 264 hours (11 full days), ending at the excluded timestamp.

The alternating phase is made reproducible by two configuration values. Defaults are `2026` and `new_moon`, so 2026 is an Amavasai year, 2027 is a Pournami year, and the pattern repeats. Change the anchor only when an authoritative project decision establishes a different reference year.

No Chaturdashi offset, four-day settling period, sunrise adjustment, placeholder date, or midnight fallback is applied to active version-2 windows. A lunar-event failure makes the window explicitly unavailable.

## Season definitions

| Season | Modified Tamil month | Exact duration |
|---|---:|---:|
| Aadi | 4 | 432 hours (18 full days) |
| Margazhi | 9 | 264 hours (11 full days) |

## Provenance

Each calculated window retains the season/year, timezone-aware local boundaries, exact duration, selected lunar event and provider metadata, calendar-rule version, and calculation status. The legacy optional `sunrise` field is `null` for version-2 windows.
