# Deterministic Karuvottam Research Index

**Model version:** `research-index-1.0`

**Status:** Experimental research aid; not a rain probability or validated forecast

## Purpose

This rule combines weather observed inside a Karuvottam window into one reproducible 0–100 research index. It exists to support later historical comparison and backtesting. A score of 70 does **not** mean a 70% chance of rain, and the score must not be displayed with a percent sign or probability wording.

## Input and quality gate

The engine consumes normalized hourly `WeatherObservation` records and their `WeatherQualityReport` from T2.4.

- An invalid quality report produces no score.
- At least 80% of expected hours must be represented.
- Each required field must be present in at least 80% of accepted records.
- Required fields are hourly precipitation, relative humidity, cloud cover, temperature, and wind speed.
- Duplicate, out-of-range, and outside-window records cause the quality report to be invalid.
- Interpolated values are allowed only with a visible `warning` quality flag.
- Missing or insufficient input returns `status=unavailable` and explicit reason codes; it never creates substitute values.

Wind direction and pressure are retained in source data but are not scored in version 1.0. Direction requires a validated moisture-source/sector rule, and pressure requires a locally evaluated tendency rule before either can be assigned points responsibly.

## Calculation

For every required field, the arithmetic mean is calculated across accepted, available records. Piecewise-linear interpolation between the following anchors produces component points:

| Component | Maximum | Mean-value → point anchors |
|---|---:|---|
| Hourly precipitation (mm) | 30 | `0→0`, `0.1→6`, `1→18`, `5→30` |
| Relative humidity (%) | 25 | `≤50→0`, `70→10`, `85→20`, `100→25` |
| Cloud cover (%) | 20 | `≤20→0`, `50→8`, `80→16`, `100→20` |
| Temperature (°C) | 10 | `≤24→10`, `30→5`, `≥36→0` |
| Wind speed (km/h) | 15 | `0→0`, `8→5`, `20→12`, `≥35→15` |

Values outside the outer anchors use the nearest endpoint. Component points are rounded to two decimal places and summed to a maximum of 100.

The weights are transparent starting hypotheses, not fitted coefficients. Precipitation, humidity, and cloud receive the largest weights because they most directly describe wet/cloudy conditions during the observation window. Temperature and wind are lower-weight contextual proxies. These choices must be tested against later observed rainfall before any operational interpretation.

## Output contract

An available result contains:

- `score` and `maximum_score=100`;
- `model_version`;
- the fixed label `experimental_research_index_not_probability`;
- source quality flag and reason codes;
- each component's field, mean, coverage, points, and maximum points.

Unavailable results contain `score=None`. Identical input records and quality reports produce identical output. Record ordering does not alter means or the resulting score.

## Limitations

This version does not establish causality, forecast horizon, rain category, rainfall amount, or calibrated confidence. It summarizes conditions observed during a Karuvottam window. T4.2 will define rain categories independently; T4.3 will map traceable outputs to dates; T6 will determine whether this index adds value over seasonal/climatology baselines.
