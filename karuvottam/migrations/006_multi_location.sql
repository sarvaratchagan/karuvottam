CREATE TABLE location_rules (
    location_id INTEGER PRIMARY KEY REFERENCES locations(id) ON DELETE CASCADE,
    chithirai_reference TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    margazhi_anchor_year INTEGER NOT NULL CHECK (margazhi_anchor_year > 0),
    margazhi_anchor_phase TEXT NOT NULL CHECK (margazhi_anchor_phase IN ('new_moon', 'full_moon'))
);

CREATE TABLE karuvottam_windows_location_scoped (
    id INTEGER PRIMARY KEY,
    location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT,
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
    UNIQUE (location_id, season_type, season_year, rule_version)
);

INSERT INTO karuvottam_windows_location_scoped (
    id, location_id, season_type, season_year, start_datetime_local,
    end_datetime_local, duration_hours, trigger_event_id, rule_version,
    status, created_at
)
SELECT id,
       (SELECT CASE WHEN COUNT(*) = 1 THEN MIN(id) ELSE NULL END FROM locations),
       season_type, season_year, start_datetime_local, end_datetime_local,
       duration_hours, trigger_event_id, rule_version, status, created_at
FROM karuvottam_windows;

DROP TABLE karuvottam_windows;
ALTER TABLE karuvottam_windows_location_scoped RENAME TO karuvottam_windows;
CREATE INDEX idx_windows_start ON karuvottam_windows(start_datetime_local);
CREATE INDEX idx_windows_location ON karuvottam_windows(location_id, season_year);

ALTER TABLE prediction_runs ADD COLUMN location_id INTEGER REFERENCES locations(id) ON DELETE RESTRICT;
UPDATE prediction_runs SET location_id = (
    SELECT location_id FROM karuvottam_windows WHERE id = prediction_runs.input_window_id
);
CREATE INDEX idx_prediction_runs_location ON prediction_runs(location_id, generated_at);

CREATE TEMP TABLE migration_fk_guard (bad INTEGER NOT NULL CHECK (bad = 0));
INSERT INTO migration_fk_guard (bad)
SELECT CASE WHEN EXISTS (SELECT 1 FROM pragma_foreign_key_check) THEN 1 ELSE 0 END;
DROP TABLE migration_fk_guard;
