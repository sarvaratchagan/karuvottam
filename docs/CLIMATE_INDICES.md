# T8.3 — DMI and ONI seasonal context

The app ingests two source-reported sea-surface-temperature indices:

- [NOAA PSL monthly DMI](https://psl.noaa.gov/data/timeseries/month/DMI/), derived from HadISST1.1. The [CSV](https://psl.noaa.gov/data/timeseries/month/data/dmi.had.long.csv) has one value per month and uses `-9999` for missing values. The importer skips those markers.
- [NOAA CPC ONI v6](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/), an ERSSTv6 three-month running Niño-3.4 index. Its year/season columns are converted to exact overlapping start/end dates, including cross-year DJF and NDJ periods. CPC warns that recent ONI values can change. CPC now uses RONI for official ENSO monitoring; ONI remains historical context here.

These are **seasonal ocean-context values**, never daily local-rain measurements,
rain probabilities, or official event declarations. DMI positive/negative labels
describe only the sign of the index. ONI warm/cold/neutral bands use ±0.5 °C but
do not apply CPC's multi-season episode rule or claim an official El Niño/La Niña
state. The newest two ONI values are tagged `recent_estimate`.

## Import

Apply migrations and take a database backup before the first import:

```bash
.venv/bin/python -m karuvottam.database migrate
.venv/bin/python -m karuvottam.climate_indices --source dmi
.venv/bin/python -m karuvottam.climate_indices --source oni
```

Only the two fixed NOAA URLs can be fetched. Exact source responses are archived
by SHA-256 under `data/imports/climate/`; retain them with database backups.
`--file` replays an archived source and requires `--issued-at`, `--retrieved-at`
and `--issue-time-basis` so provenance is not invented. Use `--database` to target
another SQLite file.

DMI's HTTP `Last-Modified` timestamp is stored as `issued_at` with
`issue_time_basis=http_last_modified`. This is a file modification time, not a
separately published scientific release date. CPC's ONI page provides no such
header, so its retrieval timestamp is stored as an explicitly labelled
`retrieval_proxy`. Both retain the actual retrieval time, provider, dataset
version, source URL, source checksum, exact period and quality flag. Reimporting
the same checksum is idempotent; changed source files make new revisions while
preserving prior values. A conflicting value for the same source issue timestamp
stops the transaction for review.

`/climate` shows each latest value, 12 recent periods, source/version, issue-time
basis, retrieval time and age of the latest period. Values whose period ended
more than 120 days ago are labelled stale. Missing or unavailable data receives
an explicit state. This page does not feed the experimental rain score.

[T8.7 source monitoring](SOURCE_MONITORING.md) also shows each source's last
poll attempt, last successful fetch, latest source period and any poll failure.
A fresh fetch of unchanged values does not reset the age of the index period.
