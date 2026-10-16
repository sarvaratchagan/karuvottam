# Experimental Forecast Timeline

**Timeline model version:** `daily-timeline-1.0`

**Status:** Experimental index timeline; no calibrated probability or future rainfall-amount model

## Period mapping

Timelines contain inclusive local calendar dates in `Asia/Kolkata`:

- Year N Aadi source window → 180 dates beginning on the date after year N Margazhi ends.
- Year N Margazhi source window → 140 dates beginning on the date after year N+1 Aadi ends.

The mapping boundary is converted to `Asia/Kolkata` before its date is selected. Day 1 is the next local date, and the final date is `start + days - 1`.

For the version-2 2026 cycle:

- Aadi-derived timeline: `2026-12-21` through `2027-06-18` inclusive (180 entries).
- Margazhi-derived timeline: `2027-07-23` through `2027-12-09` inclusive (140 entries).

## Traceability contract

Every entry contains:

- one-based day number and local target date/midnight timestamp;
- source-window key (`season:year:rule-version`) and exact source boundaries;
- calendar rule, timeline model, research-score model, and rain-category threshold versions;
- generation timestamp, input-quality flag, status, and reason codes;
- nullable research score, rain probability, predicted amount, and category fields.

The source-window key provides a readable domain link. Migration `003_prediction_traceability.sql` and `work.forecasts.add_timeline(...)` persist the complete timeline atomically; `prediction_runs.input_window_id` provides the enforced database link to the persisted source window.

## Scientific guardrails

`research-index-1.0` summarizes the complete observation window. It has not been calibrated into future rainfall probability or rainfall amount. Consequently:

- an available index produces timeline status `experimental_index_only`;
- its numeric index may be shown as an experimental research score;
- `rain_probability_pct`, `predicted_rain_mm`, and `rain_category` remain null;
- the entry reason is `rain_amount_model_not_defined`;
- an unavailable score produces `no_data` for every target date, retaining the original reason;
- missing inputs never produce rotating, random, copied, or placeholder forecast values.

T4.2 categories apply only when a valid 60-minute rainfall amount exists. Applying them directly to a 0–100 research index would mix units and is prohibited. A later version may populate future categories only after a documented amount/category mapping is implemented and evaluated.

## Hour-level rule boundary

This version generates daily dates and does not silently apply the separate hour-level expansion rule. With the updated 11-day Margazhi window, an exact 140-day expansion would be `3360 / 264 = 12.727272…` future hours per observation hour, replacing the obsolete 13.55 value tied to the former 248-hour window. Hour-level output requires a separate versioned resampling specification before implementation.
