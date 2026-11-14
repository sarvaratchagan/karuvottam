from datetime import datetime, timedelta, timezone

from karuvottam.database import migrate_database
from karuvottam.event_monitor import MonitorStore
from karuvottam.notifications import NotificationStore, deliver, process_due


def test_health_transition_delivery_and_retry(tmp_path):
    database = tmp_path / 'notifications.sqlite3'
    migrate_database(database)
    store = NotificationStore(database)
    monitor = MonitorStore(tmp_path / 'source_status.json')
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    store.add_rule('source_health', 'active', 'email', 'operator@example.org')
    store.add_rule('source_recovery', 'active', 'message')

    # Initial no-poll state is an actionable alert, but repeated scans are silent.
    assert store.scan(monitor, now=now) == 1
    assert store.scan(monitor, now=now + timedelta(minutes=1)) == 0
    assert len(store.deliveries()) == 1

    sent, failed = process_due(store, now=now,
        send=lambda item: (_ for _ in ()).throw(ConnectionError('offline')))
    assert (sent, failed) == (0, 1)
    delivery = store.deliveries()[0]
    assert delivery['status'] == 'failed'
    assert delivery['attempt_count'] == 1
    assert delivery['last_error_code'] == 'ConnectionError'
    assert process_due(store, now=now, send=lambda _: None) == (0, 0)

    store.retry(delivery['id'], now=now)
    assert process_due(store, now=now, send=lambda _: None) == (1, 0)
    assert store.deliveries()[0]['status'] == 'sent'
    assert store.deliveries()[0]['attempt_count'] == 2

    monitor.record('active', attempted_at=now, success={
        'last_retrieved_at': '2026-11-14T00:00:00Z',
        'last_digest': 'abc', 'last_usable_rows': 1,
        'last_skipped_rows': 0, 'last_missing_points': 0,
        'no_usable_rows': False, 'latest_period_end': None,
    })
    assert store.scan(monitor, now=now + timedelta(minutes=2)) == 1
    newest = store.deliveries()[0]
    assert newest['event_kind'] == 'source_recovery'
    assert newest['channel'] == 'message'
    assert process_due(store, now=now + timedelta(minutes=2),
                       send=lambda _: None) == (1, 0)


def test_rule_validation_and_disable(tmp_path):
    database = tmp_path / 'notifications.sqlite3'
    migrate_database(database)
    store = NotificationStore(database)
    import pytest
    with pytest.raises(ValueError):
        store.add_rule('source_health', 'all', 'email', 'Other <a@example.org>')
    with pytest.raises(ValueError):
        store.add_rule('source_health', 'all', 'message', 'https://example.org')
    rule_id = store.add_rule('source_health', 'all', 'email', 'a@example.org')
    assert store.add_rule('source_health', 'all', 'email', 'a@example.org') == rule_id
    store.set_rule_enabled(rule_id, False)
    assert store.rules()[0]['enabled'] == 0


def test_unconfigured_transport_is_recorded_without_network(tmp_path):
    database = tmp_path / 'notifications.sqlite3'
    migrate_database(database)
    store = NotificationStore(database)
    monitor = MonitorStore(tmp_path / 'source_status.json')
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    store.add_rule('source_health', 'active', 'message')
    assert store.scan(monitor, now=now) == 1
    assert process_due(store, now=now,
        send=lambda item: deliver(item, env={})) == (0, 1)
    assert store.deliveries()[0]['last_error_code'] == 'ValueError'


def test_new_rule_receives_current_unhealthy_state(tmp_path):
    database = tmp_path / 'notifications.sqlite3'
    migrate_database(database)
    store = NotificationStore(database)
    monitor = MonitorStore(tmp_path / 'source_status.json')
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    assert store.scan(monitor, now=now) == 0
    store.add_rule('source_health', 'dmi', 'email', 'operator@example.org')
    assert store.scan(monitor, now=now + timedelta(minutes=1)) == 1
    assert store.scan(monitor, now=now + timedelta(minutes=2)) == 0


def test_interrupted_sender_is_reclaimed_after_lease(tmp_path):
    database = tmp_path / 'notifications.sqlite3'
    migrate_database(database)
    store = NotificationStore(database)
    monitor = MonitorStore(tmp_path / 'source_status.json')
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    store.add_rule('source_health', 'oni', 'email', 'operator@example.org')
    assert store.scan(monitor, now=now) == 1
    first = store.claim(now=now)
    assert first is not None
    assert store.claim(now=now + timedelta(minutes=9)) is None
    second = store.claim(now=now + timedelta(minutes=10))
    assert second['id'] == first['id']
    store.finish(second['id'], now=now + timedelta(minutes=10))
    assert store.deliveries()[0]['attempt_count'] == 2
