import io
import logging

import pytest

import app as app_module
from karuvottam.data_access import DataAccessError
from karuvottam.error_handling import REDACTED, RedactingFormatter, redact_text
from karuvottam.weather_client import WeatherTransportError


@pytest.fixture()
def client():
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as test_client:
        yield test_client


def test_redaction_covers_credentials_urls_and_bearer_headers():
    text = redact_text(
        'apikey=url-secret&token=token-secret Authorization: header-secret '
        'Bearer bearer-secret explicit-secret',
        secrets=('explicit-secret',),
    )

    assert text.count(REDACTED) == 5
    for secret in (
        'url-secret',
        'token-secret',
        'header-secret',
        'bearer-secret',
        'explicit-secret',
    ):
        assert secret not in text


def test_formatter_redacts_exception_traceback():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        RedactingFormatter('%(levelname)s %(message)s', secrets=('actual-key',))
    )
    logger = logging.getLogger('test.redacting-formatter')
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.ERROR)

    try:
        raise RuntimeError('failed URL ?apikey=actual-key')
    except RuntimeError:
        logger.exception('provider failed with actual-key')

    output = stream.getvalue()
    assert 'actual-key' not in output
    assert REDACTED in output


def test_application_handlers_are_redacting_and_do_not_propagate_unredacted():
    package_logger = logging.getLogger('karuvottam')

    assert app_module.app.logger.propagate is False
    assert package_logger.propagate is False
    assert app_module.app.logger.handlers
    assert package_logger.handlers
    assert all(
        isinstance(handler.formatter, RedactingFormatter)
        for logger in (app_module.app.logger, package_logger)
        for handler in logger.handlers
    )


def test_request_id_is_preserved_or_safely_generated(client):
    supplied = client.get('/', headers={'X-Request-ID': 'trace-123'})
    unsafe = client.get('/', headers={'X-Request-ID': 'bad id/value'})

    assert supplied.headers['X-Request-ID'] == 'trace-123'
    assert unsafe.headers['X-Request-ID'] != 'bad id/value'
    assert len(unsafe.headers['X-Request-ID']) == 32


@pytest.mark.parametrize(
    ('method', 'path', 'status', 'message'),
    [
        ('get', '/not-a-page', 404, 'கோரிய பக்கம் கிடைக்கவில்லை'),
        ('post', '/', 405, 'இந்தச் செயல் அனுமதிக்கப்படவில்லை'),
    ],
)
def test_http_errors_use_accessible_safe_page(client, method, path, status, message):
    response = getattr(client, method)(path)
    html = response.get_data(as_text=True)

    assert response.status_code == status
    assert message in html
    assert '<html lang="ta">' in html
    assert 'href="#main-content"' in html
    assert response.headers['X-Request-ID'] in html


@pytest.mark.parametrize(
    ('error', 'status', 'message'),
    [
        (
            DataAccessError('database password=private-db-value'),
            503,
            'தரவுச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை',
        ),
        (
            WeatherTransportError('apikey=private-weather-value'),
            503,
            'வானிலைச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை',
        ),
        (
            RuntimeError('secret=private-runtime-value'),
            500,
            'எதிர்பாராத பிழை ஏற்பட்டது',
        ),
    ],
)
def test_service_failures_return_safe_correlated_errors(
    client, monkeypatch, error, status, message
):
    class FailingDashboard:
        def build(self):
            raise error

    monkeypatch.setattr(
        app_module, 'STATUS_DASHBOARD_SERVICE', FailingDashboard()
    )
    response = client.get('/', headers={'X-Request-ID': 'failure-case-1'})
    html = response.get_data(as_text=True)

    assert response.status_code == status
    assert message in html
    assert 'failure-case-1' in html
    assert 'private-' not in html
    assert type(error).__name__ not in html
