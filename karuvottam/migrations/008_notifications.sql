CREATE TABLE notification_rules (
    id INTEGER PRIMARY KEY,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('source_health', 'source_recovery')),
    source TEXT NOT NULL CHECK (source IN ('all', 'active', 'dmi', 'oni')),
    channel TEXT NOT NULL CHECK (channel IN ('email', 'message')),
    destination TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (event_kind, source, channel, destination)
);

CREATE TABLE notification_source_state (
    source TEXT PRIMARY KEY CHECK (source IN ('active', 'dmi', 'oni')),
    health TEXT NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE notification_deliveries (
    id INTEGER PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES notification_rules(id),
    source TEXT NOT NULL,
    event_kind TEXT NOT NULL,
    health TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sending', 'sent', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    leased_until TEXT,
    last_error_code TEXT,
    sent_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (rule_id, source, event_kind, created_at)
);

CREATE INDEX notification_deliveries_due
    ON notification_deliveries(status, next_attempt_at);
