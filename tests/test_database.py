import sqlite3
from pathlib import Path

import pytest

from karuvottam.database import (
    MigrationError,
    connect_database,
    migrate_database,
)


EXPECTED_TABLES = {
    'schema_migrations',
    'locations',
    'calendar_rules',
    'lunar_events',
    'karuvottam_windows',
    'weather_observations',
    'prediction_runs',
    'predictions',
    'validation_results',
    'weather_events',
    'event_track_points',
    'climate_indices',
    'historical_rainfall',
    'event_impact_assessments',
    'audit_logs',
}


def test_initial_migration_creates_every_planned_table(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'

    result = migrate_database(database_path)

    assert result.applied_versions == (1,)
    assert result.current_version == 1
    with connect_database(database_path) as connection:
        tables = {
            row['name']
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row['name'].startswith('sqlite_')
        }
        migration = connection.execute(
            'SELECT version, name, length(checksum) AS checksum_length '
            'FROM schema_migrations'
        ).fetchone()

    assert tables == EXPECTED_TABLES
    assert dict(migration) == {
        'version': 1,
        'name': 'initial',
        'checksum_length': 64,
    }


def test_migration_is_idempotent_and_data_survives_reopen(tmp_path):
    database_path = tmp_path / 'nested' / 'karuvottam.sqlite3'
    migrate_database(database_path)

    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO locations (name, latitude, longitude, elevation_m, timezone)
            VALUES (?, ?, ?, ?, ?)
            """,
            ('Test location', 9.9, 77.8, 0, 'Asia/Kolkata'),
        )
        connection.commit()

    second_result = migrate_database(database_path)
    with connect_database(database_path) as connection:
        stored_name = connection.execute('SELECT name FROM locations').fetchone()['name']

    assert second_result.applied_versions == ()
    assert second_result.current_version == 1
    assert stored_name == 'Test location'


def test_foreign_keys_and_weather_observation_uniqueness_are_enforced(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)

    with connect_database(database_path) as connection:
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        location_id = connection.execute(
            """
            INSERT INTO locations (name, latitude, longitude, timezone)
            VALUES ('Target', 9.9, 77.8, 'Asia/Kolkata')
            """
        ).lastrowid
        observation = (
            location_id,
            '2026-01-01T00:00:00Z',
            '2026-01-01T05:30:00+05:30',
            'provider-a',
            'verified',
        )
        connection.execute(
            """
            INSERT INTO weather_observations (
                location_id, observed_at_utc, observed_at_local, source, quality_flag
            ) VALUES (?, ?, ?, ?, ?)
            """,
            observation,
        )

        with pytest.raises(sqlite3.IntegrityError, match='UNIQUE constraint failed'):
            connection.execute(
                """
                INSERT INTO weather_observations (
                    location_id, observed_at_utc, observed_at_local, source, quality_flag
                ) VALUES (?, ?, ?, ?, ?)
                """,
                observation,
            )

        with pytest.raises(sqlite3.IntegrityError, match='FOREIGN KEY constraint failed'):
            connection.execute(
                """
                INSERT INTO historical_rainfall (
                    location_id, observed_at_utc, observed_at_local,
                    precipitation_mm, source, quality_flag
                ) VALUES (999, '2026-01-01T00:00:00Z',
                          '2026-01-01T05:30:00+05:30', 1.2, 'provider-a', 'verified')
                """
            )


def test_applied_migration_checksum_changes_are_rejected(tmp_path):
    migration_directory = tmp_path / 'migrations'
    migration_directory.mkdir()
    migration_file = migration_directory / '001_sample.sql'
    migration_file.write_text('CREATE TABLE sample (id INTEGER PRIMARY KEY);', encoding='utf-8')
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path, migration_directory)

    migration_file.write_text(
        'CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT);',
        encoding='utf-8',
    )

    with pytest.raises(MigrationError, match='no longer matches'):
        migrate_database(database_path, migration_directory)


def test_invalid_migration_rolls_back_schema_and_history(tmp_path):
    migration_directory = tmp_path / 'migrations'
    migration_directory.mkdir()
    (migration_directory / '001_broken.sql').write_text(
        'CREATE TABLE should_rollback (id INTEGER); INVALID SQL;',
        encoding='utf-8',
    )
    database_path = tmp_path / 'karuvottam.sqlite3'

    with pytest.raises(MigrationError, match='Failed to apply migration'):
        migrate_database(database_path, migration_directory)

    with connect_database(database_path) as connection:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
        ).fetchone()
        history_count = connection.execute(
            'SELECT count(*) FROM schema_migrations'
        ).fetchone()[0]

    assert table is None
    assert history_count == 0
