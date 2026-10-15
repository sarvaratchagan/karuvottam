# Karuvottam Time-Mapping Specification

**Specification version:** 2.0

**Project timezone:** `Asia/Kolkata`

## Timestamp and boundary rules

- Observation windows use timezone-aware half-open intervals: `[start, end)`.
- Provider UTC timestamps are converted to `Asia/Kolkata` before a local date is derived.
- Aadi lasts exactly 432 hours (18 days).
- Margazhi lasts exactly 264 hours (11 days), with continuous day-and-night observation.
- Naive timestamps are invalid.

## Daily forecast boundaries

Forecast periods use inclusive local dates: `[start_date, end_date]`.

1. Convert the source observation-window end to `Asia/Kolkata`.
2. Take its local calendar date.
3. The next local date is forecast day 1.
4. The end is `start + (number_of_days - 1)`.

Year N Aadi observations map to 180 days beginning after year N's Margazhi window ends. Year N Margazhi observations map to 140 days beginning after year N+1's Aadi window ends.

For the version-2 2026 cycle:

- Margazhi ends `2026-12-20 06:22 Asia/Kolkata`; its Aadi-derived 180-day period is `2026-12-21` through `2027-06-18`.
- The 2027 Aadi window ends on local date `2027-07-22`; its Margazhi-derived 140-day period is `2027-07-23` through `2027-12-09`.

## Required invariants

- `aadi_end - aadi_start == 432 hours`.
- `margazhi_end - margazhi_start == 264 hours`.
- Inclusive forecast counts are exactly 180 or 140 days.
- UTC-to-local conversion occurs before selecting the following date.
- Invalid naive timestamps and non-positive period lengths fail explicitly.

Hour-level experimental ratios mentioned in the broader plan are outside this daily mapping specification and require a separate versioned rule before use.
