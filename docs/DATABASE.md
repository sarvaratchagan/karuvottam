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

The ingestion/data-access layers normalize values before insertion and verify that a
weather row's UTC and local timestamps represent the same instant. SQLite does not
enforce the complete ISO-8601 grammar itself.

## Initial schema

Migration `001_initial.sql` creates the project-plan tables for locations, calendar
rules, lunar events, Karuvottam windows, weather observations, prediction runs and
outputs, validation, weather events and tracks, climate indices, historical rainfall,
event impact assessments, and audit history.

Migration `002_weather_time_intervals.sql` adds the preceding-hour precipitation
interval start, end, and duration to weather observations. Existing ERA5 rows are
backfilled; records from sources with unknown accumulation semantics remain null.

Migration `003_prediction_traceability.sql` adds source-window, mapping-boundary,
score/category version, quality, generation-time, status, research-score, and reason
fields to forecast runs and entries. Probability and predicted-rain fields remain
nullable and are deliberately null for `daily-timeline-1.0`.

Migration `004_event_provenance.sql` adds normalized-classification provenance and
source URL fields to weather event bulletins, preserving existing rows with a
`legacy_unspecified` classification basis. It also indexes identity/history reads.

Migration `005_climate_index_provenance.sql` adds source URL/checksum, retrieval time
and explicit issue-time basis to DMI/ONI rows, preserving existing values.

Migration `006_multi_location.sql` adds optional per-location calendar profiles,
location-specific window uniqueness, and a location key on saved forecast runs.
Legacy windows and runs are assigned to the sole existing location when possible;
the migration validates all foreign keys before it commits. See
[multiple locations](MULTI_LOCATION.md) for operator commands.

Migration `007_station_sensors.sql` adds station metadata, checksum-addressed
import batches, and per-reading links to normalized weather observations. See
[station and IoT observations](SENSOR_DATA.md) for the input contract.

Migration `008_notifications.sql` adds opt-in alert rules, source-health transition
state and a durable delivery queue with retry status. See
[notifications](NOTIFICATIONS.md) for setup and scheduling.

Migration `009_user_accounts.sql` adds account identities, role assignments,
enabled state and salted password hashes. See [user accounts](USER_ACCOUNTS.md).

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

Repositories cover locations, calendar rules, lunar events, Karuvottam windows,
hourly weather observations, and complete forecast timelines. `work.forecasts`
persists a run and all of its entries in the surrounding unit-of-work transaction;
`input_window_id` supplies the required database link to the source window.
Audit and weather-event repositories are available through the same transaction;
their domain rules and write semantics are documented in their feature guides.

## PostgreSQL path

PostgreSQL is supported as the planned server/multi-user deployment database, but it
is not activated by T3.1. The domain table boundaries, foreign keys, unique keys, and
ISO-8601 semantics are intentionally straightforward to port. Before deployment,
introduce a PostgreSQL-capable migration/data-access layer (for example SQLAlchemy and
Alembic), translate SQLite-specific defaults and pragmas, and run the same constraint
and persistence tests against PostgreSQL. Do not point the SQLite migration runner at
a PostgreSQL URL.
