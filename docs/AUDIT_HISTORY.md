# T7.5 — Audit history

`audit_logs` records `actor`, `action`, `record_type`, `record_id`, `reason`, and
UTC `created_at`. Audit entries are append-only through the repository API and
commit in the same SQLite transaction as the affected change. A rolled-back edit
leaves neither the change nor its audit event. Entries are ordered by id for a
stable recent-history view.

## Operator actions

After applying migrations, use the CLI on the application host with its configured
`KARUVOTTAM_DATABASE_PATH`:

```bash
.venv/bin/python -m karuvottam.audit set-location-active --location-id 1 --inactive --actor operator-name --reason "Station temporarily closed"
.venv/bin/python -m karuvottam.audit generate-forecast --year 2026 --mode aadi --actor operator-name --reason "Scheduled review"
.venv/bin/python -m karuvottam.audit list --limit 50
```

`set-location-active` writes an event only when the value actually changes. The
forecast command creates or reuses the source lunar event/window, persists the
complete 180/140-day timeline, and writes one `forecast_generated` event linked
to the prediction run id. Repeated explicit generations create separate runs and
audit events. A stored window that disagrees with the current calendar rule stops
generation rather than attaching a run to incorrect source dates.

The web forecast page remains read-only. It calculates an experimental timeline
for display but does not claim that page views are persisted forecast runs. The
operator command is the explicit durable generation action.

Weather CSV imports write one `weather_csv_imported` event per nonempty batch,
linked to its location id. The `--apply` recovery command requires `--actor` and
`--reason`; previews and idempotent repeat imports do not add events. Existing
programmatic callers that do not supply an actor are recorded as
`system:weather-csv`. The actor string is supplied by the operator or calling
process; a later user-account system can provide authenticated identities.

Audit rows record the action and reason rather than copying weather values or
credentials. Protect database access and backups because an operator with direct
SQLite write access can still alter audit history. Keep database backups according
to [the recovery procedure](BACKUP_RECOVERY.md).
