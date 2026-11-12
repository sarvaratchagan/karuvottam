CREATE TABLE weather_stations (
    id INTEGER PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    station_key TEXT NOT NULL,
    name TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('station', 'iot')),
    provider TEXT NOT NULL,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    timezone TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (location_id, station_key)
);

CREATE TABLE station_import_batches (
    id INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES weather_stations(id) ON DELETE RESTRICT,
    payload_sha256 TEXT NOT NULL,
    raw_payload_reference TEXT NOT NULL,
    actor TEXT NOT NULL,
    total_rows INTEGER NOT NULL CHECK (total_rows >= 0),
    accepted_rows INTEGER NOT NULL CHECK (accepted_rows >= 0),
    rejected_rows INTEGER NOT NULL CHECK (rejected_rows >= 0),
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (station_id, payload_sha256)
);

CREATE TABLE station_readings (
    id INTEGER PRIMARY KEY,
    station_id INTEGER NOT NULL REFERENCES weather_stations(id) ON DELETE RESTRICT,
    observation_id INTEGER NOT NULL UNIQUE REFERENCES weather_observations(id) ON DELETE RESTRICT,
    batch_id INTEGER NOT NULL REFERENCES station_import_batches(id) ON DELETE RESTRICT,
    observed_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    row_sha256 TEXT NOT NULL,
    UNIQUE (station_id, observed_at_utc)
);

CREATE INDEX idx_station_readings_time ON station_readings(station_id, observed_at_utc);
