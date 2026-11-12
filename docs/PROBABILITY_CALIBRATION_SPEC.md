# Evidence-Gated Probability Calibration

**Calibration model version:** `score-bin-calibration-1.0`

**Current publication state:** Withheld after real multi-year historical evaluation failed the gate

## Purpose

This framework tests whether the experimental 0–100 Karuvottam research index can be converted into a defensible rain probability. It does not assume that a high index is already a probability. User-facing percentages remain hidden unless a held-out, time-ordered evaluation passes every evidence requirement below.

## Required historical sample

Each `CalibrationSample` contains:

- stable source-window key and its end timestamp;
- future target timestamp, which must be after the source window ends;
- research score from `research-index-1.0`;
- observed binary rain outcome for the target.

All timestamps must be timezone-aware. A source-window key may have only one end timestamp. These checks prevent future observations or inconsistent window identities from leaking into training.

## Time-ordered validation

1. Group samples by source window.
2. Order complete groups by source-window end time.
3. By default, use the earliest 70% of windows for training and the latest 30% for evaluation. The historical run uses an explicit 2022–2024 holdout boundary.
4. Never divide one source window between training and evaluation.
5. Require all training target outcomes to end before the first evaluation source window begins.
6. Reject duplicate source-window/target identities.
7. Fit calibration bins only from training samples.
8. Calculate every reported metric only on the later held-out samples.

Input ordering does not affect the split or results.

## Calibration model

Research scores use fixed bins: `[0,20)`, `[20,40)`, `[40,60)`, `[60,80)`, and `[80,100]`. Each populated training bin receives a Laplace-smoothed event rate `(rain events + 1) / (samples + 2)`. An empty score bin falls back to the training climatological rain rate.

This transparent bin model is a calibration baseline, not a claim that it is the final or best model. Model changes require a new version and a fresh time-ordered evaluation.

## Evaluation metrics

- **Brier score:** mean squared difference between held-out calibrated probability and observed 0/1 outcome; lower is better.
- **Climatology Brier baseline:** the same held-out outcomes predicted using only the training rain frequency.
- **Reliability bins:** `[0,.2)`, `[.2,.4)`, `[.4,.6)`, `[.6,.8)`, `[.8,1]`, reporting count, mean prediction, and observed frequency.
- **Expected calibration error (ECE):** reliability-bin absolute errors weighted by held-out sample count.

## Default publication gate

Probability output is enabled only when all conditions pass:

- at least 4 earlier training windows and 2 later evaluation windows;
- at least 140 training samples and 60 held-out samples;
- both rain and no-rain outcomes occur in training and evaluation;
- at least two populated held-out reliability bins;
- every populated reliability bin has at least 10 samples;
- held-out Brier score is strictly better than training-climatology baseline;
- held-out ECE is at most `0.15`.

Failure produces `status=withheld`, explicit reason codes, and `predict_probability(...) = None`. The metrics may still be retained for research diagnostics, but percentages must not be shown as forecasts.

## Real-data result

Run `python -m karuvottam.calibration_validation` after building the T6.1 dataset and T6.4 validation artifacts and importing the matching ERA5 hourly observations. The command verifies dataset and source-window provenance, computes `research-index-1.0` scores from those observations, excludes training windows whose target outcomes cross the holdout start, then writes a checksum-verified report to `data/exports/score-calibration-2015-2024/`. The export is generated locally and ignored by Git.

For the configured Madurai-area location, 13 earlier windows yielded 2,100 training samples; six 2022–2024 windows yielded 960 held-out samples. One crossing 2021 Margazhi window was excluded. The held-out Brier score was **0.26152**, worse than the training-climatology baseline **0.24634**. ECE was **0.138479**, but only one reliability bin was populated. The gate therefore returned `withheld` for `no_brier_improvement_over_climatology` and `insufficient_populated_reliability_bins`.

The task of evaluating calibration is complete. This result does not support publishing rain probabilities. The T6.5 paired findings also do not establish incremental value for the Karuvottam candidates. Automated synthetic tests verify the calculations and lock but are not the evidence behind this decision.
