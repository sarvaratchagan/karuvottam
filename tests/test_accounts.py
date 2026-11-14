import base64

import pytest

import app as app_module
from karuvottam.accounts import AccountStore, hash_password, verify_password
from karuvottam.database import migrate_database
from karuvottam.security import AdminAuthenticator


def basic(username, password):
    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return {'Authorization': f'Basic {token}'}


@pytest.fixture()
def accounts(tmp_path, monkeypatch):
    database = tmp_path / 'accounts.sqlite3'
    migrate_database(database)
    store = AccountStore(database)
    monkeypatch.setitem(app_module.app.extensions, 'account_store', store)
    monkeypatch.setitem(app_module.app.extensions, 'admin_authenticator',
                        AdminAuthenticator(None, None))
    return store


def test_passwords_are_salted_and_never_listed(accounts):
    password = 'long-test-password'
    first = hash_password(password)
    second = hash_password(password)
    assert first != second
    assert verify_password(password.encode(), first)
    assert not verify_password(b'wrong-password-long', first)
    accounts.create('viewer1', password, 'viewer')
    assert 'password_hash' not in accounts.list_accounts()[0]
    with pytest.raises(ValueError):
        accounts.create('VIEWER1', password, 'viewer')


@pytest.mark.parametrize('role,allowed', [
    ('admin', {'/workspace', '/workspace/research', '/workspace/data',
               '/workspace/accounts', '/admin'}),
    ('researcher', {'/workspace', '/workspace/research'}),
    ('data-maintainer', {'/workspace', '/workspace/data'}),
    ('viewer', {'/workspace'}),
])
def test_role_boundaries(accounts, role, allowed):
    accounts.create('testuser', 'long-test-password', role)
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        for path in ('/workspace', '/workspace/research', '/workspace/data',
                     '/workspace/accounts', '/admin'):
            response = client.get(path, headers=basic('testuser', 'long-test-password'))
            assert response.status_code == (200 if path in allowed else 403), path
            assert response.headers['Cache-Control'] == 'no-store'
        assert client.get('/workspace').status_code == 401


def test_password_rotation_disable_and_role_change(accounts):
    accounts.create('analyst', 'long-test-password', 'viewer')
    accounts.set_role('analyst', 'researcher')
    accounts.set_password('analyst', 'replacement-password')
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        assert client.get('/workspace/research',
                          headers=basic('analyst', 'long-test-password')).status_code == 401
        assert client.get('/workspace/research',
                          headers=basic('analyst', 'replacement-password')).status_code == 200
        accounts.set_enabled('analyst', False)
        assert client.get('/workspace/research',
                          headers=basic('analyst', 'replacement-password')).status_code == 401
        accounts.set_enabled('analyst', True)
        assert client.get('/workspace/research',
                          headers=basic('analyst', 'replacement-password')).status_code == 200


def test_environment_admin_remains_bootstrap(accounts, monkeypatch):
    monkeypatch.setitem(app_module.app.extensions, 'admin_authenticator',
                        AdminAuthenticator('bootstrap', 'long-test-password'))
    accounts.create('bootstrap', 'separate-password', 'viewer')
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        assert client.get('/admin',
                          headers=basic('bootstrap', 'long-test-password')).status_code == 200
        assert client.get('/admin',
                          headers=basic('bootstrap', 'separate-password')).status_code == 401


def test_protected_pages_use_shared_research_shell(accounts):
    accounts.create('shelladmin', 'long-test-password', 'admin')
    headers = basic('shelladmin', 'long-test-password')
    app_module.app.config.update(TESTING=True)

    with app_module.app.test_client() as client:
        workspace = client.get('/workspace', headers=headers).get_data(as_text=True)
        admin = client.get('/admin', headers=headers).get_data(as_text=True)

    assert 'class="research-page"' in workspace
    assert 'aria-current="page">பணியிடம்</a>' in workspace
    assert 'class="research-page"' in admin
    assert 'aria-current="page">நிர்வாகம்</a>' in admin
