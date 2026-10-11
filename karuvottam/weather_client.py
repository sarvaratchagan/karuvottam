"""Open-Meteo ERA5 retrieval, raw archival, and idempotent ingestion."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

import certifi

from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.weather_provider import HistoricalWeatherProvider


RETRIABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_DELAY_SECONDS = 60.0


class WeatherClientError(RuntimeError):
    """Base error for historical weather retrieval."""


class WeatherTransportError(WeatherClientError):
    """Raised when the provider cannot be reached."""


class WeatherRateLimitError(WeatherClientError):
    """Raised after provider throttling exhausts retry attempts."""


class WeatherResponseError(WeatherClientError):
    """Raised when a provider response violates the selected contract."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]
    url: str


class WeatherTransport(Protocol):
    def get(
        self,
        base_url: str,
        parameters: Sequence[tuple[str, str]],
        timeout_seconds: float,
    ) -> HttpResponse: ...


class UrllibWeatherTransport:
    """Small standard-library HTTP adapter that remains replaceable in tests."""

    def __init__(self) -> None:
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def get(
        self,
        base_url: str,
        parameters: Sequence[tuple[str, str]],
        timeout_seconds: float,
    ) -> HttpResponse:
        url = f'{base_url}?{urlencode(parameters)}'
        request = Request(
            url,
            headers={
                'Accept': 'application/json',
                'User-Agent': 'karuvottam-research/1.0',
            },
        )
        try:
            with urlopen(
                request,
                timeout=timeout_seconds,
                context=self.ssl_context,
            ) as response:
                return HttpResponse(
                    status_code=response.status,
                    body=response.read(),
                    headers=dict(response.headers.items()),
                    url=response.geturl(),
                )
        except HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                body=exc.read(),
                headers=dict(exc.headers.items()) if exc.headers else {},
                url=url,
            )
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise WeatherTransportError('historical weather request failed') from exc


@dataclass(frozen=True)
class WeatherFetch:
    provider_key: str
    model: str
    requested_url: str
    requested_latitude: float
    requested_longitude: float
    start_date: date
    end_date: date
    retrieved_at_utc: datetime
    returned_latitude: float
    returned_longitude: float
    returned_elevation_m: float | None
    timezone_name: str
    utc_offset_seconds: int
    hourly_units: Mapping[str, str]
    hourly: Mapping[str, list[object]]
    raw_payload: bytes
    payload_sha256: str


@dataclass(frozen=True)
class RawPayloadArtifact:
    reference: str
    payload_path: Path
    metadata_path: Path
    created: bool


@dataclass(frozen=True)
class WeatherIngestionReport:
    fetched_hours: int
    inserted_hours: int
    existing_hours: int
    raw_payload_reference: str
    payload_sha256: str
    returned_latitude: float
    returned_longitude: float
    returned_elevation_m: float | None


def _json_error_reason(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get('reason'), str):
        return payload['reason']
    return None


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw_value = next(
        (value for key, value in headers.items() if key.lower() == 'retry-after'),
        None,
    )
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except ValueError:
        return None
    return max(0.0, min(value, MAX_RETRY_DELAY_SECONDS))


class OpenMeteoHistoricalClient:
    def __init__(
        self,
        provider: HistoricalWeatherProvider,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 30,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1,
        transport: WeatherTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError('timeout_seconds must be greater than zero')
        if max_attempts < 1:
            raise ValueError('max_attempts must be at least 1')
        if retry_backoff_seconds < 0:
            raise ValueError('retry_backoff_seconds must not be negative')
        self.provider = provider
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.transport = transport or UrllibWeatherTransport()
        self.sleep = sleep
        self.now = now

    def fetch(
        self,
        *,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> WeatherFetch:
        self._validate_request(latitude, longitude, start_date, end_date)
        public_parameters = self._request_parameters(
            latitude, longitude, start_date, end_date
        )
        transport_parameters = list(public_parameters)
        if self.api_key:
            transport_parameters.append(('apikey', self.api_key))

        response: HttpResponse | None = None
        last_transport_error: WeatherTransportError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.transport.get(
                    self.provider.base_url,
                    transport_parameters,
                    self.timeout_seconds,
                )
            except WeatherTransportError as exc:
                last_transport_error = exc
                if attempt == self.max_attempts:
                    raise WeatherTransportError(
                        f'historical weather request failed after {attempt} attempts'
                    ) from exc
                self.sleep(self._backoff_delay(attempt, None))
                continue

            if response.status_code == 200:
                break
            if response.status_code not in RETRIABLE_STATUS_CODES:
                reason = _json_error_reason(response.body)
                detail = f': {reason}' if reason else ''
                raise WeatherResponseError(
                    f'provider returned HTTP {response.status_code}{detail}'
                )
            if attempt == self.max_attempts:
                if response.status_code == 429:
                    raise WeatherRateLimitError(
                        f'provider rate limit persisted for {attempt} attempts'
                    )
                raise WeatherTransportError(
                    f'provider returned HTTP {response.status_code} for {attempt} attempts'
                )
            self.sleep(self._backoff_delay(attempt, response.headers))

        if response is None:
            raise WeatherTransportError('historical weather request failed') from last_transport_error
        return self._parse_response(
            response.body,
            public_parameters,
            latitude,
            longitude,
            start_date,
            end_date,
        )

    def _validate_request(
        self,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> None:
        if not -90 <= latitude <= 90:
            raise ValueError('latitude must be between -90 and 90')
        if not -180 <= longitude <= 180:
            raise ValueError('longitude must be between -180 and 180')
        if end_date < start_date:
            raise ValueError('end_date must not precede start_date')
        if start_date < self.provider.coverage_start:
            raise ValueError(
                f'start_date precedes provider coverage: {self.provider.coverage_start}'
            )
        current = self.now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError('now() must return a timezone-aware datetime')
        latest_available = current.astimezone(timezone.utc).date() - timedelta(
            days=self.provider.update_delay_days
        )
        if end_date > latest_available:
            raise ValueError(
                f'end_date exceeds latest expected ERA5 date: {latest_available}'
            )

    def _request_parameters(
        self,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> list[tuple[str, str]]:
        return [
            ('latitude', str(latitude)),
            ('longitude', str(longitude)),
            ('start_date', start_date.isoformat()),
            ('end_date', end_date.isoformat()),
            ('hourly', ','.join(self.provider.hourly_variables)),
            ('timezone', self.provider.request_timezone),
            ('models', self.provider.model),
            ('temperature_unit', 'celsius'),
            ('wind_speed_unit', 'kmh'),
            ('precipitation_unit', 'mm'),
        ]

    def _backoff_delay(
        self,
        attempt: int,
        headers: Mapping[str, str] | None,
    ) -> float:
        retry_after = _retry_after_seconds(headers or {})
        if retry_after is not None:
            return retry_after
        return min(
            self.retry_backoff_seconds * (2 ** (attempt - 1)),
            MAX_RETRY_DELAY_SECONDS,
        )

    def _parse_response(
        self,
        body: bytes,
        public_parameters: Sequence[tuple[str, str]],
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> WeatherFetch:
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeatherResponseError('provider returned invalid JSON') from exc
        if not isinstance(payload, dict):
            raise WeatherResponseError('provider response must be a JSON object')
        if payload.get('error'):
            raise WeatherResponseError(
                f"provider error: {payload.get('reason', 'unknown reason')}"
            )

        try:
            hourly = payload['hourly']
            units = payload['hourly_units']
            returned_latitude = float(payload['latitude'])
            returned_longitude = float(payload['longitude'])
            utc_offset_seconds = int(payload['utc_offset_seconds'])
            timezone_name = str(payload['timezone'])
        except (KeyError, TypeError, ValueError) as exc:
            raise WeatherResponseError('provider response metadata is incomplete') from exc
        if not isinstance(hourly, dict) or not isinstance(units, dict):
            raise WeatherResponseError('provider hourly data or units are invalid')
        if utc_offset_seconds != 0:
            raise WeatherResponseError('provider did not return UTC data')

        expected_length: int | None = None
        for key, expected_unit in self.provider.expected_units.items():
            if units.get(key) != expected_unit:
                raise WeatherResponseError(
                    f'unexpected unit for {key}: {units.get(key)!r}'
                )
            values = hourly.get(key)
            if not isinstance(values, list):
                raise WeatherResponseError(f'missing hourly array: {key}')
            if expected_length is None:
                expected_length = len(values)
            elif len(values) != expected_length:
                raise WeatherResponseError('hourly arrays have different lengths')
        if not expected_length:
            raise WeatherResponseError('provider returned no hourly records')

        retrieved_at = self.now().astimezone(timezone.utc)
        digest = hashlib.sha256(body).hexdigest()
        sanitized_url = f'{self.provider.base_url}?{urlencode(public_parameters)}'
        elevation = payload.get('elevation')
        return WeatherFetch(
            provider_key=self.provider.key,
            model=self.provider.model,
            requested_url=sanitized_url,
            requested_latitude=latitude,
            requested_longitude=longitude,
            start_date=start_date,
            end_date=end_date,
            retrieved_at_utc=retrieved_at,
            returned_latitude=returned_latitude,
            returned_longitude=returned_longitude,
            returned_elevation_m=None if elevation is None else float(elevation),
            timezone_name=timezone_name,
            utc_offset_seconds=utc_offset_seconds,
            hourly_units=units,
            hourly=hourly,
            raw_payload=body,
            payload_sha256=digest,
        )


class RawWeatherPayloadStore:
    """Keep exact provider responses under stable content-addressed references."""

    def __init__(self, root_directory: str | Path) -> None:
        self.root_directory = Path(root_directory)

    def save(self, fetched: WeatherFetch) -> RawPayloadArtifact:
        relative = Path(fetched.provider_key) / fetched.model
        directory = self.root_directory / relative
        directory.mkdir(parents=True, exist_ok=True)
        payload_path = directory / f'{fetched.payload_sha256}.json'
        metadata_path = directory / f'{fetched.payload_sha256}.metadata.json'
        reference = (relative / payload_path.name).as_posix()

        metadata = {
            'provider': fetched.provider_key,
            'model': fetched.model,
            'requested_url': fetched.requested_url,
            'requested_latitude': fetched.requested_latitude,
            'requested_longitude': fetched.requested_longitude,
            'returned_latitude': fetched.returned_latitude,
            'returned_longitude': fetched.returned_longitude,
            'returned_elevation_m': fetched.returned_elevation_m,
            'start_date': fetched.start_date.isoformat(),
            'end_date': fetched.end_date.isoformat(),
            'retrieved_at_utc': fetched.retrieved_at_utc.isoformat(),
            'payload_sha256': fetched.payload_sha256,
        }
        metadata_bytes = (
            json.dumps(metadata, ensure_ascii=False, indent=2) + '\n'
        ).encode('utf-8')

        if payload_path.exists():
            if hashlib.sha256(payload_path.read_bytes()).hexdigest() != fetched.payload_sha256:
                raise WeatherResponseError('raw payload checksum collision')
            if not metadata_path.exists():
                self._write_atomically(metadata_path, metadata_bytes)
            return RawPayloadArtifact(reference, payload_path, metadata_path, False)

        temporary_payload = directory / f'.{uuid4().hex}.payload.tmp'
        temporary_metadata = directory / f'.{uuid4().hex}.metadata.tmp'
        try:
            temporary_payload.write_bytes(fetched.raw_payload)
            temporary_metadata.write_bytes(metadata_bytes)
            os.replace(temporary_metadata, metadata_path)
            os.replace(temporary_payload, payload_path)
        finally:
            temporary_payload.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)
        return RawPayloadArtifact(reference, payload_path, metadata_path, True)

    @staticmethod
    def _write_atomically(path: Path, content: bytes) -> None:
        temporary = path.parent / f'.{uuid4().hex}.tmp'
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


class WeatherIngestionService:
    def __init__(
        self,
        client: OpenMeteoHistoricalClient,
        data_access: DataAccess,
        raw_store: RawWeatherPayloadStore,
        local_timezone: ZoneInfo,
    ) -> None:
        self.client = client
        self.data_access = data_access
        self.raw_store = raw_store
        self.local_timezone = local_timezone

    def ingest(
        self,
        *,
        location_id: int,
        latitude: float,
        longitude: float,
        start_date: date,
        end_date: date,
    ) -> WeatherIngestionReport:
        fetched = self.client.fetch(
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
        )
        artifact = self.raw_store.save(fetched)
        observations = self._observations(fetched, location_id, artifact.reference)
        inserted = 0
        existing = 0
        with self.data_access.transaction() as work:
            if work.locations.get(location_id) is None:
                raise ValueError(f'unknown location_id: {location_id}')
            for observation in observations:
                _, created = work.weather_observations.add_if_absent(observation)
                if created:
                    inserted += 1
                else:
                    existing += 1
        return WeatherIngestionReport(
            fetched_hours=len(observations),
            inserted_hours=inserted,
            existing_hours=existing,
            raw_payload_reference=artifact.reference,
            payload_sha256=fetched.payload_sha256,
            returned_latitude=fetched.returned_latitude,
            returned_longitude=fetched.returned_longitude,
            returned_elevation_m=fetched.returned_elevation_m,
        )

    def _observations(
        self,
        fetched: WeatherFetch,
        location_id: int,
        raw_payload_reference: str,
    ) -> tuple[WeatherObservation, ...]:
        hourly = fetched.hourly
        source = f'{fetched.provider_key}:{fetched.model}'
        observations = []
        for index, timestamp in enumerate(hourly['time']):
            if not isinstance(timestamp, str):
                raise WeatherResponseError('hourly timestamp must be a string')
            try:
                observed_utc = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError as exc:
                raise WeatherResponseError(
                    f'invalid hourly timestamp: {timestamp!r}'
                ) from exc
            if observed_utc.tzinfo is None:
                observed_utc = observed_utc.replace(tzinfo=timezone.utc)
            observed_utc = observed_utc.astimezone(timezone.utc)
            observations.append(
                WeatherObservation(
                    location_id=location_id,
                    observed_at_utc=observed_utc,
                    observed_at_local=observed_utc.astimezone(self.local_timezone),
                    temperature_c=hourly['temperature_2m'][index],
                    relative_humidity_pct=hourly['relative_humidity_2m'][index],
                    precipitation_mm=hourly['precipitation'][index],
                    cloud_cover_pct=hourly['cloud_cover'][index],
                    wind_speed_kmh=hourly['wind_speed_10m'][index],
                    wind_direction_deg=hourly['wind_direction_10m'][index],
                    pressure_hpa=hourly['pressure_msl'][index],
                    source=source,
                    quality_flag='unvalidated_reanalysis',
                    raw_payload_reference=raw_payload_reference,
                )
            )
        return tuple(observations)
