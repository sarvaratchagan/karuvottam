"""Read-only event movement, forecast-revision and SVG map model."""

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from karuvottam.data_access import DataAccess, WeatherEventRecord
from karuvottam.event_ingestion import SOURCE


EARTH_RADIUS_KM = 6371.0088
TYPE_LABELS = {
    'uacc': 'மேலடுக்கு சுழற்சி', 'lpa': 'குறைந்த காற்றழுத்தப் பகுதி',
    'depression': 'காற்றழுத்தத் தாழ்வு',
    'deep_depression': 'ஆழ்ந்த காற்றழுத்தத் தாழ்வு',
    'cyclone': 'புயல்',
}
PATH_LABELS = {
    'observed': 'கடந்த கண்காணிப்புப் பாதை',
    'official_forecast': 'அதிகாரப்பூர்வ முன்னறிவிப்பு',
    'model_guidance': 'மாதிரி வழிகாட்டுதல்',
}


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    delta_lat = b - a
    delta_lon = math.radians((lon2 - lon1 + 180) % 360 - 180)
    h = math.sin(delta_lat / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1, math.sqrt(h)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    delta_lon = math.radians((lon2 - lon1 + 180) % 360 - 180)
    y = math.sin(delta_lon) * math.cos(b)
    x = math.cos(a) * math.sin(b) - math.sin(a) * math.cos(b) * math.cos(delta_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


@dataclass(frozen=True)
class Motion:
    distance_km: float
    speed_kmh: float
    direction_deg: float
    start_at: str
    end_at: str


@dataclass(frozen=True)
class MapPoint:
    x: float
    y: float
    latitude: float
    longitude: float
    valid_at: str


@dataclass(frozen=True)
class MapPath:
    point_type: str
    label: str
    source: str
    issued_at: str | None
    points: tuple[MapPoint, ...]


@dataclass(frozen=True)
class MapShape:
    name: str
    d: str


@dataclass(frozen=True)
class MapLabel:
    name: str
    point: MapPoint
    kind: str


@dataclass(frozen=True)
class TrackView:
    year: int
    events: tuple[WeatherEventRecord, ...]
    selected: WeatherEventRecord | None
    history: tuple[WeatherEventRecord, ...]
    paths: tuple[MapPath, ...]
    target: MapPoint
    countries: tuple[MapShape, ...]
    states: tuple[MapShape, ...]
    map_labels: tuple[MapLabel, ...]
    motion: Motion | None
    target_distance_km: float | None
    forecast_shift_km: float | None
    latest_age_hours: float | None
    stale: bool


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _motion(first, last) -> Motion | None:
    hours = (_parse(last.valid_at) - _parse(first.valid_at)).total_seconds() / 3600
    if hours <= 0:
        return None
    distance = great_circle_km(first.latitude, first.longitude, last.latitude, last.longitude)
    return Motion(
        round(distance, 1), round(distance / hours, 1),
        round(bearing_deg(first.latitude, first.longitude, last.latitude, last.longitude), 1),
        first.valid_at, last.valid_at,
    )


@lru_cache(maxsize=1)
def _basemap() -> dict:
    return json.loads((Path(__file__).with_name('event_basemap.json')).read_text())


class EventTrackService:
    def __init__(
        self, access: DataAccess, *, target_latitude: float, target_longitude: float,
    ) -> None:
        self.access = access
        self.target_latitude = target_latitude
        self.target_longitude = target_longitude

    def latest_year(self) -> int | None:
        with self.access.transaction() as work:
            return work.weather_events.latest_year(SOURCE)

    def build(
        self, year: int, event_key: str | None = None,
        *, now: datetime | None = None,
    ) -> TrackView:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError('now must be timezone-aware')
        with self.access.transaction() as work:
            events = work.weather_events.latest_in_year(SOURCE, year)
            selected = next(
                (event for event in events if event.event_key == event_key),
                events[0] if events else None,
            )
            history = (
                work.weather_events.history(SOURCE, selected.event_key)
                if selected else ()
            )
            point_rows = [
                point for bulletin in history
                for point in work.weather_events.points(bulletin.id)
            ]
        # Multiple advisories may repeat an observed position; keep one per valid time.
        observed_by_time = {}
        forecast_groups = {}
        for point in point_rows:
            if point.point_type == 'observed':
                observed_by_time[point.valid_at] = point
            else:
                forecast_groups.setdefault(
                    (point.point_type, point.source, point.issued_at), []
                ).append(point)
        observed = sorted(observed_by_time.values(), key=lambda item: item.valid_at)
        tracks = (
            [('observed', SOURCE, None, observed)] if observed else []
        ) + [
            (kind, source, issued_at, sorted(points, key=lambda item: item.valid_at))
            for (kind, source, issued_at), points in sorted(
                forecast_groups.items(),
                key=lambda item: (
                    0 if item[0][0] == 'official_forecast' else 1,
                    item[0][2], item[0][1],
                ),
            )
        ]
        positions = [(self.target_latitude, self.target_longitude)] + [
            (point.latitude, point.longitude)
            for _, _, _, points in tracks for point in points
        ]
        # Keep the South India coastline visible for ordinary Bay of Bengal and
        # Arabian Sea events; expand the view when a track lies farther away.
        min_lat = min(3, min(lat for lat, _ in positions) - 2)
        max_lat = max(24, max(lat for lat, _ in positions) + 2)
        min_lon = min(65, min(lon for _, lon in positions) - 2)
        max_lon = max(97, max(lon for _, lon in positions) + 2)

        def projected(lat: float, lon: float, valid_at: str) -> MapPoint:
            return MapPoint(
                round(40 + 820 * (lon - min_lon) / (max_lon - min_lon), 2),
                round(40 + 420 * (max_lat - lat) / (max_lat - min_lat), 2),
                lat, lon, valid_at,
            )

        paths = tuple(
            MapPath(kind, PATH_LABELS[kind], source, issued_at,
                    tuple(projected(point.latitude, point.longitude, point.valid_at)
                          for point in points))
            for kind, source, issued_at, points in tracks
        )
        target = projected(self.target_latitude, self.target_longitude, '')

        def map_shape(feature: dict) -> MapShape:
            parts = []
            for ring in feature['rings']:
                points = [projected(lat, lon, '') for lon, lat in ring]
                if points:
                    parts.append(
                        f'M {points[0].x} {points[0].y} '
                        + ' '.join(f'L {point.x} {point.y}' for point in points[1:])
                        + ' Z'
                    )
            return MapShape(feature['name'], ' '.join(parts))

        basemap = _basemap()
        countries = tuple(map_shape(feature) for feature in basemap['countries'])
        states = tuple(map_shape(feature) for feature in basemap['states'])
        label_locations = (
            ('தமிழ்நாடு', 10.8, 78.8, 'land'),
            ('கேரளம்', 10.3, 76.1, 'land'),
            ('கர்நாடகம்', 15.2, 75.8, 'land'),
            ('இலங்கை', 7.5, 80.8, 'land'),
            ('அரபிக் கடல்', 13, 69.5, 'sea'),
            ('வங்காள விரிகுடா', 13, 89, 'sea'),
        )
        map_labels = tuple(
            MapLabel(name, projected(lat, lon, ''), kind)
            for name, lat, lon, kind in label_locations
            if min_lat < lat < max_lat and min_lon < lon < max_lon
        )
        latest = observed[-1] if observed else None
        motion = _motion(observed[-2], observed[-1]) if len(observed) >= 2 else None
        target_distance = (
            round(great_circle_km(latest.latitude, latest.longitude,
                                  self.target_latitude, self.target_longitude), 1)
            if latest else None
        )
        age_hours = (
            max(0, (now - _parse(latest.valid_at)).total_seconds() / 3600)
            if latest else None
        )
        # The active CSV is not a live advisory feed. Treat >72 h as stale.
        stale = age_hours is None or age_hours > 72
        shifts = {}
        for kind, source, issued_at, points in tracks:
            if kind == 'official_forecast':
                for point in points:
                    shifts.setdefault((source, point.valid_at), []).append((issued_at, point))
        shift_values = []
        for versions in shifts.values():
            versions.sort(key=lambda item: item[0])
            if len(versions) >= 2:
                old, new = versions[-2][1], versions[-1][1]
                shift_values.append(great_circle_km(
                    old.latitude, old.longitude, new.latitude, new.longitude
                ))
        return TrackView(
            year, events, selected, history, paths, target,
            countries, states, map_labels, motion,
            target_distance, round(max(shift_values), 1) if shift_values else None,
            round(age_hours, 1) if age_hours is not None else None, stale,
        )
