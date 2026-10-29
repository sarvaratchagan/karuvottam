# T6.5 — ஆய்வுக் கண்டறிதல்கள் மற்றும் அறிவியல் வரம்புகள்

**Findings contract:** `research-findings-1.0`

## ஆய்வுக் கேள்வி

இந்த project-ல் பயன்படுத்திய இடம், ERA5 வரலாற்றுத் தரவு, 2015–2024 காலம் மற்றும்
deterministic models அடிப்படையில், Karuvottam source-window features வழக்கமான seasonal
climatology baseline-க்கு மேலாக predictive value சேர்க்கிறதா?

## Evidence inputs

T6.5 எந்த prediction-ஐயும் புதிதாக உருவாக்காது. இது:

- T6.3 fixed-holdout `evaluation_metrics.csv`;
- T6.4 `rolling_predictions.csv` மற்றும் `rolling_metrics.csv`;
- அவற்றின் manifest keys மற்றும் SHA-256 values

ஆகியவற்றைச் சரிபார்த்த பிறகே summary உருவாக்குகிறது. மூன்று approaches-க்கும் ஒரே
season/year/day identity, source window, target date மற்றும் observed outcome இருக்க வேண்டும்.

## முன் வரையறுக்கப்பட்ட முடிவு விதி

Seasonal climatology baseline. `karuvottam_only` மற்றும் `combined` candidates.

ஒவ்வொரு candidate-க்கும் ஒரே rolling out-of-fold row மீது:

- Brier loss delta;
- absolute-error/MAE delta;
- squared-error அடிப்படையிலான RMSE delta

கணக்கிடப்படுகிறது. Delta = candidate minus seasonal baseline; negative என்பது improvement.

ஒரே source window-ன் 140/180 daily rows ஒன்றுக்கொன்று சார்ந்திருக்கக்கூடும். எனவே individual
day bootstrap அல்லாமல் `source_window_key` block bootstrap பயன்படுத்தப்படுகிறது. Reference
run-ல் 10 blocks, 2,000 iterations, fixed seed மற்றும் 95% percentile intervals உள்ளன.

**Incremental value supported** என்று கூற வேண்டுமெனில் Brier delta மற்றும் MAE delta
95% CI-களின் மேல் எல்லைகள் இரண்டும் 0-க்கு கீழ் இருக்க வேண்டும். ஒரு favourable F1 அல்லது
ஒரு fixed split மட்டும் இந்த rule-ஐ மாற்றாது.

## Reference முடிவுகள்

### Rolling-origin pooled metrics

| Approach | F1 | ROC-AUC | Brier | MAE mm | RMSE mm |
|---|---:|---:|---:|---:|---:|
| Seasonal climatology | 0.733226 | 0.703024 | 0.212113 | 3.219839 | 7.027875 |
| Karuvottam-only | 0.684043 | 0.646508 | 0.275347 | 3.755375 | 7.844530 |
| Combined | 0.708444 | 0.661174 | 0.245534 | 3.639255 | 7.356623 |

### Seasonal baseline-க்கு எதிரான paired 95% CI

| Candidate | Brier delta | MAE delta mm | RMSE delta mm | F1 delta | முடிவு |
|---|---:|---:|---:|---:|---|
| Karuvottam-only | 0.063234 [0.044215, 0.081066] | 0.535536 [0.327810, 0.767997] | 0.816655 [0.595816, 1.053091] | -0.049183 | ஆதரிக்கப்படவில்லை |
| Combined | 0.033421 [0.021627, 0.045750] | 0.419416 [0.138232, 0.725105] | 0.328748 [0.184326, 0.482923] | -0.024782 | ஆதரிக்கப்படவில்லை |

அனைத்து paired loss deltas மற்றும் அவற்றின் CI-களும் 0-க்கு மேல் உள்ளன. இந்த evaluation-ல்
seasonal climatology baseline மொத்தத்தில் சிறந்தது. Karuvottam-only அல்லது combined model
கூடுதல் predictive value தருகிறது என்ற ஆதாரம் கிடைக்கவில்லை.

T6.3 fixed split-ல் combined F1 மட்டும் உயர்ந்திருந்தது. ஆனால் Brier/MAE/RMSE seasonal
baseline-ஐ முந்தவில்லை; rolling folds-லும் அந்த F1 advantage தொடரவில்லை. எனவே favourable
metric மட்டும் தேர்ந்தெடுத்து accuracy claim செய்யப்படவில்லை.

## சரியான விளக்கம்

இந்த முடிவு:

- தற்போதைய இலக்கு இடம்;
- ERA5 grid reanalysis;
- 2015–2024 காலம்;
- தற்போதைய calendar/window rules;
- இங்கு வரையறுக்கப்பட்ட simple baseline/KNN models

ஆகியவற்றுக்கு மட்டும் பொருந்தும். இது கருவோட்ட மரபு எல்லா இடங்களிலும், எல்லா காலங்களிலும்
பயனற்றது என்ற பொதுவான நிரூபணம் அல்ல. வேறு formulation, சிறந்த local observations அல்லது
வேறு இடம்/காலம் வேறு முடிவைத் தரலாம்; அவை இதே leakage-safe protocol-ல் சோதிக்கப்பட வேண்டும்.

## Publication நிலை

- Incremental value supported: **இல்லை**.
- Calibrated probability publication: **disabled**.
- 180/140 நாள் UI-ல் probability, amount மற்றும் rain category: தொடர்ந்து மறைக்கப்படும்.
- Experimental research score: probability என விளக்கக்கூடாது.

## Output மற்றும் இயக்குவது

```bash
python -m karuvottam.research_findings \
  --rolling data/exports/rolling-validation-2015-2024 \
  --fixed data/exports/evaluation-metrics-2015-2024 \
  --output data/exports/research-findings-2015-2024
```

Outputs:

- `paired_comparisons.csv` — deltas, CI மற்றும் decision;
- `research_findings.json` — machine-readable evidence/conclusion;
- `research_findings.md` — தமிழ்-first research summary;
- `findings_manifest.json` — input/output hashes, bootstrap spec மற்றும் publication state.

Reference findings key: `research-findings-1.0:e40defedc55497dd`.

## அடுத்த ஆய்வு நடவடிக்கைகள்

- உள்ளூர் rain-gauge data-வில் மீள்மதிப்பீடு;
- பல இடங்கள் மற்றும் நீண்ட independent காலத்தில் external validation;
- புதிய model உருவாக்குவதற்கு முன் primary metrics/thresholds preregistration;
- seasonal baseline-ஐ paired leakage-safe evaluation-ல் தெளிவாக முந்திய பிறகே publication
  gate-ஐ மீளாய்வு செய்தல்.
