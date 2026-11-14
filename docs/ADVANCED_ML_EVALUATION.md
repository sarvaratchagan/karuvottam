# T9.6 — Advanced ML historical evaluation

This is a **research-only** comparison of two candidates against the existing T6.4 rolling seasonal-climatology baseline. It does not replace the app's forecast engine or unlock public probability output.

## Reproduce

```bash
.venv/bin/pip install -r requirements-research.txt
.venv/bin/python -m karuvottam.advanced_ml_evaluation \
  --dataset data/exports/evaluation-2015-2024 \
  --baseline data/exports/rolling-validation-2015-2024 \
  --output data/exports/advanced-ml-2015-2024
.venv/bin/python -m karuvottam.advanced_ml_evaluation --verify
```

The evaluator verifies the T6.1 dataset CSV checksum, calendar/timeline/measurement versions, T6.4 rolling baseline CSV checksum and matching dataset key/hash before fitting. The output contains `advanced_predictions.csv`, `advanced_metrics.csv`, `advanced_reliability.csv`, `advanced_summary.json`, and `advanced_manifest.json` with SHA-256 hashes. `--verify` rechecks the input and output hashes plus prediction cutoff metadata. Generated artifacts are under ignored `data/exports/`; keep a copy with any published research report.

`scikit-learn` is an optional research dependency, not part of the Flask runtime requirements. The T9.6-specific tests skip when it is absent; install `requirements-research.txt` to run the complete research suite.

## Fixed protocol

- Models: `RandomForestClassifier`/`RandomForestRegressor` (64 trees, depth 5, leaf 20) and `HistGradientBoostingClassifier`/`HistGradientBoostingRegressor` (64 iterations, 7 leaves, leaf 30, L2 10). Regressors fit `log1p(daily rain mm)` and transform back to nonnegative mm. The [scikit-learn API](https://scikit-learn.org/stable/api/sklearn.ensemble.html) supplies both estimator families. All random seeds, versions, feature names and hyperparameters are in the manifest.
- Inputs: five complete Karuvottam source-window weather aggregates, season, target-day horizon, and cyclic target month. Target-day weather, event tracks, DMI/ONI, and target outcomes are **not** model inputs. Every target day in a source window shares the same source-weather aggregates.
- Outer evaluation: 2020–2024 expanding origin, two windows per year. For each source window, fit only prior season years whose target dates are strictly before that source-window start. Feature eligibility, model fitting and calibration are redone for each cutoff. No outer evaluation outcome is passed to fitting.
- Probability calibration: sigmoid fit on raw probability logits from the latest two prior season years. Each calibration window's raw predictions come from a model trained only on earlier cutoff-eligible rows. This is prior out-of-fold calibration, not calibration on the evaluated year. Raw and calibrated Brier scores and 10-bin reliability are saved.
- Comparison: same 1,600 daily identities per model as T6.4 seasonal climatology, across ten source-window blocks. Paired Brier and rain-MAE deltas use 1,000 seeded source-window block bootstrap resamples; negative means lower error. A candidate needs complete matched coverage and upper 95% limits below zero for **both** errors before incremental value is supported. These intervals are exploratory because only ten windows exist and two candidates were examined.

## Current 2015–2024 run

| Approach | Brier ↓ | ECE ↓ | Rain MAE mm ↓ | Rain RMSE mm ↓ | ROC-AUC ↑ |
|---|---:|---:|---:|---:|---:|
| Seasonal climatology | 0.212113 | 0.074601 | 3.219839 | 7.027875 | 0.703024 |
| Random forest, calibrated | 0.209148 | 0.042577 | 3.060802 | 7.370026 | 0.694824 |
| Histogram gradient boosting, calibrated | 0.212712 | 0.062926 | 3.041798 | 7.368559 | 0.687299 |

Random forest's paired Brier delta was **−0.002965** (95% block interval **−0.009468 to +0.002712**) and rain-MAE delta **−0.159037 mm** (**−0.410432 to +0.048526**). Histogram gradient boosting's Brier delta was **+0.000599** (**−0.007195 to +0.007936**) and MAE delta **−0.178041 mm** (**−0.408459 to +0.017571**). Both candidates have full matched coverage, but every interval includes zero. The random forest passes a *candidate diagnostic* for pooled Brier/ECE/reliability-bin coverage; that is not the T4.4 operational probability gate and does not demonstrate incremental value. The current decision remains **withheld**.

## Limits

The historical source inputs are retrospective ERA5 reanalysis. Their values may not have been available at the original forecast issuance time, even though target outcomes were embargoed correctly. This evaluation therefore tests an as-of **outcome split**, not a verified live historical data-availability replay. Source-window aggregates are repeated across many daily rows, leaving only ten independent evaluation windows. No event or climate features were included, so this does not claim an event-aware model. New models must not be integrated into public predictions without a separate operational-source availability audit, a stronger external/rolling validation, and the existing probability-publication gate.
