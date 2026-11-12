import base64

import pytest

import app as app_module
from karuvottam.security import AdminAuthenticator, query_parameters_are_safe


def _basic(username: str, password: str) -> str:
    encoded = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return f'Basic {encoded}'


@pytest.fixture()
def client():
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def configured_admin(monkeypatch):
    authenticator = AdminAuthenticator('administrator', 'long-test-password')
    monkeypatch.setitem(
        app_module.app.extensions, 'admin_authenticator', authenticator
    )
    return authenticator


@pytest.mark.parametrize(
    'header',
    [
        None,
        '',
        'Bearer token',
        'Basic not-base64!',
        _basic('administrator', 'wrong-password'),
        _basic('wrong-user', 'long-test-password'),
        'Basic ' + ('A' * 2048),
    ],
)
def test_admin_authenticator_rejects_invalid_credentials(header):
    authenticator = AdminAuthenticator('administrator', 'long-test-password')

    assert authenticator.authenticate(header) is False


def test_admin_authenticator_accepts_exact_credentials_and_hides_repr():
    authenticator = AdminAuthenticator('administrator', 'long-test-password')

    assert authenticator.authenticate(
        _basic('administrator', 'long-test-password')
    )
    assert 'long-test-password' not in repr(authenticator)


def test_admin_route_is_closed_when_credentials_are_not_configured(
    client, monkeypatch
):
    monkeypatch.setitem(
        app_module.app.extensions,
        'admin_authenticator',
        AdminAuthenticator(None, None),
    )

    response = client.get('/admin')

    assert response.status_code == 503
    assert 'நிர்வாக அணுகல் அமைக்கப்படவில்லை' in response.get_data(as_text=True)
    assert 'WWW-Authenticate' not in response.headers
    assert response.headers['Cache-Control'] == 'no-store'


def test_admin_route_challenges_missing_or_wrong_credentials(
    client, configured_admin
):
    missing = client.get('/admin')
    wrong = client.get(
        '/admin',
        headers={'Authorization': _basic('administrator', 'wrong-password')},
    )

    for response in (missing, wrong):
        assert response.status_code == 401
        assert 'நிர்வாக அங்கீகாரம் தேவை' in response.get_data(as_text=True)
        assert response.headers['WWW-Authenticate'].startswith('Basic realm=')
        assert response.headers['Cache-Control'] == 'no-store'


def test_authenticated_admin_page_is_accessible_and_omits_secrets(
    client, configured_admin
):
    response = client.get(
        '/admin',
        headers={
            'Authorization': _basic('administrator', 'long-test-password')
        },
    )
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'நிர்வாக நிலை' in html
    assert '<html lang="ta">' in html
    assert 'href="#main-content"' in html
    assert html.count('<h1>') == 1
    assert 'long-test-password' not in html
    if app_module.settings.weather_api_key:
        assert app_module.settings.weather_api_key not in html


@pytest.mark.parametrize(
    'path',
    [
        '/?year=2026&year=2027',
        '/observations?source=' + ('x' * 257),
        '/?bad=%00value',
    ],
)
def test_ambiguous_or_abusive_query_parameters_are_rejected(client, path):
    response = client.get(path)

    assert response.status_code == 400
    assert 'கோரிக்கையை நிறைவேற்ற முடியவில்லை' in response.get_data(as_text=True)


def test_query_validator_accepts_normal_unicode_values():
    assert query_parameters_are_safe(
        'source=தமிழ்'.encode(),
        [('source', ['தமிழ்'])],
    )


def test_all_responses_include_security_headers(client):
    response = client.get('/')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert app_module.app.debug is False
