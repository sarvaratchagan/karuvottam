# T8.7 — Event and climate source monitoring

The existing IBTrACS and DMI/ONI importers keep source URLs, retrieval/issue times, quality and raw-source archives. This monitor adds **poll-attempt history** so a successful source check with no new rows can be distinguished from a failed or never-run check. It does not turn IBTrACS into an official live warning feed.

## Commands

```bash
.venv/bin/python -m karuvottam.event_monitor poll --source active
.venv/bin/python -m karuvottam.event_monitor poll --source dmi
.venv/bin/python -m karuvottam.event_monitor poll --source oni
.venv/bin/python -m karuvottam.event_monitor check
```

`poll` without `--source` checks all three sources. Each source fetch uses its existing fixed NOAA URL and importer, archives the exact response, and records a SHA-256, retrieval time, usable/skipped row counts, missing-coordinate point count and (for climate indices) latest period end. Repeated content remains idempotent; conflicting same-issue records fail without overwriting the last accepted value. A successful active-file fetch with zero usable classified NI points is recorded as **successful poll / no usable rows**, not proof that no storm exists. Network/API errors, HTTP 429, HTTP 5xx, malformed source data, database failures and conflicts produce a nonzero poll exit and a redacted log code.

`check` is read-only and exits nonzero if any required source has never succeeded, the last attempt failed, the last success is overdue, a climate period is stale, or the state file cannot be read. Active polling is overdue after 24 hours; DMI/ONI after 45 days. A latest DMI/ONI period ending more than 120 days ago is stale even after a recent successful fetch. The JSON output lists the status of each source. `--source` narrows either command to one or more sources. A failed poll preserves the previous success timestamp, digest, and period, while recording the failed attempt and reason. The UI separately shows stored record age and poll health; a newly downloaded historical CSV cannot make an old track current.

The atomic status file defaults to `data/monitor/source_status.json`. Set `KARUVOTTAM_SOURCE_MONITOR_STATE` (or `--state` for the CLI) to a persistent writable path shared with the web process. Restrict it to the service account. Set `KARUVOTTAM_DATABASE_PATH` and `KARUVOTTAM_LOG_PATH` consistently for the web and scheduled commands. The log uses the application's redacting, rotating formatter; it records source names, counts, SHA-256 and error codes without response bodies or credentials. `rate_limited` is retried on the next scheduled poll rather than immediately hammering the source.

An example schedule is in [`deploy/source-monitor.cron.example`](../deploy/source-monitor.cron.example): active every 12 hours, DMI/ONI weekly, health check daily. Install it on the deployment host as the service account and monitor nonzero exits. Opt-in email/message delivery through the durable queue is described in [T9.3 notifications](NOTIFICATIONS.md). No cron job or destination is installed by default. Investigate the archived response and redacted log before replaying or changing a parser.
