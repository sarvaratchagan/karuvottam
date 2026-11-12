# T8.2 — Historical event ingestion and track map

## Source and coverage

This implementation imports NOAA NCEI [IBTrACS v04r01 CSV](https://www.ncei.noaa.gov/products/international-best-track-archive), using the [North Indian Ocean and active subsets](https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/v04r01/access/csv/). NOAA describes IBTrACS as an open best-track archive updated several times weekly, with an active subset covering storms active in the last seven days. Its [column guide](https://www.ncei.noaa.gov/sites/default/files/2025-09/IBTrACS_v04r01_column_documentation.pdf) defines `SID`, UTC time, coordinates, `NEWDELHI_GRADE`, `USA_STATUS`, track type, wind and pressure. IBTrACS merges agency records; it is not a live warning feed or a source of future forecast tracks.

Only North Indian Ocean (`BASIN=NI`) main/provisional rows with a recognized New Delhi grade or USA status and valid coordinates are imported. The raw label remains `provider_classification`; the app maps `D`, `DD`, cyclone grades, `LPA`, and supported USA status codes to the five common types. UACC is outside IBTrACS cyclone-track coverage. Unknown or missing classifications are skipped rather than guessed. Wind knots are converted to km/h and pressure mb is stored as hPa; source wind averaging periods are not normalized. Provisional rows stay marked `provisional`.

The active subset can have North Indian Ocean rows with no usable category. A run may therefore import zero rows. This is a truthful no-data state, not proof that no weather system exists. Consult current official IMD/RSMC bulletins for warnings. No IMD bulletin scraper is installed until its permitted automated-use terms and machine-readable source have been established.

## Import and replay

First apply migrations and take a database backup. Then run:

```bash
.venv/bin/python -m karuvottam.database migrate
.venv/bin/python -m karuvottam.event_ingestion --dataset ni --start-year 2015 --end-year 2026
.venv/bin/python -m karuvottam.event_ingestion --dataset active
```

`--file /path/to/official.csv --retrieved-at 2026-11-07T15:30:00Z` replays an already downloaded official CSV with its actual download time. `--database /path/to/file.sqlite3` targets another database. Each downloaded or supplied CSV is archived by SHA-256 under `data/imports/events/`; retain it with the database backups. The importer reports source rows, inserted/existing/skipped counts, retrieval time and the full file checksum. Replaying the same rows does not duplicate records. A changed bulletin with the same source, SID and issue time stops the transaction and logs the conflicting identity, preserving the stored version for operator review. Do not automatically reclassify or overwrite past bulletins. Download failures exit nonzero and are logged.

The NOAA source URLs are fixed in code. The historical NI import and active import are separate operator jobs; schedule active polling at a reasonable cadence only after configuring backup, logs and alerts. Importing the active subset does not make its last position a live observation. Freshness on the page is measured from the latest **position valid time**, not from the time a historical CSV was downloaded.

## Movement and map

`/events` opens the latest stored event year; `?year=2026` explicitly selects another year and may show no data. The SVG map marks the configured target location and uses three separate visual styles: solid observed path, dashed official forecast path, dotted model guidance. IBTrACS supplies observed/best-track positions only. Official/model lines appear only if corresponding sourced points have been stored; their absence is stated explicitly.

The map includes a bundled, public-domain [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) 1:50m coastline/country layer and southern Indian state outlines. The default viewport shows South India, Sri Lanka, the Arabian Sea and Bay of Bengal; it expands to include more distant stored tracks. These outlines are geographic context, not an official boundary product. The local `karuvottam/event_basemap.json` is generated from Natural Earth's `ne_50m_admin_0_countries.geojson` and `ne_50m_admin_1_states_provinces.geojson` with `scripts/build_event_basemap.py`; no map tiles or runtime map-service requests are needed.

Great-circle distance uses a spherical haversine calculation; bearing is clockwise from north. Speed divides the distance between the latest two distinct observed times by elapsed hours. The page also shows target distance and, where two official forecast issues have the same source and valid time, the largest point shift between those two updates. This is a revision comparison, not a predicted straight-line route. Position and motion alone are not local-rain evidence.

Each event retains issue and retrieval times, provider labels, source URL/reference and quality. Data older than 72 hours is labelled stale; historical events are never presented as current solely because their CSV was downloaded recently. Missing database or missing tracks produce an explicit no-data state. [T8.7 source monitoring](SOURCE_MONITORING.md) separately tracks the last active-feed poll and its failures; a successful empty feed never reclassifies a historical event as current.
