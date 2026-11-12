import sqlite3

import app as app_module
from karuvottam.database import migrate_database
from karuvottam.health import database_is_ready
from wsgi import app as wsgi_app


def test_wsgi_entry_point_exposes_application():
    assert wsgi_app is app_module.app
    assert wsgi_app.debug is False


def test_readiness_requires_existing_current_database(tmp_path, monkeypatch):
    path = tmp_path / 'health.sqlite3'
    monkeypatch.setitem(app_module.app.config, 'DATABASE_PATH', str(path))
    with app_module.app.test_client() as client:
        live = client.get('/health/live')
        missing = client.get('/health/ready')
        assert live.status_code == 200
        assert live.json == {'status': 'ok'}
        assert missing.status_code == 503
        assert missing.json == {'status': 'unavailable'}
        assert not path.exists()  # Probe must not create a database.

        migrate_database(path)
        ready = client.get('/health/ready')
        assert ready.status_code == 200
        assert ready.json == {'status': 'ready'}
        assert ready.headers['X-Request-ID']

        with sqlite3.connect(path) as connection:
            connection.execute('DELETE FROM schema_migrations WHERE version = 5')
        stale = client.get('/health/ready')
        assert stale.status_code == 503
        assert stale.json == {'status': 'unavailable'}


def test_readiness_rejects_invalid_database(tmp_path):
    path = tmp_path / 'broken.sqlite3'
    path.write_bytes(b'not a sqlite database')
    assert database_is_ready(path) is False
