ALTER TABLE prediction_runs
ADD COLUMN source_window_key TEXT;

ALTER TABLE prediction_runs
ADD COLUMN mapping_basis_end_local TEXT;

ALTER TABLE prediction_runs
ADD COLUMN score_model_version TEXT;

ALTER TABLE prediction_runs
ADD COLUMN category_threshold_version TEXT;

ALTER TABLE prediction_runs
ADD COLUMN quality_flag TEXT;

ALTER TABLE prediction_runs
ADD COLUMN generated_at TEXT;

ALTER TABLE predictions
ADD COLUMN status TEXT NOT NULL DEFAULT 'legacy';

ALTER TABLE predictions
ADD COLUMN research_score REAL CHECK (
    research_score IS NULL OR research_score BETWEEN 0 AND 100
);

ALTER TABLE predictions
ADD COLUMN quality_flag TEXT;

ALTER TABLE predictions
ADD COLUMN reason_codes TEXT;
