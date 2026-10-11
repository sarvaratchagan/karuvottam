ALTER TABLE weather_observations
ADD COLUMN precipitation_interval_start_utc TEXT;

ALTER TABLE weather_observations
ADD COLUMN precipitation_interval_end_utc TEXT;

ALTER TABLE weather_observations
ADD COLUMN precipitation_interval_minutes INTEGER CHECK (
    precipitation_interval_minutes IS NULL OR precipitation_interval_minutes > 0
);

-- T2.2 records already ingested from the pinned ERA5 contract have known
-- preceding-hour semantics, so their interval metadata can be recovered safely.
UPDATE weather_observations
SET precipitation_interval_start_utc = strftime(
        '%Y-%m-%dT%H:%M:%SZ', observed_at_utc, '-1 hour'
    ),
    precipitation_interval_end_utc = observed_at_utc,
    precipitation_interval_minutes = 60
WHERE source = 'open-meteo:era5';
