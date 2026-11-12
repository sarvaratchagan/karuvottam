"""Verified SQLite snapshots and weather CSV recovery commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class BackupError(RuntimeError):
    """A backup cannot be created, verified, or restored safely."""


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(chunk)
    return checksum.hexdigest()


def _check_database(path: Path) -> int:
    if not path.is_file():
        raise BackupError(f'database file does not exist: {path}')
    try:
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
        try:
            result = connection.execute('PRAGMA integrity_check').fetchone()[0]
            if result != 'ok':
                raise BackupError(f'SQLite integrity check failed: {result}')
            row = connection.execute(
                'SELECT MAX(version) FROM schema_migrations'
            ).fetchone()
            return int(row[0] or 0)
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f'invalid Karuvottam database: {path}') from exc


def create_backup(database: str | Path, directory: str | Path) -> Path:
    """Take a consistent online snapshot, then publish it with a SHA-256 manifest."""
    source = Path(database).expanduser().resolve()
    if not source.is_file():
        raise BackupError(f'database file does not exist: {source}')
    target_dir = Path(directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    name = f'karuvottam-{stamp}-{uuid4().hex[:12]}.sqlite3'
    target = target_dir / name
    manifest = target.with_name(target.name + '.json')
    with tempfile.TemporaryDirectory(prefix='.backup-', dir=target_dir) as scratch:
        temporary = Path(scratch) / name
        try:
            source_connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
            try:
                with sqlite3.connect(temporary) as target_connection:
                    source_connection.backup(target_connection)
            finally:
                source_connection.close()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f'could not back up database: {source}') from exc
        version = _check_database(temporary)
        metadata = {
            'format': 'karuvottam-sqlite-backup-v1',
            'filename': name,
            'created_at_utc': datetime.now(timezone.utc).isoformat(),
            'schema_version': version,
            'size_bytes': temporary.stat().st_size,
            'sha256': _digest(temporary),
        }
        temporary_manifest = Path(scratch) / manifest.name
        temporary_manifest.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + '\n', encoding='utf-8'
        )
        # UUID names make collision unlikely; hard links also refuse any overwrite.
        os.link(temporary, target)
        try:
            os.link(temporary_manifest, manifest)
        except OSError:
            target.unlink()
            raise
    return target


def verify_backup(backup: str | Path) -> dict[str, object]:
    """Check manifest, checksum, schema version and SQLite integrity."""
    path = Path(backup).expanduser().resolve()
    manifest = path.with_name(path.name + '.json')
    try:
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise BackupError(f'missing or invalid backup manifest: {manifest}') from exc
    if not isinstance(metadata, dict) or metadata.get('format') != 'karuvottam-sqlite-backup-v1':
        raise BackupError('unsupported backup manifest format')
    if metadata.get('filename') != path.name or not path.is_file():
        raise BackupError('backup filename does not match manifest or file is missing')
    if metadata.get('size_bytes') != path.stat().st_size or metadata.get('sha256') != _digest(path):
        raise BackupError('backup size or SHA-256 checksum mismatch')
    if metadata.get('schema_version') != _check_database(path):
        raise BackupError('backup schema version mismatch')
    return metadata


def restore_backup(backup: str | Path, destination: str | Path) -> Path:
    """Restore a verified snapshot to a new file, refusing existing destinations."""
    source = Path(backup).expanduser().resolve()
    verify_backup(source)
    target = Path(destination).expanduser().resolve()
    if source == target or target.exists():
        raise BackupError(f'restore destination already exists: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=target.parent) as scratch:
        temporary = Path(scratch) / target.name
        shutil.copyfile(source, temporary)
        if _digest(source) != _digest(temporary):
            raise BackupError('restored copy checksum mismatch')
        _check_database(temporary)
        try:
            os.link(temporary, target)
        except FileExistsError as exc:
            raise BackupError(f'restore destination already exists: {target}') from exc
    return target


def export_weather_csv(
    database: str | Path, destination: str | Path, *, location_id: int,
    start_utc: datetime, end_utc: datetime,
) -> Path:
    """Export normalized weather observations through the existing CSV service."""
    from karuvottam.data_access import DataAccess
    from karuvottam.weather_csv import WeatherCsvService

    source = Path(database).expanduser().resolve()
    _check_database(source)
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise BackupError(f'CSV destination already exists: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    content = WeatherCsvService(DataAccess(source)).export(
        location_id=location_id, start_utc=start_utc, end_utc=end_utc
    )
    with target.open('x', encoding='utf-8', newline='') as stream:
        stream.write(content)
    return target


def import_weather_csv(
    database: str | Path, source: str | Path, *, location_id: int, apply: bool = False,
    actor: str = 'system:weather-csv', reason: str = 'Weather CSV recovery',
) -> dict[str, int]:
    """Preview weather recovery; write accepted rows only when explicitly requested."""
    from karuvottam.data_access import DataAccess
    from karuvottam.weather_csv import WeatherCsvService

    path = Path(database).expanduser().resolve()
    _check_database(path)
    service = WeatherCsvService(DataAccess(path))
    preview = service.preview_import(Path(source).read_bytes(), location_id=location_id)
    result = {
        'total_rows': preview.total_rows,
        'accepted_rows': preview.accepted_rows,
        'rejected_rows': preview.rejected_rows,
    }
    if apply:
        imported = service.import_preview(preview, actor=actor, reason=reason)
        result['inserted_rows'] = imported.inserted_rows
        result['existing_rows'] = imported.existing_rows
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description='Karuvottam backup and recovery')
    subparsers = parser.add_subparsers(dest='command', required=True)
    create = subparsers.add_parser('create', help='create a verified SQLite snapshot')
    create.add_argument('--database', help='defaults to KARUVOTTAM_DATABASE_PATH')
    create.add_argument('--directory', required=True, help='backup directory')
    verify = subparsers.add_parser('verify', help='verify a snapshot and manifest')
    verify.add_argument('backup')
    restore = subparsers.add_parser('restore', help='restore to a new database file')
    restore.add_argument('backup')
    restore.add_argument('--destination', required=True)
    export = subparsers.add_parser('export-weather', help='export recoverable weather CSV')
    export.add_argument('--database', help='defaults to KARUVOTTAM_DATABASE_PATH')
    export.add_argument('--destination', required=True)
    export.add_argument('--location-id', required=True, type=int)
    export.add_argument('--start', required=True, help='inclusive UTC ISO-8601 timestamp')
    export.add_argument('--end', required=True, help='inclusive UTC ISO-8601 timestamp')
    import_command = subparsers.add_parser('import-weather', help='preview or apply weather CSV recovery')
    import_command.add_argument('--database', help='defaults to KARUVOTTAM_DATABASE_PATH')
    import_command.add_argument('--source', required=True)
    import_command.add_argument('--location-id', required=True, type=int)
    import_command.add_argument('--apply', action='store_true', help='insert accepted rows')
    import_command.add_argument('--actor', help='operator identity (required with --apply)')
    import_command.add_argument('--reason', help='change reason (required with --apply)')
    args = parser.parse_args()
    if args.command in ('create', 'export-weather', 'import-weather'):
        from config import settings

        database = args.database or settings.database_path
    try:
        if args.command == 'create':
            print(create_backup(database, args.directory))
        elif args.command == 'verify':
            print(json.dumps(verify_backup(args.backup), sort_keys=True))
        elif args.command == 'restore':
            print(restore_backup(args.backup, args.destination))
        elif args.command == 'export-weather':
            start = datetime.fromisoformat(args.start.replace('Z', '+00:00'))
            end = datetime.fromisoformat(args.end.replace('Z', '+00:00'))
            if start.tzinfo is None or end.tzinfo is None or start > end:
                raise ValueError('start and end must be ordered timezone-aware timestamps')
            print(export_weather_csv(
                database, args.destination, location_id=args.location_id,
                start_utc=start, end_utc=end,
            ))
        else:
            if args.apply and (not args.actor or not args.reason):
                raise ValueError('--actor and --reason are required with --apply')
            print(json.dumps(import_weather_csv(
                database, args.source, location_id=args.location_id,
                apply=args.apply, actor=args.actor or 'system:weather-csv',
                reason=args.reason or 'Weather CSV recovery',
            ), sort_keys=True))
    except (BackupError, ValueError, OSError) as exc:
        parser.exit(1, f'Backup error: {exc}\n')


if __name__ == '__main__':
    main()
