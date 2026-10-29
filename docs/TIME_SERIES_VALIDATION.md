# T6.4 — Rolling-origin காலவரிசைச் சரிபார்ப்பு

**Validation contract:** `rolling-origin-validation-1.0`

## நோக்கம்

ஒரே fixed train/test split தற்செயலான ஆண்டு விளைவுகளால் தவறான நம்பிக்கையைத் தரலாம்.
T6.4 ஒவ்வொரு அடுத்த evaluation ஆண்டுக்கும் அதற்கு முந்தைய தரவை மட்டும் கொண்டு models-ஐ
மீண்டும் fit செய்து expanding rolling-origin validation செய்கிறது. Holdout outcome forecast
உருவாக்கத்தில் நுழையாது.

## இரண்டு காலவரிசைத் தடைகள்

### 1. Season-year fold

Evaluation year `Y` என்றால் nominal training years:

```text
training_start_year ... Y-1
```

`Y` அல்லது அதற்குப் பிந்தைய season year training-ல் நுழைய முடியாது.

### 2. Source-window as-of cutoff

Season-year check மட்டும் போதாது. முந்தைய Margazhi season-ன் சில 140 நாள் outcomes,
அடுத்த ஆண்டு Aadi source window தொடங்கும்போது இன்னும் நிகழாதிருக்கலாம். எனவே ஒவ்வொரு
evaluation source window-க்கும்:

```text
training target_date_local < source_window_start_local date
```

என்ற strict cutoff பயன்படுத்தப்படுகிறது. Cutoff-க்கு பிறகு உள்ள nominal-training outcomes
விலக்கப்படுகின்றன. Feature scaling, seasonal candidate selection மற்றும் nearest-neighbour
selection அனைத்தும் cutoff-க்கு முன் கிடைத்த rows மீது fold-க்குள் மீண்டும் செய்யப்படுகின்றன.

## Versioning மற்றும் reproducibility

Validation key பின்வருவனவற்றின் stable hash:

- dataset key மற்றும் CSV SHA-256;
- calendar rule, timeline model மற்றும் measurement-contract versions;
- seasonal, Karuvottam-only மற்றும் combined model versions;
- T6.3 metrics version மற்றும் T6.4 validation version;
- training/evaluation years, wet threshold, neighbour counts மற்றும் metric settings.

Build timestamp manifest-ல் மட்டும் உள்ளது. அதே input மற்றும் settings பயன்படுத்தும்போது
CSV/Markdown outputs byte-for-byte ஒரேபடி உருவாகும்.

## Output files

- `rolling_predictions.csv` — fold, cutoff, model version மற்றும் outcome provenance உடன்
  ஒவ்வொரு out-of-fold prediction;
- `rolling_folds.csv` — ஒவ்வொரு evaluation ஆடி/மார்கழி source window-ன் cutoff,
  eligible/latest training outcome, விலக்கப்பட்ட future outcomes மற்றும் leakage status;
- `rolling_metrics.csv` — ஒவ்வொரு fold மற்றும் pooled overall/season/month/horizon metrics;
- `rolling_reliability.csv` — fold மற்றும் pooled reliability bins;
- `rolling_summary.md` — pooled metrics மற்றும் fold ranges;
- `validation_manifest.json` — versions, guardrails, publication state, counts மற்றும்
  output SHA-256 values.

## இயக்குவது

```bash
python -m karuvottam.time_series_validation \
  --dataset data/exports/evaluation-2015-2024/evaluation_dataset.csv \
  --manifest data/exports/evaluation-2015-2024/manifest.json \
  --output data/exports/rolling-validation-2015-2024 \
  --training-start-year 2015 \
  --first-evaluation-year 2020 \
  --last-evaluation-year 2024
```

Wet-day cutoff, neighbour counts, classification cutoff, reliability-bin count மற்றும்
horizon-band நாட்களை CLI options மூலம் மாற்றலாம். எந்த setting மாற்றமும் validation key-ஐ
மாற்றும்.

## 2015–2024 reference run

- initial training season years: `2015–2019`;
- expanding evaluation folds: `2020`, `2021`, `2022`, `2023`, `2024`;
- source-window as-of leakage checks: `10`, அனைத்தும் passed;
- pooled evaluation identities: approach ஒன்றுக்கு `1,600`;
- மொத்த predictions: `4,800`, அனைத்தும் evaluated;
- metric rows: `378`;
- reliability rows: `3,780`;
- validation key: `rolling-origin-validation-1.0:87ae985574498bd0`.

| Approach | F1 | ROC-AUC | Brier | MAE mm | RMSE mm | Fold F1 range | Fold Brier range |
|---|---:|---:|---:|---:|---:|---:|---:|
| Seasonal climatology | 0.733226 | 0.703024 | 0.212113 | 3.219839 | 7.027875 | 0.688000–0.783505 | 0.204157–0.229810 |
| Karuvottam-only | 0.684043 | 0.646508 | 0.275347 | 3.755375 | 7.844530 | 0.639175–0.729223 | 0.244792–0.303125 |
| Combined | 0.708444 | 0.661174 | 0.245534 | 3.639255 | 7.356623 | 0.661538–0.754177 | 0.216180–0.270310 |

இந்த rolling run-ல் seasonal climatology pooled F1, ROC-AUC, Brier, MAE மற்றும் RMSE
அனைத்திலும் மற்ற இரண்டு approaches-ஐ முந்தியது. Karuvottam-only அல்லது combined model
கூடுதல் predictive value தருகிறது என்ற ஆதாரம் இந்த dataset/place/period-ல் கிடைக்கவில்லை.

## வரம்புகள் மற்றும் publication state

- ERA5 grid reanalysis உள்ளூர் rain gauge அல்ல.
- ஐந்து annual folds மட்டும் உள்ளன; uncertainty இன்னும் பரந்ததாக இருக்கலாம்.
- Models எளிய deterministic baselines; exhaustive hyperparameter search செய்யப்படவில்லை.
- இந்த முடிவு Karuvottam மரபின் பொதுவான செல்லுபடியாக்கல்/மறுப்பு அல்ல; குறிப்பிட்ட
  dataset, இடம், காலம் மற்றும் models பற்றிய முடிவு மட்டும்.
- Rolling validation probability calibration gate-க்கு மாற்றாகாது. Empirical probability
  UI publication தொடர்ந்து disabled.
- T6.5 இந்த முடிவுகள் மற்றும் uncertainty-ஐ ஆதாரமற்ற accuracy claim இல்லாமல் சுருக்க வேண்டும்.
