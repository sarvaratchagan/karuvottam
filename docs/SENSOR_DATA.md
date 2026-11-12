# T9.2 — Station and IoT sensor observations

The application accepts **hourly readings measured at a registered station or IoT sensor**. Register the physical sensor against an active location representing its actual coordinates and timezone. If a sensor is at another site, create that location first using [T9.1](MULTI_LOCATION.md). A station's coordinates must match its selected location; readings from a distant sensor are not silently treated as measurements at the project's target point.

Migration `007_station_sensors.sql` adds station metadata, import batches, and one provenance link per accepted reading. The normalized readings use the existing `weather_observations` table with source `station:<station_key>`. ERA5 remains `open-meteo:era5`; the two sources are stored, inspected, and quality checked separately. This import does not change the ERA5-based research forecast or its historical validation.

## Hourly CSV contract

Use UTF-8 CSV with exactly these headers, in any order:

```text
observed_at_utc,recorded_at_utc,temperature_c,relative_humidity_pct,precipitation_mm,cloud_cover_pct,wind_speed_kmh,wind_direction_deg,pressure_hpa,precipitation_interval_start_utc,precipitation_interval_end_utc,precipitation_interval_minutes
```

- `observed_at_utc` is the **end** of an exact UTC observation hour, with an ISO-8601 offset such as `2026-07-01T01:00:00Z`.
- `recorded_at_utc` is when the sensor/logger recorded the reading; it may include minutes and seconds but cannot precede `observed_at_utc`.
- Weather values use °C, %, mm, %, km/h, degrees, and hPa respectively. Leave unavailable fields blank; at least one measured field is required.
- If `precipitation_mm` is present, the interval must be exactly the preceding 60 minutes and end at `observed_at_utc`. Otherwise all three interval fields stay blank. Accumulations of unknown duration are not accepted as hourly rainfall.
- One file can contain up to 10,000 readings over at most 31 days. Split longer exports into monthly batches.

Example:

```csv
observed_at_utc,recorded_at_utc,temperature_c,relative_humidity_pct,precipitation_mm,cloud_cover_pct,wind_speed_kmh,wind_direction_deg,pressure_hpa,precipitation_interval_start_utc,precipitation_interval_end_utc,precipitation_interval_minutes
2026-07-01T01:00:00Z,2026-07-01T01:05:00Z,28.1,72,0.5,80,6,250,1005,2026-07-01T00:00:00Z,2026-07-01T01:00:00Z,60
```

## Register and import

```sh
python -m karuvottam.database migrate

python -m karuvottam.sensor_data register \
  --location-id 2 --station-key gauge-1 --name 'Village gauge' \
  --kind iot --provider 'Village committee' \
  --actor operator --reason 'Install village gauge'

python -m karuvottam.sensor_data preview \
  --station-id 1 --file readings.csv

python -m karuvottam.sensor_data import \
  --station-id 1 --file readings.csv \
  --actor operator --reason 'Daily station upload'
```

The preview reports row errors and time coverage without writing. Import archives the exact CSV under `data/imports/weather/raw/stations/<station-id>/<sha256>.csv`, records its checksum and batch counts, and inserts accepted rows with links to their station, batch, logger time, and normalized row checksum. Repeating an unchanged upload is idempotent. A changed reading at an existing station/time is rejected and the database transaction rolls back; it is never silently overwritten. Out-of-range or duplicate rows are rejected; missing fields are flagged. Gaps are reported in the preview and the [observation inspection page](/observations).

These are measured station values, subject to the device's siting, calibration, and maintenance. The app validates structural and value ranges but cannot independently certify a sensor's physical accuracy. Sensor data is labeled with its station and provider in `/observations` and is not automatically substituted into the calibrated forecast pipeline.
