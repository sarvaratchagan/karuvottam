"""Install/offline contract for the mobile web shell."""

import json
import struct

from app import app


PUBLIC_PAGES = (
    '/', '/calendar?year=2026', '/prediction?year=2026&mode=aadi',
    '/observations', '/events?year=2025', '/climate',
)


def png_size(payload):
    assert payload[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', payload[16:24])


def test_public_pages_advertise_installation():
    with app.test_client() as client:
        for path in PUBLIC_PAGES:
            response = client.get(path)
            assert response.status_code == 200, path
            html = response.get_data(as_text=True)
            assert '<link rel="manifest" href="/manifest.webmanifest">' in html
            assert '<script src="/static/pwa.js" defer></script>' in html
            assert 'apple-touch-icon.png' in html


def test_manifest_and_icons_are_installable_assets():
    with app.test_client() as client:
        response = client.get('/manifest.webmanifest')
        assert response.status_code == 200
        assert response.mimetype == 'application/manifest+json'
        manifest = json.loads(response.data)
        assert manifest['id'] == manifest['start_url'] == manifest['scope'] == '/'
        assert manifest['display'] == 'standalone'
        assert manifest['lang'] == 'ta'
        for icon in manifest['icons']:
            pixels = int(icon['sizes'].split('x')[0])
            assert png_size(client.get(icon['src']).data) == (pixels, pixels)
        assert {icon['sizes'] for icon in manifest['icons']} >= {'192x192', '512x512'}
        assert png_size(client.get('/static/icons/apple-touch-icon.png').data) == (180, 180)


def test_offline_shell_never_caches_forecast_or_private_pages():
    with app.test_client() as client:
        worker = client.get('/service-worker.js')
        assert worker.status_code == 200
        assert worker.mimetype == 'text/javascript'
        assert worker.headers['Cache-Control'] == 'no-cache'
        script = worker.get_data(as_text=True)
        assert "request.mode !== 'navigate'" in script
        assert "fetch(request, { cache: 'no-store' })" in script
        assert "caches.match('/static/offline.html')" in script
        assert "'/admin'" not in script
        assert "'/workspace'" not in script
        assert "'/prediction.csv'" not in script
        offline = client.get('/static/offline.html')
        assert offline.status_code == 200
        assert 'இணைய இணைப்பு இல்லை' in offline.get_data(as_text=True)
