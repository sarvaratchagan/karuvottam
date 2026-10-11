# Historical weather ingestion

T2.2 implements the selected Open-Meteo ERA5 contract as three separate boundaries:

1. `OpenMeteoHistoricalClient` retrieves and checks the provider response.
2. `RawWeatherPayloadStore` preserves the exact response plus retrieval metadata.
3. `WeatherIngestionService` converts hourly rows and stores them idempotently through
   the data-access layer.

## Request behavior

Every request explicitly sends:

- target latitude and longitude;
- inclusive `start_date` and `end_date`;
- the seven approved hourly variables;
- `models=era5` and `timezone=UTC`;
- Celsius, km/h, and millimetre units.

The client rejects invalid coordinates, reversed ranges, dates before ERA5 coverage,
and dates inside the expected five-day ERA5 publication delay. A configured API key is
sent to the provider but removed from the provenance URL and error messages.

## Timeout and retry policy

- Default timeout: 30 seconds per attempt.
- Default attempts: 3.
- HTTP 429, 500, 502, 503, and 504 are retried.
- Network, DNS, and timeout failures are retried.
- Numeric `Retry-After` is honoured up to 60 seconds.
- Otherwise exponential delays are used: 1, 2, 4 seconds, capped at 60 seconds.
- Other 4xx responses fail immediately with a safe provider reason when available.
- HTTPS certificates are verified against the maintained `certifi` CA bundle; TLS
  verification is never disabled.

These values are configurable through `.env`. No retry is performed inside a database
transaction.

## Response contract

Before ingestion, the client requires:

- HTTP 200 and valid JSON;
- zero UTC offset;
- the expected unit for every field;
- a list for time and every required variable;
- equal, non-empty hourly array lengths;
- returned grid latitude/longitude and optional elevation.

Null weather values remain null and are marked `unvalidated_reanalysis`; range,
missingness, and interpolation decisions belong to T2.4. T2.3 owns the final timestamp
and accumulation-period specification.

## Raw payload provenance

Exact response bytes are stored below `KARUVOTTAM_WEATHER_RAW_DATA_DIR` using their
SHA-256 digest:

```text
open-meteo/era5/<sha256>.json
open-meteo/era5/<sha256>.metadata.json
```

The metadata contains request dates and coordinates, returned grid coordinates and
elevation, retrieval time, a sanitized request URL, and the checksum. Writes are
atomic. Re-fetching identical content reuses the existing artifact. The relative JSON
path is stored in every observation's `raw_payload_reference`.

## Idempotency

The database identity key remains:

```text
location_id + observed_at_utc + source
```

The ERA5 source key is `open-meteo:era5`. Ingestion uses `ON CONFLICT DO NOTHING` and
reports inserted and existing counts. Repeating the same range therefore neither
duplicates rows nor overwrites the original record. All rows from one response are
written in a single transaction.

## Application wiring

The Flask application exposes the configured objects without making a network request
at startup:

```python
service = app.extensions['weather_ingestion_service']
report = service.ingest(
    location_id=location_id,
    latitude=9.9040188,
    longitude=77.8860417,
    start_date=date(2025, 7, 1),
    end_date=date(2025, 7, 2),
)
```

The database must already be migrated and the referenced location must exist. Network
retrieval and raw archival happen before the database transaction; a database failure
cannot leave a partial set of observation rows.
