# பல ஆண்டு மதிப்பீட்டுத் தரவுத்தொகுப்பு

**Dataset contract:** `evaluation-dataset-1.0`  
**Measurement contract:** `hour-ending-precipitation-1.0`

## நோக்கம்

T6.1 pipeline ஒவ்வொரு வரலாற்று ஆடி/மார்கழி கருவோட்டச் சாளரத்தையும் அதன்
180/140 எதிர்கால நாட்களில் பதிவான உண்மையான ERA5 மழையுடன் இணைக்கிறது. இந்த output
T6.2 baseline comparison மற்றும் T6.3 evaluation-க்கான input; இது தானாகவே
கருவோட்டம் மழையை கணிக்கிறது என்பதற்கான ஆதாரம் அல்ல.

## வெளியீட்டுக் கோப்புகள்

ஒவ்வொரு build directory-லும் மூன்று UTF-8 files உருவாகின்றன:

- `evaluation_dataset.csv` — source-window features மற்றும் ஒரு target local day-ன் observed rainfall கொண்ட ஒரு row.
- `data_gaps.csv` — source window / target day-ல் தொடர்ச்சியாக விடுபட்ட hourly ranges.
- `manifest.json` — location, provider, year range, rule/model/measurement versions, transformations, quality counts, SHA-256 checksums, lunar-event provenance மற்றும் raw-payload references.

`evaluation_dataset.csv`-இல் ஒவ்வொரு season year-க்கும்:

- ஆடி source window-க்கு 180 target rows;
- மார்கழி source window-க்கு 140 target rows;
- source-window key, exact start/end, trigger phase/time மற்றும் mapping boundary;
- source-window precipitation total மற்றும் temperature/humidity/cloud/wind means;
- source மற்றும் target expected/observed/missing/interpolated/measurement-issue hours;
- target daily observed precipitation, coverage மற்றும் quality flag;
- calendar, timeline, dataset மற்றும் measurement contract versions.

## நேரம் மற்றும் மழை interval விதி

Open-Meteo ERA5 request UTC hourly labels-ஐ வழங்குகிறது. ஒவ்வொரு precipitation value-மும்
அந்த label-ல் முடியும் முந்தைய 60 நிமிட accumulation ஆக எடுத்துக்கொள்ளப்படுகிறது.

- source bounds மற்றும் target-day bounds `(start, end]` hour-end label assignment பயன்படுத்துகின்றன;
- target day `Asia/Kolkata` midnight முதல் அடுத்த midnight வரை;
- local boundary UTC hour-ஐ நடுவில் வெட்டினால் fractional rainfall உருவாக்கப்படாது;
  end-label assignment காரணமாக அதிகபட்சம் ஒரு boundary hour இடமாற்றம் ஏற்படலாம்;
- 60-minute metadata பொருந்தாத precipitation total-ல் சேர்க்கப்படாது; measurement issue ஆகக் குறிக்கப்படும்;
- விடுபட்ட மணிகள் zero ஆக நிரப்பப்படாது;
- interpolated records தனியாக எண்ணப்பட்டு row quality `warning` ஆகும்.

ERA5 சுமார் 0.25° grid reanalysis; இது உள்ளூர் rain gauge அல்ல. Station/gauge data பின்னர்
சேர்க்கப்பட்டால் வேறு source மற்றும் measurement contract-ஆக வைத்தே ஒப்பிட வேண்டும்.

## இயக்குவது

முதலில் database migration:

```bash
python -m karuvottam.database migrate
```

API request இல்லாமல் தேவையான weather date range-ஐ பார்க்க:

```bash
python -m karuvottam.evaluation_dataset plan \
  --start-year 2015 --end-year 2024
```

ERA5 hourly data-வை bounded, idempotent chunks-ஆக சேகரிக்க:

```bash
python -m karuvottam.evaluation_dataset collect \
  --start-year 2015 --end-year 2024 --chunk-days 366
```

ஏற்கெனவே database-ல் உள்ள data-விலிருந்து மட்டும் artifacts உருவாக்க:

```bash
python -m karuvottam.evaluation_dataset build \
  --start-year 2015 --end-year 2024 \
  --output data/exports/evaluation-2015-2024
```

collect + build ஒன்றாக:

```bash
python -m karuvottam.evaluation_dataset assemble \
  --start-year 2015 --end-year 2024 \
  --output data/exports/evaluation-2015-2024
```

கட்டளை configured location இல்லாவிட்டால் அதை உருவாக்குகிறது. Weather ingestion
content-addressed raw JSON மற்றும் metadata-வை `KARUVOTTAM_WEATHER_RAW_DATA_DIR`-ல்
வைக்கிறது; மீண்டும் இயக்கும்போது database duplicates சேராது.

## Reproducibility checks

- dataset identity என்பது location coordinates/timezone, provider source, year range மற்றும் dataset version-ன் stable SHA-256 key;
- CSV column order மற்றும் row order நிலையானவை;
- CSV மற்றும் gap report hashes manifest-ல் பதிவு செய்யப்படுகின்றன;
- build timestamp manifest-ல் மட்டும் உள்ளது; அது dataset CSV hash-ஐ மாற்றாது;
- exact raw provider payload references manifest-ல் பட்டியலிடப்படுகின்றன;
- same database snapshot + same versions + same year range ஒரே CSV SHA-256-ஐ உருவாக்க வேண்டும்.

## Quality பயன்பாடு

`complete` row மட்டுமே முழு 24 hourly outcome coverage கொண்டது. `warning` row-ல் gaps,
interpolation, missing precipitation அல்லது incompatible interval metadata இருக்கலாம்.
`no_data` என்பது ஒரு hourly record கூட இல்லாத நாள். T6.2/T6.3 training/evaluation code
இந்த flags-ஐ explicit filter/stratum ஆக பயன்படுத்த வேண்டும்; warning/no-data rows-ஐ
அமைதியாக முழுமையான observations போல நடத்தக்கூடாது.

## உள்ளூர் reference build

2026-10-16 அன்று 2015–2024 season years-க்கு `assemble` இயக்கப்பட்டது:

- தேவையான UTC weather date range: `2015-07-01` முதல் `2025-12-01` வரை;
- ingested hourly records: `91,368`;
- rejected hourly records: `0`;
- linked daily rows: `3,200` (`10 × (180 + 140)`);
- complete rows: `3,200`; warning/no-data rows: `0`;
- content-addressed raw payloads: `11`;
- `evaluation_dataset.csv` SHA-256: `221dd9f29b4deb6c43163eee02f1c3e19829adbdeed2d4b0d4d4702038dd07eb`.

Generated runtime data `data/`-ல் உள்ளது மற்றும் `.gitignore` மூலம் source control-ல்
சேர்க்கப்படாது. பகிரும்போது மூன்று artifact files மற்றும் raw payload archive-ஐ ஒன்றாக
versioned research release-ஆகச் சேமிக்க வேண்டும்.
