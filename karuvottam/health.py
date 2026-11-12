"""Small read-only database readiness probe for production monitoring."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from karuvottam.database import load_migrations


def database_is_ready(database_path: str | Path) -> bool:
    """Require an existing database with the current migration history and tables."""
    path = Path(database_path).expanduser().resolve()
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(
            f'{path.as_uri()}?mode=ro', uri=True, timeout=2
        )
        try:
            connection.execute('PRAGMA query_only = ON')
            applied = connection.execute(
                'SELECT version, name, checksum FROM schema_migrations ORDER BY version'
            ).fetchall()
            expected = [
                (migration.version, migration.name, migration.checksum)
                for migration in load_migrations()
            ]
            if applied != expected:
                return False
            connection.execute('SELECT 1 FROM locations LIMIT 1').fetchone()
            return True
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return False
