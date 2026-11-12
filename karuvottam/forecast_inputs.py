"""Load stored source-window observations for experimental forecast scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from karuvottam.data_access import (
    DataAccess,
    DataAccessError,
    LocationRecord,
    WeatherObservation,
    WeatherObservationRecord,
)
from karuvottam.forecast_timeline import unavailable_research_score
from karuvottam.research_scoring import ResearchScore, ResearchScoringEngine
from karuvottam.weather_quality import WeatherQualityValidator
from karuvottam.windows import KaruvottamWindow


@dataclass(frozen=True)
class ForecastInputResult:
    research_score: ResearchScore
    source: str
    location_id: int | None
    expected_hours: int
    received_hours: int
    coverage_pct: float


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('stored weather timestamp must be timezone-aware')
    return parsed


def _floor_utc_hour(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(
        minute=0,
        second=0,
        microsecond=0,
    )


def source_window_hour_ends(window: KaruvottamWindow) -> tuple[datetime, datetime]:
    """Return inclusive first/last UTC hour-end labels assigned to a window."""
    start = window.start_datetime_local
    end = window.end_datetime_local
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError('window start must be timezone-aware')
    if end.tzinfo is None or end.utcoffset() is None:
        raise ValueError('window end must be timezone-aware')
    if end <= start:
        raise ValueError('window end must be after its start')
    first = _floor_utc_hour(start) + timedelta(hours=1)
    last = _floor_utc_hour(end)
    if last < first:
        raise ValueError('window does not contain an hourly label')
    return first, last


class StoredForecastInputService:
    """Turn persisted hourly weather rows into the existing research index."""

    def __init__(
        self,
        data_access: DataAccess,
        scoring_engine: ResearchScoringEngine,
        quality_validator: WeatherQualityValidator,
        *,
        location_name: str,
        latitude: float,
        longitude: float,
        timezone_name: str,
        source: str,
    ) -> None:
        self.data_access = data_access
        self.scoring_engine = scoring_engine
        self.quality_validator = quality_validator
        self.location_name = location_name
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_name = timezone_name
        self.local_timezone = ZoneInfo(timezone_name)
        self.source = source

    def score(self, window: KaruvottamWindow) -> ForecastInputResult:
        first_hour, last_hour = source_window_hour_ends(window)
        expected_hours = int((last_hour - first_hour) / timedelta(hours=1)) + 1
        try:
            with self.data_access.transaction() as work:
                location = self._configured_location(work.locations.list_active())
                if location is None:
                    return self._unavailable(
                        'configured_location_not_found',
                        expected_hours=expected_hours,
                    )
                records = work.weather_observations.list_between(
                    location.id,
                    first_hour,
                    last_hour,
                    source=self.source,
                )
        except DataAccessError:
            return self._unavailable(
                'weather_database_unavailable',
                expected_hours=expected_hours,
            )

        observations = tuple(self._observation(record) for record in records)
        quality = self.quality_validator.validate(
            observations,
            expected_start_utc=first_hour,
            expected_end_utc=last_hour + timedelta(hours=1),
        )
        score = self.scoring_engine.score(observations, quality)
        if not observations and score.reason_codes == ('no_records',):
            score = unavailable_research_score('source_window_observations_not_found')
        return ForecastInputResult(
            research_score=score,
            source=self.source,
            location_id=location.id,
            expected_hours=expected_hours,
            received_hours=len(observations),
            coverage_pct=quality.coverage_pct,
        )

    def _configured_location(
        self,
        locations: tuple[LocationRecord, ...],
    ) -> LocationRecord | None:
        for location in locations:
            if (
                location.name == self.location_name
                and abs(location.latitude - self.latitude) < 0.000001
                and abs(location.longitude - self.longitude) < 0.000001
                and location.timezone_name == self.timezone_name
            ):
                return location
        return None

    @staticmethod
    def _observation(record: WeatherObservationRecord) -> WeatherObservation:
        observed_utc = _parse_timestamp(record.observed_at_utc)
        observed_local = _parse_timestamp(record.observed_at_local)
        assert observed_utc is not None and observed_local is not None
        interval_start = _parse_timestamp(
            record.precipitation_interval_start_utc
        )
        interval_end = _parse_timestamp(record.precipitation_interval_end_utc)
        compatible_interval = (
            record.precipitation_interval_minutes == 60
            and interval_start is not None
            and interval_end is not None
            and interval_end.astimezone(timezone.utc)
            == observed_utc.astimezone(timezone.utc)
            and interval_start.astimezone(timezone.utc)
            == observed_utc.astimezone(timezone.utc) - timedelta(hours=1)
        )
        return WeatherObservation(
            location_id=record.location_id,
            observed_at_utc=observed_utc,
            observed_at_local=observed_local,
            source=record.source,
            quality_flag=record.quality_flag,
            temperature_c=record.temperature_c,
            relative_humidity_pct=record.relative_humidity_pct,
            precipitation_mm=(
                record.precipitation_mm if compatible_interval else None
            ),
            cloud_cover_pct=record.cloud_cover_pct,
            wind_speed_kmh=record.wind_speed_kmh,
            wind_direction_deg=record.wind_direction_deg,
            pressure_hpa=record.pressure_hpa,
            is_interpolated=record.is_interpolated,
            raw_payload_reference=record.raw_payload_reference,
            precipitation_interval_start_utc=interval_start,
            precipitation_interval_end_utc=interval_end,
            precipitation_interval_minutes=record.precipitation_interval_minutes,
        )

    def _unavailable(
        self,
        reason: str,
        *,
        expected_hours: int,
    ) -> ForecastInputResult:
        return ForecastInputResult(
            research_score=unavailable_research_score(reason),
            source=self.source,
            location_id=None,
            expected_hours=expected_hours,
            received_hours=0,
            coverage_pct=0.0,
        )
