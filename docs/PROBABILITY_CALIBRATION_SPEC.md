# Evidence-Gated Probability Calibration

**Calibration model version:** `score-bin-calibration-1.0`

**Current publication state:** Withheld until real multi-year historical validation satisfies the gate

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
3. Use the earliest 70% of windows for training and the latest 30% for evaluation.
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

## Current limitation

Automated tests use synthetic separable data only to verify calculations, time separation, determinism, boundary behavior, and the publication lock. Synthetic test success is **not calibration evidence**. T6.1 multi-year samples, T6.3 fixed-holdout metrics, T6.4 rolling validation, and the T6.5 paired findings summary now exist. These results do not establish Karuvottam incremental value, and the score-calibration publication gate has not passed; therefore the current hidden-probability state must not change.
