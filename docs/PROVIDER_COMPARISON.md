# T9.8 — ERA5 / NASA POWER provider comparison

The reference run compares Open-Meteo ERA5 observations already stored for the
target location with independently downloaded NASA POWER hourly data. It covers
the UTC weather interval **2015-07-01 through 2025-12-01**, needed for the
**2015–2024 Karuvottam evaluation seasons**. The generated report is
[`data/exports/provider-comparison-2015-2024/provider_comparison.md`](../data/exports/provider-comparison-2015-2024/provider_comparison.md).

## Reproduce

```bash
.venv/bin/python -m karuvottam.provider_comparison \
  --dataset data/exports/evaluation-2015-2024/evaluation_dataset.csv \
  --dataset-manifest data/exports/evaluation-2015-2024/manifest.json \
  --baseline data/exports/baseline-comparison-2015-2024/baseline_predictions.csv \
  --baseline-manifest data/exports/baseline-comparison-2015-2024/baseline_manifest.json \
  --database data/karuvottam.sqlite3 \
  --output data/exports/provider-comparison-2015-2024
```

The runner checks the ERA5 dataset and baseline-prediction checksums, requests
POWER in UTC with seven hourly fields, validates units and all expected hour
keys, and saves every raw annual response plus its hash and retrieval metadata.
Later runs reuse verified raw files. It reports fill values, invalid values,
coverage, matched-hour differences, local-day rainfall differences, and the
effect on the same 2015–2021 training / 2022–2024 evaluation split. NASA POWER
wind is converted from m/s to km/h. Its mm/hour precipitation is summed over
one-hour slots; missing hours are never filled with zero.

The NASA-based evaluation dataset is built from the same Karuvottam windows
and target dates as the ERA5 dataset. The existing T6.2 baseline and T6.3
metric services are then rerun using NASA features **and** NASA rainfall
outcomes. The ERA5 metrics are recalculated from the stored baseline predictions
for a matched comparison. The runner does not switch the production weather
provider or publish probabilities.

## Reference findings

| Measure | Result |
|---|---:|
| Matched UTC hours for six comparable fields | 91,368 / 91,368 |
| POWER fill/invalid values across seven requested fields | 0 / 0 |
| Hourly precipitation mean absolute difference | 0.164481 mm |
| Local-day rainfall mean absolute difference | 2.475038 mm over 3,200 days |
| Wet/dry labels that differ at 0.1 mm | 625 / 3,200 days |
| POWER hour-start sensitivity: changed wet/dry labels | 24 / 3,200 days |

| Provider | Seasonal MAE / Brier | Karuvottam MAE / Brier | Combined MAE / Brier |
|---|---:|---:|---:|
| ERA5 | 3.238575 / 0.215086 | 3.688333 / 0.262616 | 3.559379 / 0.218682 |
| POWER | 3.141054 / 0.160269 | 3.305646 / 0.204977 | 3.004275 / 0.174813 |

On POWER, the combined model improves rainfall MAE versus the seasonal
baseline but worsens Brier score. On ERA5, neither candidate improves both.
Therefore this provider comparison does not change the existing publication
hold. The point estimates here do not replace the paired uncertainty and
calibration gates in T6.5/T8.8.

## Interpretation limits

- Both products are gridded estimates, not independent rain-gauge truth. High
  completeness does not establish local accuracy or API uptime.
- POWER `PS` is **surface pressure**; ERA5 `pressure_msl` is **sea-level
  pressure**. Their availability is reported, but their values are not directly
  differenced.
- POWER's documentation specifies hourly averages, mm/hour precipitation and
  UTC selection, but does not establish the same hour-boundary convention as
  ERA5's preceding-hour accumulation. The runner uses matching UTC labels for
  the main analysis and reports a +1-hour POWER shift as a sensitivity check.
- The providers use different spatial grids and source products. Agreement
  measures are descriptive and cannot establish which product is correct.
- This is historical reanalysis comparison, not a live gauge feed or a
  00/12 UTC ECMWF IFS HRES forecast-run integration.

## Source contracts

- [NASA POWER Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
- [NASA POWER API status and response codes](https://power.larc.nasa.gov/docs/services/api/)
- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Original T2.1 provider selection](WEATHER_PROVIDER_EVALUATION.md)
