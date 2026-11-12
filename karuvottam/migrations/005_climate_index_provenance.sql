ALTER TABLE climate_indices ADD COLUMN retrieved_at TEXT;
ALTER TABLE climate_indices ADD COLUMN source_url TEXT;
ALTER TABLE climate_indices ADD COLUMN source_sha256 TEXT;
ALTER TABLE climate_indices ADD COLUMN issue_time_basis TEXT NOT NULL DEFAULT 'legacy_unspecified';

CREATE INDEX idx_climate_indices_latest
ON climate_indices(index_type, period_end DESC, issued_at DESC, id DESC);
