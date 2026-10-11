import json
from datetime import date, datetime, timezone
import pytest

from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.weather_client import (
    HttpResponse,
    OpenMeteoHistoricalClient,
    RawWeatherPayloadStore,
    WeatherIngestionService,
    WeatherRateLimitError,
    WeatherResponseError,
    WeatherTransportError,
)
from karuvottam.weather_provider import EXPECTED_HOURLY_UNITS, OPEN_METEO_ERA5


FIXED_NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def _payload(*, unit_overrides=None, array_overrides=None) -> bytes:
    units = dict(EXPECTED_HOURLY_UNITS)
    units.update(unit_overrides or {})
    hourly = {
        'time': ['2025-07-01T00:00', '2025-07-01T01:00'],
        'temperature_2m': [27.0, 27.5],
        'relative_humidity_2m': [72, 70],
        'precipitation': [0.0, 0.2],
        'cloud_cover': [95, 96],
        'wind_speed_10m': [3.9, 4.2],
        'wind_direction_10m': [254, 250],
        'pressure_msl': [1007.7, 1007.9],
    }
    hourly.update(array_overrides or {})
    return json.dumps(
        {
            'latitude': 10.0,
            'longitude': 78.0,
            'elevation': 157.0,
            'utc_offset_seconds': 0,
            'timezone': 'GMT',
            'hourly_units': units,
            'hourly': hourly,
        },
        separators=(',', ':'),
    ).encode()


class FakeTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def get(self, base_url, parameters, timeout_seconds):
        self.calls.append((base_url, tuple(parameters), timeout_seconds))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(status=200, body=None, headers=None):
    return HttpResponse(
        status_code=status,
        body=_payload() if body is None else body,
        headers=headers or {},
        url='https://archive-api.open-meteo.com/v1/archive?test=1',
    )


def _client(transport, *, sleep=lambda _seconds: None, max_attempts=3, api_key=None):
    return OpenMeteoHistoricalClient(
        OPEN_METEO_ERA5,
        api_key=api_key,
        timeout_seconds=7,
        max_attempts=max_attempts,
        retry_backoff_seconds=1,
        transport=transport,
        sleep=sleep,
        now=lambda: FIXED_NOW,
    )


def _fetch(client):
    return client.fetch(
        latitude=9.9040188,
        longitude=77.8860417,
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 2),
    )


def test_fetch_uses_pinned_contract_and_keeps_api_key_out_of_provenance():
    transport = FakeTransport([_response()])

    fetched = _fetch(_client(transport, api_key='secret-key'))

    _, parameters, timeout = transport.calls[0]
    request_parameters = dict(parameters)
    assert timeout == 7
    assert request_parameters['models'] == 'era5'
    assert request_parameters['timezone'] == 'UTC'
    assert request_parameters['hourly'] == ','.join(OPEN_METEO_ERA5.hourly_variables)
    assert request_parameters['apikey'] == 'secret-key'
    assert 'secret-key' not in fetched.requested_url
    assert fetched.returned_latitude == 10.0
    assert fetched.returned_longitude == 78.0
    assert fetched.returned_elevation_m == 157.0
    assert len(fetched.hourly['time']) == 2
    assert len(fetched.payload_sha256) == 64


def test_rate_and_server_errors_retry_with_retry_after_and_backoff():
    transport = FakeTransport(
        [
            _response(429, b'{"error":true}', {'Retry-After': '2.5'}),
            _response(503, b'busy'),
            _response(),
        ]
    )
    delays = []

    fetched = _fetch(_client(transport, sleep=delays.append))

    assert len(fetched.hourly['time']) == 2
    assert delays == [2.5, 2]
    assert len(transport.calls) == 3


def test_rate_limit_exhaustion_raises_specific_error():
    transport = FakeTransport(
        [_response(429, b'busy'), _response(429, b'busy')]
    )

    with pytest.raises(WeatherRateLimitError, match='2 attempts'):
        _fetch(_client(transport, max_attempts=2))


def test_non_retriable_provider_error_includes_safe_reason():
    transport = FakeTransport(
        [_response(400, b'{"error":true,"reason":"invalid date"}')]
    )

    with pytest.raises(WeatherResponseError, match='invalid date'):
        _fetch(_client(transport))

    assert len(transport.calls) == 1


def test_transport_error_retries_then_reports_exhaustion():
    transport = FakeTransport(
        [WeatherTransportError('offline'), WeatherTransportError('offline')]
    )

    with pytest.raises(WeatherTransportError, match='after 2 attempts'):
        _fetch(_client(transport, max_attempts=2))


@pytest.mark.parametrize(
    'body, message',
    [
        (b'not-json', 'invalid JSON'),
        (_payload(unit_overrides={'precipitation': 'inch'}), 'unexpected unit'),
        (
            _payload(array_overrides={'cloud_cover': [95]}),
            'different lengths',
        ),
    ],
)
def test_invalid_provider_contract_is_rejected(body, message):
    transport = FakeTransport([_response(body=body)])

    with pytest.raises(WeatherResponseError, match=message):
        _fetch(_client(transport))


def test_raw_payload_store_is_content_addressed_and_idempotent(tmp_path):
    fetched = _fetch(_client(FakeTransport([_response()])))
    store = RawWeatherPayloadStore(tmp_path / 'raw')

    first = store.save(fetched)
    second = store.save(fetched)

    assert first.created is True
    assert second.created is False
    assert first.reference == second.reference
    assert first.payload_path.read_bytes() == fetched.raw_payload
    metadata = json.loads(first.metadata_path.read_text(encoding='utf-8'))
    assert metadata['payload_sha256'] == fetched.payload_sha256
    assert metadata['requested_url'] == fetched.requested_url


def test_ingestion_is_idempotent_and_retains_raw_reference(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9040188,
            longitude=77.8860417,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )

    client = _client(FakeTransport([_response(), _response()]))
    service = WeatherIngestionService(
        client,
        data_access,
        RawWeatherPayloadStore(tmp_path / 'raw'),
    )
    request = {
        'location_id': location.id,
        'latitude': location.latitude,
        'longitude': location.longitude,
        'start_date': date(2025, 7, 1),
        'end_date': date(2025, 7, 2),
    }

    first = service.ingest(**request)
    second = service.ingest(**request)

    assert first.fetched_hours == 2
    assert first.inserted_hours == 2
    assert first.existing_hours == 0
    assert second.inserted_hours == 0
    assert second.existing_hours == 2
    assert first.raw_payload_reference == second.raw_payload_reference
    with data_access.transaction() as work:
        records = work.weather_observations.list_between(
            location.id,
            datetime(2025, 7, 1, tzinfo=timezone.utc),
            datetime(2025, 7, 2, tzinfo=timezone.utc),
        )
    assert len(records) == 2
    assert all(
        record.raw_payload_reference == first.raw_payload_reference
        for record in records
    )
    assert records[0].observed_at_local == '2025-07-01T05:30:00+05:30'
    assert records[0].observed_at_utc == '2025-07-01T00:00:00Z'
    assert (
        records[0].precipitation_interval_start_utc
        == '2025-06-30T23:00:00Z'
    )
    assert records[0].precipitation_interval_end_utc == '2025-07-01T00:00:00Z'
    assert records[0].precipitation_interval_minutes == 60
    assert records[0].quality_flag == 'unvalidated_reanalysis'


@pytest.mark.parametrize(
    'timestamps, message',
    [
        (['2025-07-01T00:30', '2025-07-01T01:30'], 'exact hour'),
        (['2025-07-01T00:00+05:30', '2025-07-01T01:00+05:30'], 'must be UTC'),
        (['2025-07-01T00:00', '2025-07-01T02:00'], 'consecutive'),
        (['2025-07-01T00:00', '2025-07-01T00:00'], 'consecutive'),
    ],
)
def test_provider_hour_labels_must_be_consecutive_exact_utc_hours(
    timestamps, message
):
    transport = FakeTransport(
        [_response(body=_payload(array_overrides={'time': timestamps}))]
    )

    with pytest.raises(WeatherResponseError, match=message):
        _fetch(_client(transport))


def test_local_timestamp_uses_the_persisted_location_timezone(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Target',
            latitude=9.9040188,
            longitude=77.8860417,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
    body = _payload(
        array_overrides={
            'time': ['2025-06-30T18:00Z', '2025-06-30T19:00Z'],
        }
    )
    service = WeatherIngestionService(
        _client(FakeTransport([_response(body=body)])),
        data_access,
        RawWeatherPayloadStore(tmp_path / 'raw'),
    )

    service.ingest(
        location_id=location.id,
        latitude=location.latitude,
        longitude=location.longitude,
        start_date=date(2025, 7, 1),
        end_date=date(2025, 7, 2),
    )

    with data_access.transaction() as work:
        records = work.weather_observations.list_between(
            location.id,
            datetime(2025, 6, 30, 18, tzinfo=timezone.utc),
            datetime(2025, 6, 30, 19, tzinfo=timezone.utc),
        )
    assert [record.observed_at_local for record in records] == [
        '2025-06-30T23:30:00+05:30',
        '2025-07-01T00:30:00+05:30',
    ]


def test_request_rejects_dates_outside_expected_era5_availability():
    client = _client(FakeTransport([]))

    with pytest.raises(ValueError, match='coverage'):
        client.fetch(
            latitude=10,
            longitude=78,
            start_date=date(1939, 12, 31),
            end_date=date(1940, 1, 1),
        )
    with pytest.raises(ValueError, match='latest expected'):
        client.fetch(
            latitude=10,
            longitude=78,
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 6),
        )
