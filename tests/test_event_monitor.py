import csv
import io
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

import app as app_module
from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.event_monitor import MonitorStore, poll


NOW = datetime(2026, 11, 8, 6, tzinfo=timezone.utc)


def _active_csv(*, missing_point=False):
    stream = io.StringIO(newline='')
    fields = ['SID', 'BASIN', 'ISO_TIME', 'LAT', 'LON', 'TRACK_TYPE',
              'NEWDELHI_GRADE', 'USA_STATUS']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({})
    writer.writerow({'SID': '2026312N12080', 'BASIN': 'NI',
                     'ISO_TIME': '2026-11-08 00:00:00',
                     'LAT': '' if missing_point else '12',
                     'LON': '80', 'TRACK_TYPE': 'PROVISIONAL',
                     'NEWDELHI_GRADE': 'D'})
    return stream.getvalue().encode()


def test_monitor_preserves_last_good_import_after_rate_limit(tmp_path, monkeypatch):
    database = tmp_path / 'events.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    store = MonitorStore(tmp_path / 'monitor' / 'source_status.json')
    monkeypatch.setattr('karuvottam.event_monitor.fetch_dataset',
                        lambda dataset, archive: _active_csv())
    first = poll('active', access, store, archive_root=tmp_path / 'imports', now=NOW)
    assert first.health == 'ok'
    assert first.last_usable_rows == 1
    assert first.last_digest
    assert first.last_retrieved_at == '2026-11-08T06:00:00Z'
    with access.transaction() as work:
        assert work.weather_events.latest_year('noaa:ibtracs:v04r01') == 2026

    def limited(dataset, archive):
        raise RuntimeError('download failed') from HTTPError(
            'https://example.invalid', 429, 'rate limited', {}, None,
        )

    monkeypatch.setattr('karuvottam.event_monitor.fetch_dataset', limited)
    second = poll('active', access, store, archive_root=tmp_path / 'imports',
                  now=NOW + timedelta(hours=1))
    assert second.health == 'last_attempt_failed'
    assert second.last_error_code == 'rate_limited'
    assert second.last_success_at == first.last_success_at
    assert second.last_digest == first.last_digest
    assert second.last_attempt_at != first.last_attempt_at


def test_monitor_detects_overdue_poll_and_stale_index(tmp_path, monkeypatch):
    database = tmp_path / 'climate.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    store = MonitorStore(tmp_path / 'source_status.json')
    dmi = b'Date,DMI\n2026-10-01,0.3\n'
    monkeypatch.setattr('karuvottam.event_monitor.fetch_source',
                        lambda source: (dmi, NOW, NOW, 'http_last_modified'))
    fresh = poll('dmi', access, store, archive_root=tmp_path / 'imports', now=NOW)
    assert fresh.health == 'ok'
    assert fresh.latest_period_end == '2026-10-31'
    assert next(item for item in store.statuses(now=NOW + timedelta(days=46))
                if item.source == 'dmi').health == 'poll_overdue'
    store.record('oni', attempted_at=NOW, success={
        'last_retrieved_at': '2026-11-08T06:00:00Z',
        'latest_period_end': '2026-01-31', 'last_digest': 'a' * 64,
        'last_usable_rows': 1, 'last_skipped_rows': 0,
        'no_usable_rows': False,
    })
    assert next(item for item in store.statuses(now=NOW)
                if item.source == 'oni').health == 'index_stale'


def test_monitor_distinguishes_empty_active_feed_and_page_status(tmp_path, monkeypatch):
    database = tmp_path / 'events.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    store = MonitorStore(tmp_path / 'source_status.json')
    monkeypatch.setattr('karuvottam.event_monitor.fetch_dataset',
                        lambda dataset, archive: _active_csv().splitlines(keepends=True)[:2][0]
                        + _active_csv().splitlines(keepends=True)[:2][1])
    result = poll('active', access, store, archive_root=tmp_path / 'imports', now=NOW)
    assert result.health == 'ok'
    assert result.no_usable_rows
    assert result.last_usable_rows == 0
    monkeypatch.setitem(app_module.app.extensions, 'source_monitor_store', store)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        html = client.get('/events?year=2026').get_data(as_text=True)
    assert 'கடைசி active கோப்பில் பயன்படும்' in html
    assert '2026-11-08T06:00:00Z' in html


def test_monitor_counts_missing_track_coordinates(tmp_path, monkeypatch):
    database = tmp_path / 'events.sqlite3'
    migrate_database(database)
    store = MonitorStore(tmp_path / 'source_status.json')
    monkeypatch.setattr('karuvottam.event_monitor.fetch_dataset',
                        lambda dataset, archive: _active_csv(missing_point=True))
    result = poll('active', DataAccess(database), store,
                  archive_root=tmp_path / 'imports', now=NOW)
    assert result.health == 'ok'
    assert result.last_missing_points == 1
    assert result.last_usable_rows == 0


def test_corrupt_monitor_state_is_unavailable(tmp_path):
    store = MonitorStore(tmp_path / 'source_status.json')
    store.path.write_text('{broken')
    assert {item.health for item in store.statuses(now=NOW)} == {'state_unavailable'}


def test_first_failed_poll_is_reported_as_failure(tmp_path, monkeypatch):
    database = tmp_path / 'events.sqlite3'
    migrate_database(database)
    store = MonitorStore(tmp_path / 'source_status.json')

    def offline(dataset, archive):
        raise RuntimeError('download failed') from ConnectionError('offline')

    monkeypatch.setattr('karuvottam.event_monitor.fetch_dataset', offline)
    result = poll('active', DataAccess(database), store,
                  archive_root=tmp_path / 'imports', now=NOW)
    assert result.health == 'last_attempt_failed'
    assert result.last_error_code == 'network_error'
    assert result.last_success_at is None
