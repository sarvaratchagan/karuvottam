"""Tamil/English selection and rendered UI contract."""

import base64
import json
import re

import pytest

from app import app
from karuvottam.security import AdminAuthenticator


@pytest.mark.parametrize('path,english_text', (
    ('/', 'Karuvottam | Rain research site'),
    ('/calendar?year=2026', 'Calendar'),
    ('/prediction?year=2026&mode=aadi', 'Aadi-based 180-day forecast'),
    ('/observations', 'Weather data inspection'),
    ('/events?year=2025', 'Weather Event Tracks'),
    ('/climate', 'Climate'),
))
def test_public_pages_render_in_english(path, english_text):
    separator = '&' if '?' in path else '?'
    with app.test_client() as client:
        response = client.get(f'{path}{separator}lang=en')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert response.headers['Content-Language'] == 'en'
    assert response.headers['Vary'] == 'Cookie'
    assert '<html lang="en">' in html
    assert english_text in html
    assert 'aria-label="Language"' in html
    assert 'lang="ta" hreflang="ta">தமிழ்</a>' in html
    assert 'lang="en" hreflang="en" aria-current="true"' in html


def test_language_choice_persists_and_preserves_query_filters():
    with app.test_client() as client:
        english = client.get('/prediction?year=2026&mode=margazhi&lang=en')
        assert 'karuvottam_lang=en' in english.headers['Set-Cookie']
        assert '/prediction?year=2026&amp;mode=margazhi&amp;lang=ta' in english.get_data(as_text=True)
        following = client.get('/calendar?year=2026')
        assert following.headers['Content-Language'] == 'en'
        assert '<html lang="en">' in following.get_data(as_text=True)
        tamil = client.get('/calendar?year=2026&lang=ta')
        assert tamil.headers['Content-Language'] == 'ta'
        assert '<html lang="ta">' in tamil.get_data(as_text=True)


def test_default_and_invalid_language_remain_tamil():
    with app.test_client() as client:
        for path in ('/', '/?lang=invalid'):
            response = client.get(path)
            assert response.headers['Content-Language'] == 'ta'
            assert '<html lang="ta">' in response.get_data(as_text=True)
        assert client.get('/?lang=invalid').headers.get('Set-Cookie') is None


@pytest.mark.parametrize('path,expected', (
    ('/?year=-1&lang=en', 'Year must be between 2015 and 2100'),
    ('/prediction?year=0&mode=unknown&view=unknown&lang=en',
     'Invalid Karuvottam type; Aadi was selected.'),
    ('/observations?start=bad&end=2026-01-01&lang=en',
     'Enter valid start and end dates'),
))
def test_invalid_inputs_explain_fallback_in_english(path, expected):
    with app.test_client() as client:
        response = client.get(path)
    assert response.status_code == 200
    assert expected in response.get_data(as_text=True)


def test_english_dynamic_dates_and_units_are_translated():
    with app.test_client() as client:
        home = client.get('/?year=2026&lang=en').get_data(as_text=True)
        calendar = client.get('/calendar?year=2026').get_data(as_text=True)
    assert re.search(r'Margazhi Karuvottam window · 2026', home)
    assert 'View 180-day forecast' in home
    assert 'Chithirai 1; rule version' in calendar
    assert 'source data' in calendar or 'Karuvottam' in calendar


def test_manifest_and_offline_shell_follow_selected_language():
    with app.test_client() as client:
        client.get('/?lang=en')
        manifest = client.get('/manifest.webmanifest')
        assert json.loads(manifest.data)['lang'] == 'en'
        assert manifest.headers['Content-Language'] == 'en'
        offline = client.get('/static/offline.html').get_data(as_text=True)
        assert '/static/offline-lang.js' in offline
        assert 'data-en="You are offline"' in offline
        worker = client.get('/service-worker.js').get_data(as_text=True)
        assert "'/static/offline-lang.js'" in worker


def test_error_page_uses_selected_language():
    with app.test_client() as client:
        response = client.get('/missing-page?lang=en')
    assert response.status_code == 404
    assert '<html lang="en">' in response.get_data(as_text=True)
    assert 'Return to home' in response.get_data(as_text=True)


@pytest.mark.parametrize('path', (
    '/workspace', '/workspace/research', '/workspace/data',
    '/workspace/accounts', '/admin',
))
def test_protected_pages_render_english(monkeypatch, path):
    monkeypatch.setitem(app.extensions, 'admin_authenticator',
                        AdminAuthenticator('locale-test', 'long-test-password'))
    credentials = base64.b64encode(b'locale-test:long-test-password').decode()
    with app.test_client() as client:
        response = client.get(f'{path}?lang=en',
                              headers={'Authorization': f'Basic {credentials}'})
    assert response.status_code == 200
    assert response.headers['Content-Language'] == 'en'
    assert '<html lang="en">' in response.get_data(as_text=True)
    assert 'aria-label="Language"' in response.get_data(as_text=True)
