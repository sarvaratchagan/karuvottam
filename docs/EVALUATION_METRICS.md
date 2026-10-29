# T6.3 — மதிப்பீட்டு அளவீடுகள் மற்றும் அறிக்கைகள்

**Evaluation contract:** `evaluation-metrics-1.0`

## நோக்கம்

T6.2 உருவாக்கிய seasonal climatology, Karuvottam-only மற்றும் combined predictions-ஐ
ஒரே fixed temporal holdout-ல் ஒரே அளவீடுகளால் மதிப்பிடுவது இந்தப் பணியின் நோக்கம்.
இந்த முடிவுகள் research evidence மட்டுமே; application UI-ல் calibrated probability
வெளியிட அனுமதி அல்ல.

## Input guardrails

`BaselinePredictionReader`:

- `baseline_predictions.csv` SHA-256 manifest-உடன் பொருந்துகிறதா எனச் சரிபார்க்கிறது;
- comparison key/version ஒவ்வொரு row-லும் ஒரேதா என உறுதிசெய்கிறது;
- மூன்று approaches-க்கும் ஒரே season/year/day identities உள்ளதா எனச் சரிபார்க்கிறது;
- அந்த identities-க்கு dataset, source window, target date, wet threshold, quality மற்றும்
  observed outcome அனைத்தும் ஒரேதா என உறுதிசெய்கிறது;
- duplicate, invalid probability, negative rainfall மற்றும் inconsistent wet-day label-ஐ
  நிராகரிக்கிறது.

`status=available`, complete target quality மற்றும் முழு prediction/outcome fields உள்ள rows
மட்டுமே score செய்யப்படுகின்றன. மற்ற rows coverage count-ல் இருக்கும்; metric-ல் கற்பனை
மதிப்பு நிரப்பப்படாது.

## அளவீடுகள்

### மழை நாள் வகைப்பாடு

Observed wet day என்பது T6.2-ல் பதிவு செய்யப்பட்ட threshold-க்கு சமம் அல்லது அதிகமான
தினசரி மழை. இயல்புநிலை predicted-wet cutoff empirical wet frequency `>= 50%`.

- precision, recall, F1;
- true/false positive மற்றும் true/false negative counts;
- tie-aware rank ROC-AUC. ஒரு group-ல் wet அல்லது dry class ஒன்றே இருந்தால் ROC-AUC blank.

### Preliminary probability quality

- Brier score, `0–1` scale;
- இயல்புநிலை 10 reliability bins;
- ஒவ்வொரு bin-லும் mean predicted frequency, observed wet frequency மற்றும் absolute gap;
- sample-weighted expected calibration error (ECE), `0–1` scale.

இவை empirical model frequencies; calibrated public forecast probabilities அல்ல.

### மழை அளவு

- MAE மற்றும் RMSE, millimetres;
- bias = mean predicted rainfall minus observed rainfall;
- Pearson correlation. Prediction அல்லது observation variance zero என்றால் blank.

### பிரிக்கப்பட்ட அறிக்கைகள்

ஒவ்வொரு approach-க்கும்:

- overall;
- source season (`aadi`, `margazhi`);
- target Gregorian month;
- 30 நாள் forecast-horizon bands (`001-030`, `031-060`, ...)

என metrics மற்றும் reliability தனித்தனியாக எழுதப்படுகின்றன.

## Output files

- `evaluation_metrics.csv` — classification, probability மற்றும் amount metrics;
- `evaluation_reliability.csv` — ஒவ்வொரு group-ன் reliability bins;
- `evaluation_summary.md` — overall comparison மற்றும் interpretation limits;
- `evaluation_manifest.json` — source comparison hash, metric settings, definitions,
  limitations, counts மற்றும் output SHA-256 values.

Build timestamp manifest-ல் மட்டும் இருக்கும். அதே input மற்றும் settings பயன்படுத்தினால்
மூன்று report files byte-for-byte ஒரேபடி உருவாகும்; evaluation key-யும் மாறாது.

## இயக்குவது

```bash
python -m karuvottam.evaluation_metrics \
  --predictions data/exports/baseline-comparison-2015-2024/baseline_predictions.csv \
  --manifest data/exports/baseline-comparison-2015-2024/baseline_manifest.json \
  --output data/exports/evaluation-metrics-2015-2024
```

Optional controls:

- `--classification-threshold-pct` — இயல்புநிலை `50`;
- `--reliability-bin-count` — இயல்புநிலை `10`, 100-ஐ முழுமையாகப் பகுக்க வேண்டும்;
- `--horizon-bin-days` — இயல்புநிலை `30`.

## 2015–2024 reference run

Training season years `2015–2021`; fixed evaluation season years `2022–2024`.
ஒவ்வொரு approach-க்கும் `960` rows, மொத்தம் `2,880` predictions அனைத்தும் score செய்யப்பட்டன.

| Approach | F1 | ROC-AUC | Brier | ECE | MAE mm | RMSE mm | Bias mm | Correlation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Seasonal climatology | 0.719635 | 0.702913 | 0.215086 | 0.076265 | 3.238575 | 7.201626 | -0.554361 | 0.277208 |
| Karuvottam-only | 0.705781 | 0.658173 | 0.262616 | 0.164236 | 3.688333 | 7.946096 | -0.432500 | 0.120135 |
| Combined | 0.750836 | 0.704362 | 0.218682 | 0.078292 | 3.559379 | 7.564755 | -0.431596 | 0.078334 |

- Combined approach recall/F1-ல் அதிகம்; ROC-AUC seasonal baseline-ஐ விட மிகச் சிறிய அளவு மட்டுமே அதிகம்.
- Seasonal climatology குறைந்த Brier, ECE, MAE, RMSE மற்றும் அதிக correlation கொண்டது.
- Karuvottam-only approach இந்த fixed holdout-ல் seasonal baseline-ஐ மீறவில்லை.
- எந்த approach-ம் எல்லா metric families-லும் முன்னிலை பெறவில்லை. Combined model Karuvottam
  கூடுதல் மதிப்பை நிரூபித்தது என்று இந்த ஒரே split-இலிருந்து கூற முடியாது.

Reference evaluation key:
`evaluation-metrics-1.0:ed0d8407e25d8d73`.

## வரம்புகள் மற்றும் அடுத்த பணி

- Target rainfall ERA5 reanalysis; உள்ளூர் rain-gauge அளவீடு அல்ல.
- Subgroup sample/class counts மாறுபடும்; சிறிய groups நிலையற்றதாக இருக்கலாம்.
- இது ஒரு fixed holdout மட்டும்; year-by-year rolling-origin uncertainty இல்லை.
- Hyperparameter sensitivity மற்றும் confidence intervals இன்னும் மதிப்பிடப்படவில்லை.
- T6.4 time-series validation மற்றும் versioning முடியும் வரை UI probability publication gate
  மூடப்பட்டே இருக்க வேண்டும்.
