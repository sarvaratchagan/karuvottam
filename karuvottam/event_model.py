"""Source-faithful weather-event advisory and track-point input contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


EVENT_TYPES = frozenset({'uacc', 'lpa', 'depression', 'deep_depression', 'cyclone'})
POINT_TYPES = frozenset({'observed', 'official_forecast', 'model_guidance'})
CLASSIFICATION_BASES = frozenset({'provider_category', 'analyst_interpretation'})


def utc_timestamp(value: datetime, name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f'{name} must be timezone-aware')
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _text(value: str | None, name: str, *, required: bool = True) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f'{name} must be nonblank text of at most 1000 characters')


def _coordinate(value: float, name: str, limit: float) -> None:
    if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f'{name} must be a finite coordinate between {-limit} and {limit}')


@dataclass(frozen=True)
class EventAdvisory:
    source: str
    event_key: str
    event_type: str
    provider_classification: str
    issued_at: datetime
    retrieved_at: datetime
    quality_flag: str
    source_reference: str | None = None
    source_url: str | None = None
    classification_basis: str = 'provider_category'
    classification_rule_version: str | None = None
    intensity: str | None = None
    center_latitude: float | None = None
    center_longitude: float | None = None
    central_pressure_hpa: float | None = None
    maximum_wind_kmh: float | None = None

    def validate(self) -> None:
        for name in ('source', 'event_key', 'provider_classification', 'quality_flag'):
            _text(getattr(self, name), name)
        _text(self.source_reference, 'source_reference', required=False)
        _text(self.source_url, 'source_url', required=False)
        _text(self.intensity, 'intensity', required=False)
        _text(self.classification_rule_version, 'classification_rule_version', required=False)
        if self.source_reference is None and self.source_url is None:
            raise ValueError('source_reference or source_url is required')
        if self.event_type not in EVENT_TYPES:
            raise ValueError('event_type is unsupported')
        if self.classification_basis not in CLASSIFICATION_BASES:
            raise ValueError('classification_basis is unsupported')
        if self.classification_basis == 'analyst_interpretation' and not self.classification_rule_version:
            raise ValueError('analyst interpretation requires classification_rule_version')
        if self.source_url is not None and not self.source_url.startswith(('https://', 'http://')):
            raise ValueError('source_url must use HTTP or HTTPS')
        if utc_timestamp(self.retrieved_at, 'retrieved_at') < utc_timestamp(self.issued_at, 'issued_at'):
            raise ValueError('retrieved_at must not precede issued_at')
        if (self.center_latitude is None) != (self.center_longitude is None):
            raise ValueError('center latitude and longitude must be provided together')
        if self.center_latitude is not None:
            _coordinate(self.center_latitude, 'center_latitude', 90)
            _coordinate(self.center_longitude, 'center_longitude', 180)
        for name in ('central_pressure_hpa', 'maximum_wind_kmh'):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, (int, float)) or not math.isfinite(value)
                or value < (0 if name == 'maximum_wind_kmh' else 0.000001)
            ):
                raise ValueError(f'{name} must be a finite positive value')


@dataclass(frozen=True)
class EventTrackPoint:
    valid_at: datetime
    latitude: float
    longitude: float
    point_type: str
    source: str
    quality_flag: str
    issued_at: datetime | None = None

    def validate(self) -> None:
        utc_timestamp(self.valid_at, 'valid_at')
        if self.issued_at is not None:
            utc_timestamp(self.issued_at, 'issued_at')
        _coordinate(self.latitude, 'latitude', 90)
        _coordinate(self.longitude, 'longitude', 180)
        _text(self.source, 'source')
        _text(self.quality_flag, 'quality_flag')
        if self.point_type not in POINT_TYPES:
            raise ValueError('point_type is unsupported')
        if self.point_type != 'observed' and self.issued_at is None:
            raise ValueError('forecast and model points require issued_at')
