import csv
import hashlib
import io
from datetime import datetime, timezone

import pytest

from karuvottam.data_access import DataAccess, DuplicateRecordError
from karuvottam.database import connect_database, migrate_database
from karuvottam.observation_inspection import ObservationInspectionService
from karuvottam.sensor_data import CSV_COLUMNS, StationDataError, StationDataService


def _csv(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


def _row(hour=1, **changes):
    row = {
        'observed_at_utc': f'2026-07-01T{hour:02d}:00:00Z',
        'recorded_at_utc': f'2026-07-01T{hour:02d}:05:00Z',
        'temperature_c': '28.1', 'relative_humidity_pct': '72',
        'precipitation_mm': '0.5', 'cloud_cover_pct': '80',
        'wind_speed_kmh': '6', 'wind_direction_deg': '250',
        'pressure_hpa': '1005',
        'precipitation_interval_start_utc': f'2026-07-01T{hour-1:02d}:00:00Z',
        'precipitation_interval_end_utc': f'2026-07-01T{hour:02d}:00:00Z',
        'precipitation_interval_minutes': '60',
    }
    row.update(changes)
    return row


def _setup(tmp_path):
    database = tmp_path / 'station.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    with access.transaction() as work:
        target = work.locations.add(
            name='Sensor site', latitude=10.5, longitude=78.2,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        other = work.locations.add(
            name='Other site', latitude=11.5, longitude=79.2,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
    service = StationDataService(access, tmp_path / 'raw')
    station = service.register(
        location_id=target.id, station_key='gauge-1', name='Village gauge',
        source_kind='iot', provider='Village committee',
        actor='operator', reason='Install sensor',
    )
    return database, access, service, target, other, station


def test_station_import_preserves_provenance_and_is_idempotent(tmp_path):
    database, access, service, target, other, station = _setup(tmp_path)
    payload = _csv([
        _row(1),
        _row(2, cloud_cover_pct=''),
        _row(3, pressure_hpa='700'),
        _row(4, precipitation_mm='2.0', precipitation_interval_minutes='30'),
    ])
    preview = service.preview_csv(payload, station_id=station.id)
    assert [row.quality_flag for row in preview.rows] == [
        'valid', 'missing', 'out_of_range', 'invalid_csv',
    ]
    assert preview.accepted_rows == 2
    assert preview.rejected_rows == 2
    assert preview.quality_report.missing_hours == ()
    first = service.import_csv(
        payload, station_id=station.id, actor='operator', reason='Daily upload',
    )
    second = service.import_csv(
        payload, station_id=station.id, actor='operator', reason='Retry upload',
    )
    assert (first.inserted_rows, first.rejected_rows) == (2, 2)
    assert (second.inserted_rows, second.existing_rows) == (0, 2)
    archive = tmp_path / 'raw' / first.raw_payload_reference
    assert archive.read_bytes() == payload
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == first.payload_sha256
    with access.transaction() as work:
        target_rows = work.weather_observations.list_between(
            target.id, datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            source='station:gauge-1',
        )
        other_rows = work.weather_observations.list_between(
            other.id, datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
        )
        reading = work.weather_stations.find_reading(
            station.id, datetime(2026, 7, 1, 1, tzinfo=timezone.utc),
        )
        audits = work.audit.list_recent()
    assert len(target_rows) == 2 and not other_rows
    assert target_rows[0].precipitation_interval_minutes == 60
    assert target_rows[0].raw_payload_reference == first.raw_payload_reference
    assert reading.observation_id == target_rows[0].id
    assert [item.action for item in audits] == [
        'station_weather_imported', 'station_registered',
    ]
    with connect_database(database) as connection:
        assert connection.execute('SELECT COUNT(*) FROM station_import_batches').fetchone()[0] == 1
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_conflicting_station_revision_rolls_back(tmp_path):
    _, access, service, target, _, station = _setup(tmp_path)
    service.import_csv(
        _csv([_row(1)]), station_id=station.id,
        actor='operator', reason='Initial reading',
    )
    with pytest.raises(DuplicateRecordError, match='revision conflicts'):
        service.import_csv(
            _csv([_row(1, precipitation_mm='9.0'), _row(2)]),
            station_id=station.id, actor='operator', reason='Changed reading',
        )
    with access.transaction() as work:
        rows = work.weather_observations.list_between(
            target.id, datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            source='station:gauge-1',
        )
    assert len(rows) == 1


def test_sensor_source_is_visible_to_observation_inspection(tmp_path):
    _, access, service, target, _, station = _setup(tmp_path)
    service.import_csv(
        _csv([_row(1)]), station_id=station.id,
        actor='operator', reason='Daily upload',
    )
    inspection = ObservationInspectionService(
        access, location_name=target.name, latitude=target.latitude,
        longitude=target.longitude, timezone_name=target.timezone_name,
    ).build(source='station:gauge-1')
    assert inspection.station == station
    assert inspection.selected_source == 'station:gauge-1'
    assert inspection.records[0].quality_flag == 'valid'


def test_station_contract_rejects_missing_interval_and_bad_identity(tmp_path):
    _, access, service, target, _, station = _setup(tmp_path)
    with pytest.raises(StationDataError, match='station_key'):
        service.register(
            location_id=target.id, station_key='bad key', name='Bad',
            source_kind='station', provider='Test', actor='operator', reason='Test',
        )
    with pytest.raises(ValueError, match='coordinates'):
        with access.transaction() as work:
            work.weather_stations.register(
                location_id=target.id, station_key='remote', name='Remote',
                source_kind='station', provider='Test', latitude=11,
                longitude=target.longitude, timezone_name=target.timezone_name,
            )
    preview = service.preview_csv(_csv([
        _row(1, precipitation_interval_start_utc=''),
    ]), station_id=station.id)
    assert preview.accepted_rows == 0
    assert 'rainfall requires' in preview.rows[0].issues[0]
