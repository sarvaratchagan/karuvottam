CREATE TABLE locations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    elevation_m REAL,
    timezone TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (name, latitude, longitude)
);

CREATE TABLE calendar_rules (
    id INTEGER PRIMARY KEY,
    rule_name TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    chithirai_reference_date TEXT NOT NULL,
    description TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (rule_name, rule_version)
);

CREATE TABLE lunar_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL CHECK (event_type IN ('full_moon', 'new_moon')),
    event_datetime_utc TEXT NOT NULL,
    event_datetime_local TEXT NOT NULL,
    source TEXT NOT NULL,
    calculation_version TEXT NOT NULL,
    quality_flag TEXT NOT NULL,
    UNIQUE (event_type, event_datetime_utc, source, calculation_version)
);

CREATE TABLE karuvottam_windows (
    id INTEGER PRIMARY KEY,
    season_type TEXT NOT NULL CHECK (season_type IN ('aadi', 'margazhi')),
    season_year INTEGER NOT NULL,
    start_datetime_local TEXT NOT NULL,
    end_datetime_local TEXT NOT NULL,
    duration_hours REAL NOT NULL CHECK (duration_hours > 0),
    trigger_event_id INTEGER REFERENCES lunar_events(id) ON DELETE SET NULL,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (end_datetime_local > start_datetime_local),
    UNIQUE (season_type, season_year, rule_version)
);

CREATE TABLE weather_observations (
    id INTEGER PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    observed_at_utc TEXT NOT NULL,
    observed_at_local TEXT NOT NULL,
    temperature_c REAL,
    relative_humidity_pct REAL CHECK (
        relative_humidity_pct IS NULL OR relative_humidity_pct BETWEEN 0 AND 100
    ),
    precipitation_mm REAL CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
    cloud_cover_pct REAL CHECK (cloud_cover_pct IS NULL OR cloud_cover_pct BETWEEN 0 AND 100),
    wind_speed_kmh REAL CHECK (wind_speed_kmh IS NULL OR wind_speed_kmh >= 0),
    wind_direction_deg REAL CHECK (
        wind_direction_deg IS NULL OR wind_direction_deg BETWEEN 0 AND 360
    ),
    pressure_hpa REAL CHECK (pressure_hpa IS NULL OR pressure_hpa > 0),
    source TEXT NOT NULL,
    is_interpolated INTEGER NOT NULL DEFAULT 0 CHECK (is_interpolated IN (0, 1)),
    quality_flag TEXT NOT NULL,
    raw_payload_reference TEXT,
    UNIQUE (location_id, observed_at_utc, source)
);

CREATE TABLE prediction_runs (
    id INTEGER PRIMARY KEY,
    season_type TEXT NOT NULL CHECK (season_type IN ('aadi', 'margazhi')),
    season_year INTEGER NOT NULL,
    prediction_start TEXT NOT NULL,
    prediction_end TEXT NOT NULL,
    input_window_id INTEGER REFERENCES karuvottam_windows(id) ON DELETE RESTRICT,
    rule_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    notes TEXT,
    CHECK (prediction_end >= prediction_start)
);

CREATE TABLE predictions (
    id INTEGER PRIMARY KEY,
    prediction_run_id INTEGER NOT NULL REFERENCES prediction_runs(id) ON DELETE CASCADE,
    target_datetime_local TEXT NOT NULL,
    rain_probability_pct REAL CHECK (
        rain_probability_pct IS NULL OR rain_probability_pct BETWEEN 0 AND 100
    ),
    predicted_rain_mm REAL CHECK (predicted_rain_mm IS NULL OR predicted_rain_mm >= 0),
    rain_category TEXT,
    data_quality_score REAL,
    prediction_method TEXT NOT NULL,
    model_version TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE (prediction_run_id, target_datetime_local)
);

CREATE TABLE validation_results (
    id INTEGER PRIMARY KEY,
    prediction_run_id INTEGER NOT NULL REFERENCES prediction_runs(id) ON DELETE CASCADE,
    evaluation_period TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    baseline_name TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE weather_events (
    id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('uacc', 'lpa', 'depression', 'deep_depression', 'cyclone')
    ),
    provider_classification TEXT NOT NULL,
    intensity TEXT,
    source TEXT NOT NULL,
    source_reference TEXT,
    issued_at TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    center_latitude REAL CHECK (center_latitude IS NULL OR center_latitude BETWEEN -90 AND 90),
    center_longitude REAL CHECK (
        center_longitude IS NULL OR center_longitude BETWEEN -180 AND 180
    ),
    central_pressure_hpa REAL CHECK (
        central_pressure_hpa IS NULL OR central_pressure_hpa > 0
    ),
    maximum_wind_kmh REAL CHECK (maximum_wind_kmh IS NULL OR maximum_wind_kmh >= 0),
    quality_flag TEXT NOT NULL,
    UNIQUE (source, event_key, issued_at)
);

CREATE TABLE event_track_points (
    id INTEGER PRIMARY KEY,
    weather_event_id INTEGER NOT NULL REFERENCES weather_events(id) ON DELETE CASCADE,
    valid_at TEXT NOT NULL,
    issued_at TEXT,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    point_type TEXT NOT NULL CHECK (
        point_type IN ('observed', 'official_forecast', 'model_guidance')
    ),
    source TEXT NOT NULL,
    movement_distance_km REAL CHECK (
        movement_distance_km IS NULL OR movement_distance_km >= 0
    ),
    movement_speed_kmh REAL CHECK (movement_speed_kmh IS NULL OR movement_speed_kmh >= 0),
    movement_direction_deg REAL CHECK (
        movement_direction_deg IS NULL OR movement_direction_deg BETWEEN 0 AND 360
    ),
    target_distance_km REAL CHECK (target_distance_km IS NULL OR target_distance_km >= 0),
    quality_flag TEXT NOT NULL,
    UNIQUE (weather_event_id, point_type, valid_at, source)
);

CREATE TABLE climate_indices (
    id INTEGER PRIMARY KEY,
    index_type TEXT NOT NULL CHECK (index_type IN ('iod_dmi', 'enso_oni')),
    index_value REAL NOT NULL,
    classification TEXT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    data_version TEXT NOT NULL,
    quality_flag TEXT NOT NULL,
    CHECK (period_end >= period_start),
    UNIQUE (index_type, period_start, period_end, provider, issued_at)
);

CREATE TABLE historical_rainfall (
    id INTEGER PRIMARY KEY,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    observed_at_utc TEXT NOT NULL,
    observed_at_local TEXT NOT NULL,
    precipitation_mm REAL CHECK (precipitation_mm IS NULL OR precipitation_mm >= 0),
    source TEXT NOT NULL,
    quality_flag TEXT NOT NULL,
    is_missing INTEGER NOT NULL DEFAULT 0 CHECK (is_missing IN (0, 1)),
    UNIQUE (location_id, observed_at_utc, source)
);

CREATE TABLE event_impact_assessments (
    id INTEGER PRIMARY KEY,
    weather_event_id INTEGER NOT NULL REFERENCES weather_events(id) ON DELETE CASCADE,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    assessed_at TEXT NOT NULL,
    target_distance_km REAL CHECK (target_distance_km IS NULL OR target_distance_km >= 0),
    prediction_source TEXT NOT NULL,
    model_version TEXT NOT NULL,
    rain_probability_pct REAL CHECK (
        rain_probability_pct IS NULL OR rain_probability_pct BETWEEN 0 AND 100
    ),
    predicted_rain_mm REAL CHECK (predicted_rain_mm IS NULL OR predicted_rain_mm >= 0),
    uncertainty TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    UNIQUE (weather_event_id, location_id, assessed_at, model_version)
);

CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_lunar_events_utc ON lunar_events(event_datetime_utc);
CREATE INDEX idx_windows_start ON karuvottam_windows(start_datetime_local);
CREATE INDEX idx_weather_observations_time ON weather_observations(observed_at_utc);
CREATE INDEX idx_predictions_target ON predictions(target_datetime_local);
CREATE INDEX idx_weather_events_key ON weather_events(event_key);
CREATE INDEX idx_weather_events_issued ON weather_events(issued_at);
CREATE INDEX idx_event_track_points_valid ON event_track_points(weather_event_id, valid_at);
CREATE INDEX idx_climate_indices_period ON climate_indices(index_type, period_start, period_end);
CREATE INDEX idx_historical_rainfall_time ON historical_rainfall(location_id, observed_at_utc);
CREATE INDEX idx_event_impacts_event_location
    ON event_impact_assessments(weather_event_id, location_id, assessed_at);
