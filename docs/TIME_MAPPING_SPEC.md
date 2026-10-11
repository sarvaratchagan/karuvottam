# Karuvottam Time-Mapping Specification

**Specification version:** 1.0

**Project timezone:** `Asia/Kolkata`

**Status:** Active for the MVP

This document fixes the boundary conventions for the Aadi and Margazhi observation windows and their corresponding daily experimental forecast periods. It implements the project-defined mapping rules; it does not claim that those rules have established meteorological predictive value.

## 1. Timestamp rules

1. Observation-window boundaries are timezone-aware timestamps.
2. The authoritative project timezone is `Asia/Kolkata`.
3. Provider timestamps must retain their source timezone or UTC offset. UTC timestamps must be converted to `Asia/Kolkata` before deriving a local calendar date.
4. A timestamp without timezone information is invalid for forecast-period mapping.
5. Persistence will retain UTC and local timestamps where the schema requires both. UTC must never be interpreted directly as local time.

## 2. Observation-window boundaries

Observation windows use a half-open interval: **`[start, end)`**.

- The start timestamp is included.
- The end timestamp is excluded.
- Aadi duration is exactly 18 days, or 432 hours.
- Margazhi duration is exactly 10 days and 8 hours, or 248 hours.
- The decimal notation `10.33 days` is descriptive only and must not be rounded or used as the computational duration.

Example: a Margazhi window beginning at `2026-12-21 00:00 Asia/Kolkata` ends at `2026-12-31 08:00 Asia/Kolkata`. The observation at exactly the end timestamp is outside that window.

## 3. Daily forecast boundaries

Daily forecast periods use inclusive local dates: **`[start_date, end_date]`**.

1. Convert the observation-window end timestamp to `Asia/Kolkata`.
2. Take its local calendar date.
3. The next local calendar date is forecast **day 1**.
4. The end date is `start_date + (number_of_days - 1)`.
5. Therefore, both start and end dates are included in the advertised 180-day or 140-day total.

This definition avoids carrying the observation end's clock time into a daily forecast. For example, a window ending at 08:00 produces a forecast beginning at the next local date, not at 08:00 on that date.

## 4. Aadi mapping

Year N Aadi observations map to 180 inclusive local dates beginning on the local date after the end of the year N Margazhi observation window.

For the current 2026 placeholder window:

- Margazhi window: `[2026-12-21 00:00, 2026-12-31 08:00)` in `Asia/Kolkata`
- Forecast day 1: `2027-01-01`
- Forecast day 180: `2027-06-29`
- Inclusive date count: 180

## 5. Margazhi mapping

Year N–N+1 Margazhi observations map to 140 inclusive local dates beginning on the local date after the end of the year N+1 Aadi observation window.

For the current 2026–27 placeholder cycle:

- 2027 Aadi window: `[2027-07-22 00:00, 2027-08-09 00:00)` in `Asia/Kolkata`
- Forecast day 1: `2027-08-10`
- Forecast day 140: `2027-12-27`
- Inclusive date count: 140

## 6. Hour-level mapping

The plan also defines Aadi `1 observation hour ↔ 10 forecast hours` and Margazhi `1 observation hour ↔ 13.55 forecast hours`. Those hour-level transformations are not defined by this daily specification and must not be inferred from it. A separate versioned specification and tests are required before producing hour-level forecasts.

## 7. Required invariants

- `observation_end - observation_start == 432 hours` for Aadi.
- `observation_end - observation_start == 248 hours` for Margazhi.
- `forecast_end - forecast_start + 1 day == 180 days` for an Aadi-derived daily period.
- `forecast_end - forecast_start + 1 day == 140 days` for a Margazhi-derived daily period.
- Converting a UTC window end to local time happens before selecting the next calendar date.
- Invalid naive timestamps and non-positive period lengths fail explicitly.
