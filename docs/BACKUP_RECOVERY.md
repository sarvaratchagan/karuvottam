# T7.3 — Backup and recovery

The SQLite database is the authoritative application store. A weather CSV preserves
normalized weather observations only; it does not preserve locations, windows,
predictions, event records, audit rows, or raw provider responses. Keep raw weather
archives (`KARUVOTTAM_WEATHER_RAW_DATA_DIR`) and exported evaluation files separately.

## Daily backup

From the project directory, with the virtual environment installed:

```bash
.venv/bin/python -m karuvottam.backup create \
  --database data/karuvottam.sqlite3 \
  --directory /path/to/offsite-or-mounted-backups
```

The command uses SQLite's online backup API, so committed WAL transactions are
included while the application is running. It writes a uniquely named `.sqlite3`
snapshot and an adjacent `.sqlite3.json` manifest containing SHA-256, byte count,
creation time and schema version. A failed command exits nonzero. Do not treat an
unpaired snapshot as a completed backup.

Install a daily 02:15 local-time cron entry on the host that owns the database (edit
paths for that host):

```cron
15 2 * * * cd /absolute/path/to/karuvottam && /absolute/path/to/karuvottam/.venv/bin/python -m karuvottam.backup create --database /absolute/path/to/karuvottam/data/karuvottam.sqlite3 --directory /mounted/offsite/karuvottam >> /absolute/path/to/backup.log 2>&1
```

The scheduler is an operator deployment step; this repository does not install a
machine-wide cron job. Monitor nonzero exits and the age of the newest verified pair.
Retain at least 30 daily pairs and a separate monthly pair according to local storage
policy. Delete the `.sqlite3` and matching `.json` together only after a newer pair
has passed verification and a restore drill. Store copies on another disk or host;
the application host alone is not a disaster-recovery copy. Restrict backup and log
permissions to the service operator.

## Verify and restore drill

```bash
.venv/bin/python -m karuvottam.backup verify /mounted/offsite/karuvottam/karuvottam-YYYYMMDDTHHMMSSZ-ID.sqlite3
.venv/bin/python -m karuvottam.backup restore /mounted/offsite/karuvottam/karuvottam-YYYYMMDDTHHMMSSZ-ID.sqlite3 --destination /tmp/karuvottam-restore-drill.sqlite3
.venv/bin/python -m karuvottam.database migrate --database /tmp/karuvottam-restore-drill.sqlite3
```

Use a fresh destination for every drill. `verify` checks the manifest, checksum,
schema version and SQLite integrity. `restore` repeats those checks, copies and checks
the snapshot, and refuses to overwrite an existing destination. The migration command
checks that the restored schema agrees with this checkout. Inspect key row counts and
recent observations in the drill copy before retiring old backups.

## Recover from data loss

1. Stop the web app and ingestion jobs. Preserve the damaged database **and** any
   `-wal`/`-shm` companions for diagnosis; do not run migrations on the damaged copy.
2. Choose the newest complete `.sqlite3` + `.json` pair and run `verify`.
3. Run `restore` to a **new** path on the application filesystem. Run `migrate`
   against it, then inspect locations, observation counts and recent timestamps.
4. With the app stopped, move the damaged database and its WAL/SHM files aside, then
   move the verified restored file to `KARUVOTTAM_DATABASE_PATH`. Keep the damaged
   files until recovery is confirmed. Restart the app and ingestion, check `/admin`
   and logs, and reconcile any writes newer than the backup from raw archives/CSV.

Never copy a live SQLite file by itself: pending committed writes may be in WAL. The
restore command deliberately does not replace the live path.

## Weather CSV fallback

When a database backup is unavailable, create/migrate a fresh database and recreate
the location first. Export a recoverable weather range from an intact database:

```bash
.venv/bin/python -m karuvottam.backup export-weather --database data/karuvottam.sqlite3 --location-id 1 --start 2024-01-01T00:00:00Z --end 2024-12-31T23:00:00Z --destination /mounted/offsite/weather-2024.csv
```

Preview before importing, then explicitly apply accepted rows:

```bash
.venv/bin/python -m karuvottam.backup import-weather --database /path/to/recovered.sqlite3 --location-id 1 --source /mounted/offsite/weather-2024.csv
.venv/bin/python -m karuvottam.backup import-weather --database /path/to/recovered.sqlite3 --location-id 1 --source /mounted/offsite/weather-2024.csv --apply --actor operator-name --reason "Restore weather observations"
```

Check `accepted_rows` and `rejected_rows`; investigate rejects before relying on the
recovered data. CSV imports are idempotent for location + UTC hour + source, and
quality flags are recalculated. CSV cannot reconstruct the other database tables.
