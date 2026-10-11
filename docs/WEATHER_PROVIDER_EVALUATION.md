# வரலாற்று வானிலைத் தரவு வழங்குநர் மதிப்பீடு

- **முடிவு தேதி:** 2026-10-10
- **பணி:** T2.1
- **இலக்கு இடம்:** 9.9040188, 77.8860417
- **தேர்வு:** Open-Meteo Historical Weather API, explicit `models=era5`, `timezone=UTC`

## முடிவு

MVP மற்றும் non-commercial research பயன்பாட்டின் முதன்மை வரலாற்றுத் தரவு வழங்குநராக
**Open-Meteo ERA5** தேர்ந்தெடுக்கப்பட்டுள்ளது. இந்தத் தேர்வு ஏழு கட்டாய hourly fields-ஐ
ஒரே நிலையான model family-ல் வழங்குகிறது, 1940 முதல் கிடைக்கிறது, மேலும் units மற்றும்
hour semantics அதிகாரப்பூர்வ documentation-ல் தெளிவாக உள்ளன.

Default `best_match` பயன்படுத்தப்படாது; பல காலங்களில் model மாறுவதால் நீண்டகால
backtest-ல் செயற்கையான discontinuity வரலாம். `ERA5-Land` தனியாகவும் பயன்படுத்தப்படாது;
அதில் இந்தத் திட்டத்திற்குத் தேவையான precipitation, cloud, wind மற்றும் pressure fields
முழுமையாக கிடைக்கவில்லை.

## வழங்குநர் ஒப்பீடு

| அளவுகோல் | Open-Meteo ERA5 | NASA POWER hourly |
|---|---|---|
| கட்டாய fields | 7/7 | 7/7 |
| Hourly history | 1940 முதல் | 2001 முதல் |
| Nominal spatial resolution | 0.25° (~25 km) | meteorology 0.5° × 0.625°; solar/cloud source சுமார் 1° |
| நேரம் | `timezone=UTC` மூலம் UTC | default LST; `time-standard=UTC` கட்டாயமாகச் சேர்க்க வேண்டும் |
| மழை பொருள் | timestamp-க்கு முந்தைய ஒரு மணி நேரத் தொகை, mm | hourly precipitation rate/amount, mm/hour |
| சமீபத்திய availability | தினசரி புதுப்பிப்பு, சுமார் 5 நாள் தாமதம் | near-real-time; 2–3 மாதத்தில் improved climate-quality data மாற்றலாம் |
| Request limit | Free: 600/min, 5,000/hour, 10,000/day, 300,000/month | ஒரு request-க்கு அதிகபட்சம் 15 parameters; மிக அதிக synchronous requests தடைக்கப்படலாம்; HTTP 429 பயன்படுத்தப்படுகிறது |
| உரிமம் / செலவு | Data CC BY 4.0; free API non-commercial மட்டும்; commercial historical API-க்கு Professional அல்லது மேலான paid plan / self-host தேவை | NASA data இலவசமாகக் கிடைக்கிறது; NASA acknowledgement/citation வலியுறுத்தப்படுகிறது |
| இந்தத் திட்டத்தில் பங்கு | **Primary** | Fallback மற்றும் provider comparison/backtest |

NASA POWER ஒரு நல்ல சுயாதீன ஒப்பீட்டு ஆதாரம். ஆனால் அதன் குறுகிய hourly history,
குறைந்த spatial resolution, local civil time அல்லாத default LST, மற்றும் near-real-time
values பின்னர் மாற்றப்படக்கூடிய தன்மை காரணமாக primary source ஆகத் தேர்ந்தெடுக்கப்படவில்லை.

## அங்கீகரிக்கப்பட்ட Open-Meteo contract

Endpoint:

```text
https://archive-api.open-meteo.com/v1/archive
```

நிலையான parameters:

```text
models=era5
timezone=UTC
temperature_unit=celsius
wind_speed_unit=kmh
precipitation_unit=mm
```

Hourly variables:

```text
temperature_2m
relative_humidity_2m
precipitation
cloud_cover
wind_speed_10m
wind_direction_10m
pressure_msl
```

Expected units:

| Field | Unit | நேரப் பொருள் |
|---|---|---|
| `temperature_2m` | °C | குறிப்பிட்ட மணிநேரத்தின் instantaneous value |
| `relative_humidity_2m` | % | instantaneous |
| `precipitation` | mm | குறிப்பிட்ட timestamp-ல் முடியும் முந்தைய ஒரு மணி நேரத் தொகை |
| `cloud_cover` | % | instantaneous |
| `wind_speed_10m` | km/h | 10 m wind |
| `wind_direction_10m` | degree | instantaneous, 10 m |
| `pressure_msl` | hPa | instantaneous mean-sea-level pressure |

T2.2 client response-ல் `hourly_units` இதே units-ஐக் கொண்டுள்ளதா சரிபார்க்க வேண்டும்.
மாறுபட்ட unit அல்லது குறைந்த array length வந்தால் அந்த response சேமிக்கப்படக்கூடாது.

## இலக்கு இட sample verification

2025-07-01 முதல் 2025-07-02 வரை இலக்கு coordinates-க்கு இரண்டு நேரடி API requests
2026-10-10 அன்று இயக்கப்பட்டன.

### ERA5

- 48 UTC timestamps கிடைத்தன.
- ஏழு கட்டாய variable arrays-லும் 48 values கிடைத்தன.
- API பயன்படுத்திய grid-cell center: `10.0, 78.0`.
- API காட்டிய DEM elevation: `157 m`.
- Unit metadata contract-உடன் பொருந்தியது.

### ERA5-Land rejection evidence

- Temperature மற்றும் humidity மட்டும் கிடைத்தன.
- Precipitation, cloud cover, wind speed/direction மற்றும் pressure அனைத்தும் `null`.
- எனவே அதிக resolution இருந்தாலும் இந்தத் திட்டத்தின் முழு input contract-ஐ நிறைவேற்றாது.

### NASA POWER fallback verification

அதே இரண்டு நாட்களுக்கு `T2M`, `RH2M`, `PRECTOTCORR`, `CLOUD_AMT`, `WS10M`,
`WD10M`, `PS` ஆகிய ஏழு fields-மும் UTC-ல் கிடைத்தன. NASA units வேறுபடுகின்றன:
wind m/s மற்றும் surface pressure kPa; fallback adapter இவை canonical km/h மற்றும் hPa-க்கு
மாற்ற வேண்டும்.

## தரவு தரம் மற்றும் அறிவியல் வரம்புகள்

- ERA5 என்பது station observation அல்ல; observations மற்றும் model assimilation சேர்ந்த
  gridded reanalysis estimate.
- திரும்ப வரும் grid center கேட்ட coordinates-இலிருந்து மாறலாம்; requested coordinates,
  returned grid coordinates மற்றும் elevation அனைத்தும் provenance-ஆகச் சேமிக்கப்பட வேண்டும்.
- தற்போதைய project elevation `0` என்பது placeholder. சரிபார்க்கப்பட்ட site elevation
  கிடைக்கும் வரை API-க்கு `elevation=0` அனுப்பக்கூடாது; provider DEM/downscaling default-ஐ
  பயன்படுத்தி returned elevation-ஐச் சேமிக்க வேண்டும்.
- ERA5 resolution காரணமாக ஊர்/பண்ணை அளவிலான convective rain வேறுபாடுகள் மறையலாம்.
- Missing/null values interpolation செய்யப்படாமல் முதலில் quality flag பெற வேண்டும்.
- Backtest முழுவதும் ஒரே `models=era5` contract பயன்படுத்தப்பட வேண்டும்.

## உரிமம் மற்றும் deployment gate

Open-Meteo free endpoint இந்த MVP-யில் non-commercial research/prototyping-க்கு மட்டும்.
UI/export-ல் Open-Meteo மற்றும் ERA5 attribution காட்டப்பட வேண்டும். Commercial, advertising,
subscription அல்லது SLA deployment முன்:

1. தற்போதைய Open-Meteo pricing/terms மீண்டும் ஆய்வு செய்ய வேண்டும்.
2. Historical API-ஐ உள்ளடக்கும் Professional அல்லது மேலான subscription பெற வேண்டும்,
   அல்லது Open-Meteo server-ஐ உரிய AGPL/தரவு உரிமைகளுடன் self-host செய்ய வேண்டும்.
3. Customer endpoint மற்றும் API key environment configuration-க்கு மாற்றப்பட வேண்டும்.

Exact subscription fee இந்த ஆவணத்தில் freeze செய்யப்படவில்லை; provider விலை மாற்றக்கூடும்.
Procurement நேரத்தில் அதிகாரப்பூர்வ pricing page தான் source of truth.

## அதிகாரப்பூர்வ ஆதாரங்கள்

- [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api)
- [Open-Meteo pricing](https://open-meteo.com/en/pricing)
- [Open-Meteo terms](https://open-meteo.com/en/terms)
- [NASA POWER Hourly API](https://power.larc.nasa.gov/docs/services/api/temporal/hourly/)
- [NASA POWER API overview](https://power.larc.nasa.gov/docs/services/api/)
- [NASA POWER data-request guidance](https://power.larc.nasa.gov/docs/tutorials/service-data-request/api/)
- [NASA Earthdata data-use and citation guidance](https://www.earthdata.nasa.gov/engage/open-data-services-software/data-use-policy)

## அடுத்த செயலாக்கப் பணிகளுக்கான கட்டுப்பாடுகள்

- T2.2: இந்த exact contract-க்கு client, retry, timeout மற்றும் raw provenance உருவாக்குதல்.
- T2.3: UTC timestamp-ஐ canonical `Z` format-க்கு மாற்றி precipitation-ஐ preceding-hour
  accumulation ஆகப் பதிவு செய்தல்.
- T2.4: null/range/length/unit/grid/elevation quality checks சேர்த்தல்.
- T6.1/T9.8: NASA POWER-ஐ independent comparison provider ஆகப் பயன்படுத்துதல்.
