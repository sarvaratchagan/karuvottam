ALTER TABLE weather_events
ADD COLUMN classification_basis TEXT NOT NULL DEFAULT 'legacy_unspecified'
CHECK (classification_basis IN (
    'legacy_unspecified', 'provider_category', 'analyst_interpretation'
));

ALTER TABLE weather_events
ADD COLUMN classification_rule_version TEXT;

ALTER TABLE weather_events
ADD COLUMN source_url TEXT;

CREATE INDEX idx_weather_events_identity_issue
ON weather_events(source, event_key, issued_at DESC, id DESC);
