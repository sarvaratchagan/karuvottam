"""Evidence inventory for target-location weather-event impact (T8.4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean

from karuvottam.data_access import DataAccess, WeatherObservationRecord
from karuvottam.event_tracks import TrackView, great_circle_km


@dataclass(frozen=True)
class EventImpact:
    status: str
    reference_at: str | None
    distance_km: float | None
    distance_change_km: float | None
    model_disagreement_km: float | None
    observation_source: str | None
    observation_references: tuple[str, ...]
    observation_hours: int
    rain_hours: int
    rain_mm: float | None
    humidity_pct: float | None
    cloud_cover_pct: float | None
    surface_wind_kmh: float | None
    gaps: tuple[str, ...]


def _valid_hourly_rain(record: WeatherObservationRecord) -> bool:
    if record.precipitation_mm is None or record.precipitation_interval_minutes != 60:
        return False
    if not record.precipitation_interval_start_utc or not record.precipitation_interval_end_utc:
        return False
    end = datetime.fromisoformat(record.precipitation_interval_end_utc)
    start = datetime.fromisoformat(record.precipitation_interval_start_utc)
    observed = datetime.fromisoformat(record.observed_at_utc)
    return end == observed and end - start == timedelta(hours=1)


def _mean(records: tuple[WeatherObservationRecord, ...], field: str) -> float | None:
    values = [getattr(record, field) for record in records if getattr(record, field) is not None]
    return round(mean(values), 1) if values else None


def _model_disagreement(track: TrackView) -> float | None:
    official = {}
    model = {}
    for path in track.paths:
        if path.point_type not in ('official_forecast', 'model_guidance'):
            continue
        target = official if path.point_type == 'official_forecast' else model
        for point in path.points:
            key = (path.source, point.valid_at)
            previous = target.get(key)
            if previous is None or (path.issued_at or '') > previous[0]:
                target[key] = (path.issued_at or '', point)
    by_time_official = {}
    by_time_model = {}
    for (_, valid_at), (_, point) in official.items():
        by_time_official.setdefault(valid_at, []).append(point)
    for (_, valid_at), (_, point) in model.items():
        by_time_model.setdefault(valid_at, []).append(point)
    differences = [
        great_circle_km(a.latitude, a.longitude, b.latitude, b.longitude)
        for valid_at in by_time_official.keys() & by_time_model.keys()
        for a in by_time_official[valid_at] for b in by_time_model[valid_at]
    ]
    return round(max(differences), 1) if differences else None


class EventImpactService:
    def __init__(
        self, access: DataAccess, *, location_name: str, target_latitude: float,
        target_longitude: float, timezone_name: str,
    ) -> None:
        self.access = access
        self.location_name = location_name
        self.target_latitude = target_latitude
        self.target_longitude = target_longitude
        self.timezone_name = timezone_name

    def build(self, track: TrackView) -> EventImpact:
        observed = next((path.points for path in track.paths if path.point_type == 'observed'), ())
        latest = observed[-1] if observed else None
        distance = (
            round(great_circle_km(latest.latitude, latest.longitude,
                                  self.target_latitude, self.target_longitude), 1)
            if latest else None
        )
        distance_change = (
            round(distance - great_circle_km(
                observed[-2].latitude, observed[-2].longitude,
                self.target_latitude, self.target_longitude,
            ), 1)
            if len(observed) >= 2 else None
        )
        disagreement = _model_disagreement(track)
        gaps = []
        if latest is None:
            gaps.append('கண்காணிக்கப்பட்ட நிகழ்வு மையப் புள்ளி இல்லை.')
        if disagreement is None:
            gaps.append('ஒரே செல்லுபடி நேரத்திற்கான அதிகாரப்பூர்வ மற்றும் மாதிரி பாதைகள் இரண்டும் இல்லை.')
        gaps.extend((
            'இலக்கிடத்திற்கான மூலத்துடன் கூடிய எதிர்கால மழை மாதிரி வெளியீடு இல்லை.',
            'மேலடுக்கு காற்றோட்டம் மற்றும் நிலப்பரப்பு தாக்க மாதிரி இல்லை.',
            'நிகழ்வு–உள்ளூர் மழை தொடர்பின் தனி வரலாற்றுச் சரிபார்ப்பு இன்னும் இல்லை.',
        ))

        source = None
        records: tuple[WeatherObservationRecord, ...] = ()
        if latest:
            end = datetime.fromisoformat(latest.valid_at.replace('Z', '+00:00'))
            with self.access.transaction() as work:
                location = next((item for item in work.locations.list_active()
                                 if item.name == self.location_name
                                 and abs(item.latitude - self.target_latitude) < 0.000001
                                 and abs(item.longitude - self.target_longitude) < 0.000001
                                 and item.timezone_name == self.timezone_name), None)
                if location:
                    candidates = work.weather_observations.list_between(
                        location.id, end - timedelta(hours=24), end,
                    )
                    by_source = {}
                    for record in candidates:
                        observed_at = datetime.fromisoformat(record.observed_at_utc)
                        if (end - timedelta(hours=24) < observed_at <= end
                                and record.quality_flag == 'valid'
                                and not record.is_interpolated):
                            by_source.setdefault(record.source, []).append(record)
                    if by_source:
                        source, chosen = max(
                            by_source.items(), key=lambda pair: (len(pair[1]), pair[0])
                        )
                        records = tuple(chosen)
                else:
                    gaps.append('இலக்கு இடத்திற்கான செயலில் உள்ள வானிலைத் தரவு இடம் இல்லை.')
        rain_records = tuple(record for record in records if _valid_hourly_rain(record))
        if len(rain_records) < 24:
            gaps.append(f'முந்தைய 24 மணிநேர உள்ளூர் மழை அளவீடு முழுமையில்லை ({len(rain_records)}/24 மணி).')
        rain_mm = round(sum(record.precipitation_mm for record in rain_records), 1) if len(rain_records) == 24 else None
        if not records:
            gaps.append('நிகழ்வு நேரத்துடன் பொருந்தும் தரச் சரிபார்க்கப்பட்ட உள்ளூர் ஈரப்பதம், மேகம், காற்று பதிவுகள் இல்லை.')
        return EventImpact(
            status='insufficient_evidence',
            reference_at=latest.valid_at if latest else None,
            distance_km=distance,
            distance_change_km=distance_change,
            model_disagreement_km=disagreement,
            observation_source=source,
            observation_references=tuple(sorted({
                record.raw_payload_reference for record in records
                if record.raw_payload_reference
            })),
            observation_hours=len(records),
            rain_hours=len(rain_records),
            rain_mm=rain_mm,
            humidity_pct=_mean(records, 'relative_humidity_pct'),
            cloud_cover_pct=_mean(records, 'cloud_cover_pct'),
            surface_wind_kmh=_mean(records, 'wind_speed_kmh'),
            gaps=tuple(gaps),
        )
