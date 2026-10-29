# T6.2 — அடிப்படை மாதிரி ஒப்பீடு

**Comparison contract:** `baseline-comparison-1.0`

## நோக்கம்

T6.2, T6.1 evaluation dataset-ன் ஒரே holdout rows-க்கு மூன்று முறைகளின் preliminary
predictions-ஐ உருவாக்குகிறது. இது performance முடிவை அறிவிப்பதில்லை; precision/recall,
Brier மற்றும் rainfall-error மதிப்பீடுகள் T6.3 report-ல் உள்ளன. Rolling temporal
uncertainty மற்றும் validation T6.4-ல் செய்யப்பட வேண்டும்.

## மூன்று அணுகுமுறைகள்

### 1. Seasonal climatology

**Version:** `seasonal-climatology-1.0`

Training period-ல் அதே source season மற்றும் target Gregorian month கொண்ட rows-ன்:

- mean daily precipitation;
- wet-day frequency (`rainfall >= configured threshold`)

பயன்படுத்தப்படுகின்றன. அந்த month-க்கு training rows இல்லாவிட்டால் மட்டும் அதே season-ன்
மொத்த climatology fallback ஆகும். இதில் Karuvottam source-window weather features இல்லை.

### 2. Karuvottam-only

**Version:** `karuvottam-knn-1.0`

அதே season மற்றும் அதே forecast day number கொண்ட prior training years-ல் source-window
features மிகவும் அருகிலுள்ள `k` rows தேர்வு செய்யப்படுகின்றன:

- source-window total precipitation;
- mean temperature;
- mean relative humidity;
- mean cloud cover;
- mean wind speed.

Features training-period standard deviation மூலம் scale செய்யப்படுகின்றன. இயல்புநிலை
`k=3`. Target month அல்லது current/future observed rainfall distance-ல் பயன்படுத்தப்படாது.

### 3. Combined

**Version:** `combined-knn-1.0`

அதே season-ன் prior training rows மீது source-window features உடன்:

- circular target-month distance;
- normalized forecast-horizon distance

சேர்க்கப்பட்ட nearest-neighbour model. இயல்புநிலை `k=25`. இது Karuvottam inputs
seasonal timing-க்கு மேலாக ஏதேனும் signal சேர்க்கிறதா என்பதை அடுத்த பணிகளில் அளவிடுவதற்கான
எளிய, deterministic comparison model மட்டுமே; optimized ML claim அல்ல.

## பொதுவான output contract

`baseline_predictions.csv`-ல் ஒவ்வொரு evaluation identity-க்கும் மூன்று rows உள்ளன.
அனைத்து approaches-க்கும் ஒரே:

- season type/year;
- source-window key;
- target day number/date;
- training/evaluation period;
- wet-day threshold;
- source/target quality flags;
- observed outcome fields

பயன்படுகின்றன. ஒவ்வொரு model row-லும் predicted rain amount, empirical wet frequency,
status, unavailable reason, training candidate count மற்றும் selected-neighbour count உள்ளன.

`baseline_manifest.json` source dataset key/hash, split, model versions/descriptions,
guardrails, per-approach counts மற்றும் output SHA-256-ஐ பதிவு செய்கிறது.

## Leakage guardrails

- `training_end_year < evaluation_start_year` கட்டாயம்.
- Feature scaling training rows-ல் மட்டுமே செய்யப்படுகிறது.
- Complete target outcomes மட்டுமே training candidates ஆகும்.
- Holdout observed rainfall output-ல் பின்னர் scoring-க்காக மட்டும் copy செய்யப்படுகிறது;
  prediction functions அதை வாசிப்பதில்லை.
- Missing source features இருந்தால் Karuvottam/combined output `unavailable`; கற்பனை மதிப்பு இல்லை.
- மூன்று approaches-ம் ஒரே evaluation row identities-க்கு உருவாக்கப்படுகின்றன.

Empirical wet frequency இன்னும் calibrated/public forecast probability அல்ல.

## இயக்குவது

```bash
python -m karuvottam.baseline_comparison \
  --dataset data/exports/evaluation-2015-2024/evaluation_dataset.csv \
  --manifest data/exports/evaluation-2015-2024/manifest.json \
  --output data/exports/baseline-comparison-2015-2024 \
  --training-start-year 2015 \
  --training-end-year 2021 \
  --evaluation-start-year 2022 \
  --evaluation-end-year 2024
```

Optional controls:

- `--wet-day-threshold-mm` — இயல்புநிலை `0.1` mm;
- `--karuvottam-neighbors` — இயல்புநிலை `3`;
- `--combined-neighbors` — இயல்புநிலை `25`.

## உள்ளூர் reference run

2026-10-16 அன்று T6.1 reference dataset மீது:

- training season years: `2015–2021`;
- evaluation season years: `2022–2024`;
- common evaluation rows: `960`;
- predictions per approach: `960`;
- total predictions: `2,880`;
- unavailable predictions: `0`;
- comparison key: `baseline-comparison-1.0:d4ab2063419649d8`;
- predictions SHA-256: `3f067cd6c5886c33dab40e5c2faf124fd194259f6379f50393de21cd8cd51f28`.

இந்த எண்ணிக்கைகள் coverage/reproducibility நிலை மட்டும். Fixed-holdout முடிவுகள்
[EVALUATION_METRICS.md](EVALUATION_METRICS.md)-இல் உள்ளன; உறுதியான approach முடிவு
T6.4 time-series validation முடியும் வரை கூறப்படக்கூடாது.
