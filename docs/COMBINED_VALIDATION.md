# T8.8 — Combined model validation

`python -m karuvottam.combined_validation` reads the checksum-verified T6.5 paired rolling comparison, T8.5 event–rainfall holdout, and T4.4 real-score calibration. It writes `combined_validation.json` and a checksum manifest under `data/exports/combined-validation-2015-2024/`. These generated artifacts are ignored by Git. The `/events` page shows the decision only when its report and linked evidence match the configured target location and historical dataset.

## Current decision: withheld

The 2020–2024 rolling comparison used 1,600 matched daily rows per approach at the same location. The experimental `combined-knn-1.0` candidate had a paired Brier difference of **+0.033421** and rain MAE difference of **+0.419416 mm** versus seasonal climatology; positive values mean worse error. Their 95% confidence interval upper limits were **+0.04575** and **+0.725105 mm**. This does not demonstrate incremental value.

The separate T8.5 event-distance model had **3.22 mm/24h** holdout MAE versus **3.17 mm/24h** for its baseline. The real-score probability calibration had **0.26152** Brier versus **0.24634** climatology and failed its reliability-bin gate. These are distinct research candidates; the score calibration is not a calibration of `combined-knn-1.0`.

The T6 combined candidate uses Karuvottam source-window weather features. It has **no** event tracks, IOD, or ENSO features, so the comparison cannot validate a new event/climate-aware forecast. The application publishes no combined rain amount or probability. A future candidate needs versioned inputs, matched leakage-safe historical evaluation, baseline improvement, and its own held-out probability calibration before publication.

## Reproduce

Build the upstream artifacts according to [T6.1](EVALUATION_DATASET.md), [T6.4](TIME_SERIES_VALIDATION.md), [T6.5](RESEARCH_FINDINGS.md), and [T8.5](EVENT_RAINFALL.md), then run:

```sh
python -m karuvottam.calibration_validation
python -m karuvottam.combined_validation
```

The local dashboard reads `KARUVOTTAM_SCORE_CALIBRATION_DIR` and `KARUVOTTAM_COMBINED_VALIDATION_DIR` when set; otherwise it uses the export paths above. Missing, mismatched, or corrupted artifacts show an unavailable decision. A deployment must provide the generated evidence separately.
