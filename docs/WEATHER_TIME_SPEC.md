# Weather timestamp and accumulation specification

This specification completes T2.3 for the selected Open-Meteo ERA5 historical
contract. It separates the timestamp attached to an hourly row from the time interval
represented by its precipitation value.

## Provider-hour meaning

Requests always use `timezone=UTC`. Open-Meteo ERA5 returns one label per exact UTC
hour. The label is stored as `observed_at_utc` and is the observation instant for the
instantaneous fields (temperature, humidity, cloud cover, wind, and pressure).

For example, provider label `2025-07-01T00:00` is normalized to:

```text
observed_at_utc   = 2025-07-01T00:00:00Z
observed_at_local = 2025-07-01T05:30:00+05:30  (Asia/Kolkata)
```

A timestamp without an offset is interpreted as UTC only because the request and
response metadata both require UTC. Explicit non-UTC offsets, non-hour boundaries,
duplicates, reverse order, and gaps are rejected instead of silently shifted.

The local timestamp is derived from the timezone stored on the referenced location,
not from the computer timezone or a global default. UTC and local values must represent
the same instant. This keeps a UTC hour on the correct local calendar date when an
offset crosses midnight.

## Precipitation interval

Open-Meteo defines hourly `precipitation` as the millimetre accumulation during the
preceding hour. The provider timestamp is therefore the interval end. The project uses
the mathematical boundary convention `(start, end]`:

```text
provider timestamp                    2025-07-01T00:00:00Z
precipitation_interval_start_utc       2025-06-30T23:00:00Z  (exclusive)
precipitation_interval_end_utc         2025-07-01T00:00:00Z  (inclusive)
precipitation_interval_minutes         60
```

The precipitation value belongs to that interval; it must not be moved to the local
date containing the interval start. Daily aggregation must assign or split intervals
using an explicitly chosen aggregation rule. Until such a rule is introduced, hourly
records retain both interval boundaries so no implicit date reassignment occurs.

## Persistence rules

- UTC values use canonical `YYYY-MM-DDTHH:MM:SSZ` text.
- Local values include their numeric UTC offset.
- All three precipitation interval fields are supplied together or all remain null.
- The interval end equals `observed_at_utc`.
- The stored duration equals the difference between the interval boundaries.
- New ERA5 rows always use a 60-minute interval.

Migration `002_weather_time_intervals.sql` adds these fields. It safely backfills
existing `open-meteo:era5` rows because their semantics are fixed by the pinned
provider contract. Rows from providers without declared interval semantics remain
null and must not be guessed.

## Examples around local midnight

| UTC provider label | Asia/Kolkata timestamp | Preceding precipitation interval (UTC) |
|---|---|---|
| `2025-06-30T18:00:00Z` | `2025-06-30T23:30:00+05:30` | `(17:00, 18:00]` |
| `2025-06-30T19:00:00Z` | `2025-07-01T00:30:00+05:30` | `(18:00, 19:00]` |

The two consecutive UTC records correctly fall on different local dates without
changing their identity key or accumulation periods.
