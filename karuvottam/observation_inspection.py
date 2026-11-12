"""Read model for inspecting stored hourly weather observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from karuvottam.data_access import (
    DataAccess,
    DataAccessError,
    LocationRecord,
    WeatherObservationRecord,
    WeatherStationRecord,
)


METRICS = (
    ('temperature_c', 'வெப்பநிலை', '°C'),
    ('relative_humidity_pct', 'ஈரப்பதம்', '%'),
    ('cloud_cover_pct', 'மேக மூட்டம்', '%'),
    ('precipitation_mm', 'மழை', 'மி.மீ.'),
    ('wind_speed_kmh', 'காற்றின் வேகம்', 'கி.மீ./மணி'),
)
MAX_RANGE_DAYS = 366


@dataclass(frozen=True)
class ChartPoint:
    observed_at_local: datetime
    value: float
    x_pct: float
    y_pct: float
    is_interpolated: bool
    quality_flag: str


@dataclass(frozen=True)
class ObservationSeries:
    field_name: str
    label_tamil: str
    unit: str
    points: tuple[ChartPoint, ...]
    segments: tuple[tuple[ChartPoint, ...], ...]
    minimum: float | None
    maximum: float | None
    missing_value_count: int


@dataclass(frozen=True)
class MissingInterval:
    start_local: datetime
    end_local: datetime
    missing_hours: int


@dataclass(frozen=True)
class ObservationInspection:
    location_name: str
    location_record: LocationRecord | None
    start_date: date
    end_date: date
    selected_source: str | None
    station: WeatherStationRecord | None
    available_sources: tuple[str, ...]
    records: tuple[WeatherObservationRecord, ...]
    recent_records: tuple[WeatherObservationRecord, ...]
    series: tuple[ObservationSeries, ...]
    gaps: tuple[MissingInterval, ...]
    expected_hours: int
    received_hours: int
    coverage_pct: float
    raw_count: int
    interpolated_count: int
    quality_counts: tuple[tuple[str, int], ...]
    database_available: bool
    warnings: tuple[str, ...]


class ObservationInspectionService:
    """Load a bounded observation range and derive honest chart metadata."""

    def __init__(
        self,
        data_access: DataAccess,
        *,
        location_name: str,
        latitude: float,
        longitude: float,
        timezone_name: str,
    ) -> None:
        self.data_access = data_access
        self.location_name = location_name
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_name = timezone_name
        self.local_timezone = ZoneInfo(timezone_name)

    def build(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        source: str | None = None,
        now: datetime | None = None,
    ) -> ObservationInspection:
        if (start_date is None) != (end_date is None):
            raise ValueError('start_date and end_date must be provided together')
        if start_date is not None:
            self._validate_date_range(start_date, end_date)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError('now must be timezone-aware')

        warnings: list[str] = []
        station = None
        try:
            with self.data_access.transaction() as work:
                location = self._configured_location(work.locations.list_active())
                if location is None:
                    warnings.append(
                        'அமைக்கப்பட்ட இடம் செயலில் உள்ள இடமாகத் தரவுத்தளத்தில் இல்லை.'
                    )
                    return self._empty_result(
                        start_date,
                        end_date,
                        current,
                        warnings=warnings,
                    )
                latest = work.weather_observations.latest_for_location(location.id)
                sources = work.weather_observations.list_sources_for_location(
                    location.id
                )
                selected_source = source.strip() if source else None
                if selected_source and selected_source not in sources:
                    warnings.append(
                        'கோரப்பட்ட தரவு மூலம் கிடைக்கவில்லை; சமீபத்திய மூலம் தேர்ந்தெடுக்கப்பட்டது.'
                    )
                    selected_source = None
                if selected_source is None and latest is not None:
                    selected_source = latest.source
                if selected_source is not None:
                    latest = work.weather_observations.latest_for_location(
                        location.id,
                        source=selected_source,
                    )
                    station = next((item for item in
                                    work.weather_stations.list_for_location(location.id)
                                    if selected_source == f'station:{item.station_key}'), None)

                if start_date is None or end_date is None:
                    reference_date = (
                        self._parse_datetime(latest.observed_at_local).date()
                        if latest is not None
                        else current.astimezone(self.local_timezone).date()
                    )
                    end_date = reference_date
                    start_date = reference_date - timedelta(days=6)
                self._validate_date_range(start_date, end_date)
                start_local, end_exclusive_local = self._local_boundaries(
                    start_date,
                    end_date,
                )
                records = work.weather_observations.list_between(
                    location.id,
                    start_local.astimezone(timezone.utc),
                    end_exclusive_local.astimezone(timezone.utc)
                    - timedelta(microseconds=1),
                    source=selected_source,
                )
        except DataAccessError:
            warnings.append(
                'தரவுத்தளம் தயாராக இல்லை; migration-ஐ இயக்கி மீண்டும் முயற்சிக்கவும்.'
            )
            return self._empty_result(
                start_date,
                end_date,
                current,
                database_available=False,
                warnings=warnings,
            )

        start_local, end_exclusive_local = self._local_boundaries(
            start_date,
            end_date,
        )
        actual_hours = {
            self._parse_datetime(record.observed_at_utc)
            .astimezone(timezone.utc)
            .replace(microsecond=0)
            for record in records
        }
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_exclusive_local.astimezone(timezone.utc)
        expected = self._expected_timestamps(start_utc, end_utc)
        expected_hours = len(expected)
        missing = tuple(hour for hour in expected if hour not in actual_hours)
        received_hours = len(set(expected) & actual_hours)
        quality_counts = Counter(record.quality_flag for record in records)
        if not records:
            warnings.append('தேர்ந்தெடுத்த காலத்தில் வானிலைப் பதிவுகள் இல்லை.')
        if missing:
            warnings.append(
                f'{len(missing)} மணிநேரத் தரவு விடுபட்டுள்ளது; கீழே கால இடைவெளிகள் காட்டப்பட்டுள்ளன.'
            )

        return ObservationInspection(
            location_name=self.location_name,
            location_record=location,
            start_date=start_date,
            end_date=end_date,
            selected_source=selected_source,
            station=station,
            available_sources=sources,
            records=records,
            recent_records=records[-100:],
            series=self._build_series(records, start_utc, end_utc),
            gaps=self._compress_gaps(missing),
            expected_hours=expected_hours,
            received_hours=received_hours,
            coverage_pct=round(received_hours / expected_hours * 100, 2),
            raw_count=sum(not record.is_interpolated for record in records),
            interpolated_count=sum(record.is_interpolated for record in records),
            quality_counts=tuple(sorted(quality_counts.items())),
            database_available=True,
            warnings=tuple(warnings),
        )

    def _empty_result(
        self,
        start_date: date | None,
        end_date: date | None,
        now: datetime,
        *,
        database_available: bool = True,
        warnings: list[str],
    ) -> ObservationInspection:
        reference = now.astimezone(self.local_timezone).date()
        resolved_end = end_date or reference
        resolved_start = start_date or resolved_end - timedelta(days=6)
        self._validate_date_range(resolved_start, resolved_end)
        start_local, end_exclusive = self._local_boundaries(
            resolved_start,
            resolved_end,
        )
        missing = self._expected_timestamps(
            start_local.astimezone(timezone.utc),
            end_exclusive.astimezone(timezone.utc),
        )
        expected_hours = len(missing)
        return ObservationInspection(
            location_name=self.location_name,
            location_record=None,
            start_date=resolved_start,
            end_date=resolved_end,
            selected_source=None,
            station=None,
            available_sources=(),
            records=(),
            recent_records=(),
            series=self._build_series(
                (),
                start_local.astimezone(timezone.utc),
                end_exclusive.astimezone(timezone.utc),
            ),
            gaps=self._compress_gaps(missing),
            expected_hours=expected_hours,
            received_hours=0,
            coverage_pct=0.0,
            raw_count=0,
            interpolated_count=0,
            quality_counts=(),
            database_available=database_available,
            warnings=tuple(warnings),
        )

    def _build_series(
        self,
        records: tuple[WeatherObservationRecord, ...],
        start_utc: datetime,
        end_utc: datetime,
    ) -> tuple[ObservationSeries, ...]:
        duration_seconds = (end_utc - start_utc).total_seconds()
        result: list[ObservationSeries] = []
        for field_name, label, unit in METRICS:
            valued = [
                (record, float(value))
                for record in records
                for value in (getattr(record, field_name),)
                if value is not None
            ]
            values = [value for _, value in valued]
            minimum = min(values) if values else None
            maximum = max(values) if values else None
            points: list[ChartPoint] = []
            for record, value in valued:
                observed = self._parse_datetime(record.observed_at_utc).astimezone(
                    timezone.utc
                )
                x_pct = (observed - start_utc).total_seconds() / duration_seconds * 100
                if minimum == maximum:
                    y_pct = 50.0
                else:
                    y_pct = 95.0 - (value - minimum) / (maximum - minimum) * 90.0
                points.append(
                    ChartPoint(
                        observed_at_local=observed.astimezone(self.local_timezone),
                        value=value,
                        x_pct=round(x_pct, 3),
                        y_pct=round(y_pct, 3),
                        is_interpolated=record.is_interpolated,
                        quality_flag=record.quality_flag,
                    )
                )
            result.append(
                ObservationSeries(
                    field_name=field_name,
                    label_tamil=label,
                    unit=unit,
                    points=tuple(points),
                    segments=self._segments(tuple(points)),
                    minimum=minimum,
                    maximum=maximum,
                    missing_value_count=len(records) - len(points),
                )
            )
        return tuple(result)

    @staticmethod
    def _segments(
        points: tuple[ChartPoint, ...],
    ) -> tuple[tuple[ChartPoint, ...], ...]:
        if not points:
            return ()
        segments: list[list[ChartPoint]] = [[points[0]]]
        for point in points[1:]:
            previous = segments[-1][-1]
            if point.observed_at_local - previous.observed_at_local > timedelta(
                hours=1
            ):
                segments.append([point])
            else:
                segments[-1].append(point)
        return tuple(tuple(segment) for segment in segments)

    def _compress_gaps(
        self,
        missing_utc: tuple[datetime, ...],
    ) -> tuple[MissingInterval, ...]:
        if not missing_utc:
            return ()
        ranges: list[tuple[datetime, datetime]] = []
        start = previous = missing_utc[0]
        for current in missing_utc[1:]:
            if current != previous + timedelta(hours=1):
                ranges.append((start, previous))
                start = current
            previous = current
        ranges.append((start, previous))
        return tuple(
            MissingInterval(
                start_local=start.astimezone(self.local_timezone),
                end_local=end.astimezone(self.local_timezone),
                missing_hours=int((end - start) / timedelta(hours=1)) + 1,
            )
            for start, end in ranges
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

    def _local_boundaries(
        self,
        start_date: date,
        end_date: date,
    ) -> tuple[datetime, datetime]:
        return (
            datetime.combine(start_date, time.min, tzinfo=self.local_timezone),
            datetime.combine(
                end_date + timedelta(days=1),
                time.min,
                tzinfo=self.local_timezone,
            ),
        )

    @staticmethod
    def _validate_date_range(start_date: date, end_date: date | None) -> None:
        if end_date is None or end_date < start_date:
            raise ValueError('end_date must not precede start_date')
        if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
            raise ValueError(f'date range must not exceed {MAX_RANGE_DAYS} days')

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))

    @staticmethod
    def _expected_timestamps(
        start_utc: datetime,
        end_utc: datetime,
    ) -> tuple[datetime, ...]:
        first = start_utc.replace(minute=0, second=0, microsecond=0)
        if first < start_utc:
            first += timedelta(hours=1)
        count = max(0, int((end_utc - first) / timedelta(hours=1)))
        if first + timedelta(hours=count) < end_utc:
            count += 1
        return tuple(first + timedelta(hours=offset) for offset in range(count))
