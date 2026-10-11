# Karuvottam Observation Window Generation

**Rule version:** inherited from the configured calendar rule

**Boundary convention:** half-open `[start, end)`

## Generation pipeline

For each season year:

1. Resolve the modified Tamil month start using the configured calendar rule.
2. Select the first eligible new moon or full moon after that month begins.
3. For Aadi, replace that reference event with the start of its preceding Shukla or Krishna Chaturdashi; for Margazhi, keep the lunar event as the trigger.
4. Convert the selected trigger to `Asia/Kolkata` and add four local calendar days.
5. Calculate local sunrise on that target date for the configured location.
6. Use that sunrise timestamp as the included window start.
7. Add the exact season duration to obtain the excluded window end.

No placeholder date or midnight fallback is allowed. A lunar-event or sunrise failure makes the window explicitly unavailable.

## Season definitions

| Season | Modified Tamil month | Exact duration |
|---|---:|---:|
| Aadi | 4 | 432 hours (18 full days) |
| Margazhi | 9 | 248 hours (10 days + 8 hours) |

The Margazhi duration is never calculated from a rounded `10.33` decimal value.

## Provenance

Each calculated window retains:

- season type and season year;
- timezone-aware local start and end timestamps;
- exact duration in hours;
- the final selected trigger, its reference lunar event where applicable, and provider metadata;
- the sunrise calculation and its location/provider metadata;
- calendar rule version and calculation status.

`KaruvottamWindow.as_record()` exposes these values for the persistence layer planned in T3.1.
