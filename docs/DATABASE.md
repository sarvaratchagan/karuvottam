# Database schema and migrations

## Current database

The MVP uses SQLite. Its path comes from `KARUVOTTAM_DATABASE_PATH` and defaults to
`data/karuvottam.sqlite3`. Relative paths are resolved from the project root. Runtime
database files are ignored by Git.

Create or upgrade the configured database with:

```bash
python -m karuvottam.database migrate
```

For an explicit database path:

```bash
python -m karuvottam.database migrate --database /path/to/karuvottam.sqlite3
```

Running the command repeatedly is safe. Applied migrations are recorded in
`schema_migrations`; the SHA-256 checksum prevents an already-applied migration from
being edited silently.

## Migration rules

- Migration files live in `karuvottam/migrations/` and use `NNN_name.sql` names.
- Never edit a migration that has been applied. Add the next numbered migration.
- Each pending migration is applied in one transaction and rolled back on failure.
- Foreign-key enforcement is enabled for every application connection.
- File databases use write-ahead logging and a busy timeout for safer local access.

## Timestamp convention

SQLite stores application timestamps as ISO-8601 `TEXT`:

- UTC timestamps end in `Z`, for example `2026-07-01T00:30:00Z`.
- Local timestamps include a numeric offset, for example
  `2026-07-01T06:00:00+05:30`.
- Date-only periods use `YYYY-MM-DD`.

The ingestion/data-access layers must normalize values before insertion. SQLite does
not enforce the complete ISO-8601 grammar itself.

## Initial schema

Migration `001_initial.sql` creates the project-plan tables for locations, calendar
rules, lunar events, Karuvottam windows, weather observations, prediction runs and
outputs, validation, weather events and tracks, climate indices, historical rainfall,
event impact assessments, and audit history.

Weather observations enforce the project identity key:

`location_id + observed_at_utc + source`

Observed event tracks, official forecast tracks, and model-guidance tracks use
different `point_type` values so forecast paths cannot be mistaken for actual paths.

## Data-access boundary

Application code uses `DataAccess` from `karuvottam.data_access`; Flask routes must not
contain SQL. A unit of work exposes table-specific repositories that share one
transaction:

```python
from karuvottam.data_access import DataAccess

data_access = DataAccess(database_path)
with data_access.transaction() as work:
    location = work.locations.add(
        name='Target',
        latitude=9.9040188,
        longitude=77.8860417,
        elevation_m=0,
        timezone_name='Asia/Kolkata',
    )
```

The context commits only after the complete block succeeds. Any application or
database exception rolls back every write in the block. SQLite errors are mapped to
stable application exceptions: `DuplicateRecordError`, `ConstraintViolationError`,
and `DataAccessError`. Callers should not parse SQLite error strings.

The initial repositories cover locations, calendar rules, lunar events, Karuvottam
windows, and hourly weather observations. Repositories for forecasts, validation,
auditing, and weather-event analysis are added with those feature phases so their
domain rules and write semantics are explicit rather than exposed through generic SQL.

## PostgreSQL path

PostgreSQL is supported as the planned server/multi-user deployment database, but it
is not activated by T3.1. The domain table boundaries, foreign keys, unique keys, and
ISO-8601 semantics are intentionally straightforward to port. Before deployment,
introduce a PostgreSQL-capable migration/data-access layer (for example SQLAlchemy and
Alembic), translate SQLite-specific defaults and pragmas, and run the same constraint
and persistence tests against PostgreSQL. Do not point the SQLite migration runner at
a PostgreSQL URL.
