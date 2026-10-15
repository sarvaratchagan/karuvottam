# தன்னியக்க துல்லிய மழை முன்னறிவிப்பு திட்டம் — MVP

## தற்போதைய MVP
- ஆண்டு தேர்வு
- ஆடி 18 நாள் → மார்கழி கருவோட்டம் முடிந்த மறுநாள் → 180 நாள் பொருத்தம்
- மார்கழி 11 நாள் (இரவு/பகல் தொடர்ச்சி) → அடுத்த ஆண்டு ஆடி கருவோட்டம் முடிந்த மறுநாள் → 140 நாள் பொருத்தம்
- 180/140 நாள் முன்னறிவிப்பு அட்டவணை UI
- தமிழ்-first இடைமுகம்

## முக்கிய வரம்பு
கருவோட்டத் தொடக்கங்கள் தேர்ந்தெடுக்கப்பட்ட சந்திர நிகழ்வின் துல்லிய உள்ளூர் நேரத்திலிருந்து நேரடியாக உருவாக்கப்படுகின்றன. வானிலை client மற்றும் ingestion உள்ளன; முகப்பிலுள்ள முன்னறிவிப்பு மதிப்புகள் இன்னும் விளக்க மதிப்புகள், அளவீடு செய்யப்பட்ட நிகழ்தகவுகள் அல்ல.

ஆடி 1 = சூன் 21. அதன்பின் முதலில் வரும் பௌர்ணமி அல்லது அமாவாசை நேரமே ஆடி தொடக்கம். மார்கழியில் அமாவாசை/பௌர்ணமி ஆண்டுதோறும் மாறி மாறி பயன்படுத்தப்படும்; இயல்புநிலை anchor `2026 = அமாவாசை`. மார்கழி கண்காணிப்பு 11 முழு நாட்கள்.

## இயக்குவது

### தேவைகள்

- Python 3.10 அல்லது அதற்கு மேல்
- macOS / Linux முனையம் அல்லது பொருத்தமான Windows கட்டளை முனையம்

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

பின்னர் http://127.0.0.1:5000 திறக்கவும்.

macOS-இல் AirPlay Receiver அல்லது வேறு பயன்பாடு port 5000-ஐ பயன்படுத்தினால்:

```bash
KARUVOTTAM_PORT=5050 python app.py
```

பின்னர் http://127.0.0.1:5050 திறக்கவும்.

`.env` கோப்பில் உள்ளூர் அமைப்புகளை மாற்றலாம். உண்மையான API விசை அல்லது ரகசியத்தை `.env.example` அல்லது Git-இல் சேர்க்க வேண்டாம்.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
python app.py
```

## தற்போதைய கோப்பு அமைப்பு

| கோப்பு / கோப்புறை | பயன்பாடு |
|---|---|
| `app.py` | Flask வழித்தடங்கள் மற்றும் தற்போதைய MVP தேதி/கணிப்பு மாதிரி |
| `config.py` | சூழல் மாறிகளிலிருந்து சரிபார்க்கப்பட்ட பயன்பாட்டு அமைப்புகள் |
| `.env.example` | ரகசியமற்ற அமைப்பு மாதிரி |
| `templates/index.html` | தமிழ் முகப்புப் பக்கம் மற்றும் ஆண்டு சுழற்சி |
| `templates/prediction.html` | 180/140 நாள் விளக்க அட்டவணை |
| `static/style.css` | பகிரப்பட்ட responsive வடிவமைப்பு |
| `requirements.txt` | Python சார்புகள் |
| `PROJECT_PLAN.md` | திட்ட விவரக்குறிப்பு மற்றும் சாலைவரைபடம் |
| `TASKS.md` | முன்னுரிமை மற்றும் சார்புகளுடன் செயலாக்க backlog |
| `karuvottam/database.py` | SQLite இணைப்பு மற்றும் versioned migration runner |
| `karuvottam/data_access.py` | transaction மற்றும் repository அடிப்படையிலான data-access layer |
| `karuvottam/weather_client.py` | retry, raw archive மற்றும் idempotent ERA5 ingestion |
| `karuvottam/weather_quality.py` | record மற்றும் window-level weather quality validation |
| `karuvottam/weather_csv.py` | preview-first UTF-8 weather CSV import மற்றும் export |
| `karuvottam/migrations/` | மாற்றக்கூடாத வரிசைப்படுத்தப்பட்ட schema migrations |
| `docs/DATABASE.md` | schema, timestamp மற்றும் migration நடைமுறை |

## தற்போதைய வழித்தடங்கள்

- `/` — ஆண்டு தேர்வு மற்றும் கருவோட்டச் சுழற்சி
- `/prediction?year=2026&mode=aadi` — ஆடி அடிப்படையிலான 180 நாள் காட்சி
- `/prediction?year=2026&mode=margazhi` — மார்கழி அடிப்படையிலான 140 நாள் காட்சி

உற்பத்தி இயக்கத்தில் Flask development server பயன்படுத்தப்படக்கூடாது. தற்போதைய உள்ளூர் இயக்கம் `debug=False` உடன் மட்டுமே தொடங்குகிறது.

## அமைப்புகள்

| சூழல் மாறி | இயல்புநிலை / பயன்பாடு |
|---|---|
| `KARUVOTTAM_LOCATION_NAME` | இலக்கு இடத்தின் காட்சிப் பெயர் |
| `KARUVOTTAM_LATITUDE` | `9.9040188` |
| `KARUVOTTAM_LONGITUDE` | `77.8860417` |
| `KARUVOTTAM_ELEVATION_M` | `0` — சரிபார்க்கப்பட்ட உயரம் கிடைத்தால் மாற்றவும் |
| `KARUVOTTAM_TIMEZONE` | `Asia/Kolkata` |
| `KARUVOTTAM_CHITHIRAI_REFERENCE` | `03-21` — சித்திரை 1 குறிப்பு |
| `KARUVOTTAM_CALENDAR_RULE_VERSION` | `2.0` |
| `KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_YEAR` | `2026` |
| `KARUVOTTAM_MARGAZHI_ALTERNATION_ANCHOR_PHASE` | `new_moon` — anchor ஆண்டின் அமாவாசை |
| `KARUVOTTAM_WEATHER_PROVIDER` | `open-meteo` |
| `KARUVOTTAM_WEATHER_MODEL` | `era5` — அனைத்து கட்டாய hourly fields-க்கும் நிலையான reanalysis |
| `KARUVOTTAM_WEATHER_API_BASE_URL` | வரலாற்று வானிலை API முகவரி |
| `KARUVOTTAM_WEATHER_API_KEY` | விருப்ப API ரகசியம்; Git-இல் சேர்க்கக்கூடாது |
| `KARUVOTTAM_WEATHER_TIMEOUT_SECONDS` | ஒரு request attempt-க்கு `30` விநாடிகள் |
| `KARUVOTTAM_WEATHER_RETRY_ATTEMPTS` | retry உட்பட அதிகபட்சம் `3` attempts |
| `KARUVOTTAM_WEATHER_RETRY_BACKOFF_SECONDS` | exponential retry-ன் ஆரம்ப தாமதம் `1` விநாடி |
| `KARUVOTTAM_WEATHER_RAW_DATA_DIR` | `data/imports/weather/raw` — exact provider responses |
| `KARUVOTTAM_DATABASE_PATH` | `data/karuvottam.sqlite3` — SQLite கோப்பு பாதை |
| `KARUVOTTAM_PORT` | `5000` |

## தரவுத்தளத்தை உருவாக்குதல் / புதுப்பித்தல்

```bash
python -m karuvottam.database migrate
```

இந்த கட்டளையை மீண்டும் இயக்குவது பாதுகாப்பானது. விரிவான schema மற்றும் migration
விதிகள் [docs/DATABASE.md](docs/DATABASE.md)-இல் உள்ளன. PostgreSQL server வெளியீட்டிற்கான
திட்டமிட்ட மாற்றுப் பாதையும் அதில் பதிவு செய்யப்பட்டுள்ளது.

## சோதனைகளை இயக்குவது

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

இந்தச் சோதனைகள் பயன்பாட்டு import, முக்கியப் பக்கங்கள், தவறான ஆண்டு fallback மற்றும் பதிவு,
18 நாள் / 264 மணி நேரச் சாளரங்கள், ஆண்டுதோறும் மாறும் மார்கழி சந்திர கட்டம், 180 / 140 நாள் கால இணைப்பு, migration rollback,
foreign keys, uniqueness மற்றும் restart-க்குப் பிந்தைய database persistence ஆகியவற்றைச்
சரிபார்க்கின்றன.

## விதி விவரக்குறிப்புகள்

- [கருவோட்டக் கால இணைப்பு மற்றும் நேர எல்லைகள்](docs/TIME_MAPPING_SPEC.md)
- [மாற்றியமைக்கப்பட்ட தமிழ் நாட்காட்டி விதி](docs/CALENDAR_RULE_SPEC.md)
- [சந்திர நிகழ்வு கணக்கீடு](docs/LUNAR_EVENT_SPEC.md)
- [பட்சம் மற்றும் திதிகள் — பழைய v1 குறிப்பு](docs/TITHI_RULE_SPEC.md)
- [சூரிய உதயம்/நிலைபெறுதல் — பழைய v1 குறிப்பு](docs/SUNRISE_SPEC.md)
- [கருவோட்டக் கண்காணிப்புக் காலச் சாளர விதி](docs/WINDOW_SPEC.md)
- [வரலாற்று வானிலைத் தரவு வழங்குநர் மதிப்பீடு](docs/WEATHER_PROVIDER_EVALUATION.md)
- [ERA5 weather client மற்றும் ingestion நடைமுறை](docs/WEATHER_INGESTION.md)
- [Weather timestamp மற்றும் precipitation interval விதிகள்](docs/WEATHER_TIME_SPEC.md)
- [Weather data-quality validation விதிகள்](docs/WEATHER_QUALITY.md)
- [Weather CSV import மற்றும் export ஒப்பந்தம்](docs/WEATHER_CSV.md)
