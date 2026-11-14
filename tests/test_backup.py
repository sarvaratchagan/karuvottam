import json
import sqlite3
from datetime import datetime, timezone

import pytest

from karuvottam.backup import (
    BackupError,
    create_backup,
    export_weather_csv,
    import_weather_csv,
    restore_backup,
    verify_backup,
)
from karuvottam.database import connect_database, migrate_database


def _database(tmp_path):
    path = tmp_path / 'live.sqlite3'
    migrate_database(path)
    return path


def test_backup_captures_wal_and_restores_without_overwriting_live_database(tmp_path):
    source = _database(tmp_path)
    writer = connect_database(source)
    try:
        writer.execute(
            'INSERT INTO locations (name, latitude, longitude, elevation_m, timezone) '
            'VALUES (?, ?, ?, ?, ?)',
            ('வத்தலக்குண்டு', 10, 77, 0, 'Asia/Kolkata'),
        )
        writer.commit()
        assert source.with_name(source.name + '-wal').exists()
        backup = create_backup(source, tmp_path / 'backups')
        metadata = verify_backup(backup)
        assert metadata['schema_version'] == 9
        restored = restore_backup(backup, tmp_path / 'recovered.sqlite3')
        with sqlite3.connect(restored) as connection:
            assert connection.execute('SELECT name FROM locations').fetchone()[0] == 'வத்தலக்குண்டு'
        with pytest.raises(BackupError, match='already exists'):
            restore_backup(backup, source)
        with pytest.raises(BackupError, match='already exists'):
            restore_backup(backup, restored)
    finally:
        writer.close()


def test_backup_detects_tampering_and_missing_source(tmp_path):
    source = _database(tmp_path)
    backup = create_backup(source, tmp_path / 'backups')
    with backup.open('ab') as stream:
        stream.write(b'tampered')
    with pytest.raises(BackupError, match='checksum mismatch'):
        verify_backup(backup)
    with pytest.raises(BackupError, match='checksum mismatch'):
        restore_backup(backup, tmp_path / 'recovered.sqlite3')
    with pytest.raises(BackupError, match='does not exist'):
        create_backup(tmp_path / 'missing.sqlite3', tmp_path / 'backups')
    assert not (tmp_path / 'missing.sqlite3').exists()


def test_backup_manifest_validation_and_csv_export(tmp_path):
    source = _database(tmp_path)
    with connect_database(source) as connection:
        connection.execute(
            'INSERT INTO locations (name, latitude, longitude, elevation_m, timezone) '
            'VALUES (?, ?, ?, ?, ?)',
            ('Test', 10, 77, 0, 'Asia/Kolkata'),
        )
    backup = create_backup(source, tmp_path / 'backups')
    manifest = backup.with_name(backup.name + '.json')
    data = json.loads(manifest.read_text())
    data['filename'] = 'other.sqlite3'
    manifest.write_text(json.dumps(data))
    with pytest.raises(BackupError, match='filename'):
        verify_backup(backup)

    target = tmp_path / 'weather.csv'
    export_weather_csv(
        source, target, location_id=1,
        start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    assert target.read_text(encoding='utf-8').startswith('observed_at_utc,')
    assert import_weather_csv(source, target, location_id=1) == {
        'total_rows': 0, 'accepted_rows': 0, 'rejected_rows': 0,
    }
    assert import_weather_csv(source, target, location_id=1, apply=True) == {
        'total_rows': 0, 'accepted_rows': 0, 'rejected_rows': 0,
        'inserted_rows': 0, 'existing_rows': 0,
    }
    with pytest.raises(BackupError, match='already exists'):
        export_weather_csv(
            source, target, location_id=1,
            start_utc=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_utc=datetime(2024, 1, 2, tzinfo=timezone.utc),
        )
