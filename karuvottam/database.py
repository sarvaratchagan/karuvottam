"""SQLite connection and versioned schema migration support."""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Iterable


class MigrationError(RuntimeError):
    """Raised when the migration history is invalid or a migration fails."""


@dataclass(frozen=True)
class Migration:
    """Represent one SQL schema migration loaded from a migration file."""

    version: int
    name: str
    sql: str
    checksum: str


@dataclass(frozen=True)
class MigrationResult:
    """Summarize which migrations were applied and the latest known version."""

    applied_versions: tuple[int, ...]
    current_version: int


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    """Open a configured SQLite database with integrity settings enabled."""
    path_text = str(database_path)

    # Create the parent directory for file-based databases if it does not exist.
    # SQLite's special ':memory:' database does not require a filesystem path.
    if path_text != ':memory:':
        Path(path_text).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    # Set a timeout so a connection can wait briefly when another connection is busy.
    connection = sqlite3.connect(path_text, timeout=30)

    # Return rows that support column-name access, such as row['version'].
    connection.row_factory = sqlite3.Row

    # Enforce foreign-key relationships for this connection.
    connection.execute('PRAGMA foreign_keys = ON')

    # Configure how long SQLite waits for a lock before reporting a busy error.
    connection.execute('PRAGMA busy_timeout = 5000')

    # Use write-ahead logging for file databases to improve reader/writer concurrency.
    if path_text != ':memory:':
        connection.execute('PRAGMA journal_mode = WAL')

    return connection


def _migration_from_path(path: Path) -> Migration:
    """Read a migration file and derive its version, name, SQL, and checksum."""
    # Migration filenames must begin with a numeric version and underscore,
    # for example: 001_create_locations.sql.
    prefix, separator, descriptive_name = path.stem.partition('_')
    if not separator or not prefix.isdigit() or not descriptive_name:
        raise MigrationError(
            f'Migration filename must use NNN_name.sql format: {path.name}'
        )

    # Read the SQL as UTF-8 and hash the exact file contents. The checksum
    # detects changes to a migration after it has already been applied.
    sql = path.read_text(encoding='utf-8')
    return Migration(
        version=int(prefix),
        name=descriptive_name,
        sql=sql,
        checksum=hashlib.sha256(sql.encode('utf-8')).hexdigest(),
    )


def load_migrations(migration_directory: str | Path | None = None) -> tuple[Migration, ...]:
    """Load migrations in version order and reject duplicate versions."""
    # Use the package's built-in migrations directory unless a custom directory
    # is supplied (useful for tests or alternate deployments).
    if migration_directory is None:
        directory = Path(str(files('karuvottam.migrations')))
    else:
        directory = Path(migration_directory)

    # Load every SQL migration and sort numerically by its version.
    migrations = tuple(
        sorted(
            (_migration_from_path(path) for path in directory.glob('*.sql')),
            key=lambda migration: migration.version,
        )
    )

    # Two files with the same version would make migration order ambiguous.
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError('Migration versions must be unique')

    return migrations


def _sql_literal(value: str) -> str:
    """Escape a string for use as a single-quoted SQL literal."""
    # Double embedded single quotes according to SQL string-literal rules.
    # This helper is used for migration metadata embedded in executescript().
    return "'" + value.replace("'", "''") + "'"


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    """Create the table that records successfully applied migrations."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (
                strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            )
        )
        """
    )

    # Persist the tracking table before checking or applying individual migrations.
    connection.commit()


def _applied_migrations(connection: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    """Return applied migration metadata indexed by migration version."""
    rows: Iterable[sqlite3.Row] = connection.execute(
        'SELECT version, name, checksum FROM schema_migrations ORDER BY version'
    )

    # A dictionary makes it easy to check whether a migration version is already applied.
    return {row['version']: row for row in rows}


def migrate_database(
    database_path: str | Path,
    migration_directory: str | Path | None = None,
) -> MigrationResult:
    """Apply pending migrations and verify that applied migration files are unchanged.

    Each migration's SQL and its history entry are executed in one transaction.
    If a migration fails, its transaction is rolled back and a MigrationError
    is raised. The connection is closed regardless of the outcome.
    """
    # Load and validate the migration files before opening the database.
    migrations = load_migrations(migration_directory)
    connection = connect_database(database_path)
    applied_now: list[int] = []

    try:
        # Ensure the database has a place to track migration versions and checksums.
        _ensure_migration_table(connection)
        applied = _applied_migrations(connection)

        for migration in migrations:
            existing = applied.get(migration.version)

            if existing is not None:
                # An applied migration must remain identical to the version originally
                # recorded. Editing its SQL or name could make existing databases differ.
                if (
                    existing['name'] != migration.name
                    or existing['checksum'] != migration.checksum
                ):
                    raise MigrationError(
                        f'Applied migration {migration.version:03d} no longer matches its file'
                    )

                # This migration is already present and verified, so skip it.
                continue

            # Run the migration and record its metadata together. BEGIN IMMEDIATE
            # obtains a write reservation before executing the migration statements.
            # The history entry is inserted only after the migration SQL succeeds.
            script = (
                'BEGIN IMMEDIATE;\n'
                f'{migration.sql}\n'
                'INSERT INTO schema_migrations (version, name, checksum) VALUES ('
                f'{migration.version}, {_sql_literal(migration.name)}, '
                f'{_sql_literal(migration.checksum)});\n'
                'COMMIT;'
            )

            try:
                # executescript() supports a sequence of SQL statements in one script.
                connection.executescript(script)
            except sqlite3.DatabaseError as exc:
                # Undo any uncommitted work before translating the database error.
                if connection.in_transaction:
                    connection.rollback()
                raise MigrationError(
                    f'Failed to apply migration {migration.version:03d}_{migration.name}'
                ) from exc

            # Report only migrations newly applied during this invocation.
            applied_now.append(migration.version)

        # The current version is the highest version available in the migration set,
        # or zero when no migration files are present.
        current_version = max((migration.version for migration in migrations), default=0)
        return MigrationResult(tuple(applied_now), current_version)
    finally:
        # Always release the connection, including when validation or execution fails.
        connection.close()


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for database migration."""
    parser = argparse.ArgumentParser(description='Manage the Karuvottam SQLite schema')

    # At present, the CLI exposes only the migration command.
    parser.add_argument('command', choices=('migrate',))

    # An explicit path overrides the database path configured in application settings.
    parser.add_argument(
        '--database',
        help='SQLite database file path (defaults to KARUVOTTAM_DATABASE_PATH)',
    )
    return parser


def main() -> None:
    """Run the requested database command from the command line."""
    args = _build_parser().parse_args()

    # Prefer an explicitly supplied database path; otherwise use application settings.
    if args.database is None:
        from config import settings

        database_path = settings.database_path
    else:
        database_path = args.database

    # Apply pending migrations and report the outcome to the operator.
    result = migrate_database(database_path)
    if result.applied_versions:
        applied = ', '.join(f'{version:03d}' for version in result.applied_versions)
        print(f'Applied migrations: {applied}')
    else:
        print(f'Database already at version {result.current_version:03d}')


# Execute the command-line entry point only when this file is run directly.
if __name__ == '__main__':
    main()
