"""Deterministic quality checks for normalized hourly weather observations."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Mapping, Sequence

from karuvottam.data_access import WeatherObservation


QUALITY_VALID = 'valid'
QUALITY_MISSING = 'missing'
QUALITY_OUT_OF_RANGE = 'out_of_range'
QUALITY_DUPLICATE = 'duplicate'
QUALITY_INTERPOLATED = 'interpolated'
QUALITY_OUTSIDE_WINDOW = 'outside_window'

WEATHER_VALUE_RANGES: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        'temperature_c': (-90.0, 65.0),
        'relative_humidity_pct': (0.0, 100.0),
        'precipitation_mm': (0.0, 500.0),
        'cloud_cover_pct': (0.0, 100.0),
        'wind_speed_kmh': (0.0, 300.0),
        'wind_direction_deg': (0.0, 360.0),
        'pressure_hpa': (800.0, 1100.0),
    }
)


@dataclass(frozen=True)
class RecordQualityResult:
    record_index: int
    observed_at_utc: datetime
    quality_flag: str
    issue_codes: tuple[str, ...]
    rejected: bool


@dataclass(frozen=True)
class WeatherQualityReport:
    expected_start_utc: datetime
    expected_end_utc: datetime
    expected_hours: int
    received_records: int
    unique_hours: int
    accepted_records: int
    rejected_records: int
    valid_records: int
    missing_value_records: int
    out_of_range_records: int
    duplicate_records: int
    interpolated_records: int
    missing_hours: tuple[datetime, ...]
    field_missing_counts: Mapping[str, int]
    field_out_of_range_counts: Mapping[str, int]
    coverage_pct: float
    overall_quality_flag: str
    records: tuple[RecordQualityResult, ...]


class WeatherQualityValidator:
    """Apply stable record and complete-window checks without altering source data."""

    def __init__(
        self,
        value_ranges: Mapping[str, tuple[float, float]] = WEATHER_VALUE_RANGES,
    ) -> None:
        self.value_ranges = dict(value_ranges)
        if not self.value_ranges:
            raise ValueError('at least one weather value range is required')
        for field_name, bounds in self.value_ranges.items():
            if len(bounds) != 2 or bounds[0] > bounds[1]:
                raise ValueError(f'invalid quality range for {field_name}')

    def validate(
        self,
        observations: Sequence[WeatherObservation],
        *,
        expected_start_utc: datetime,
        expected_end_utc: datetime,
    ) -> WeatherQualityReport:
        start = self._utc_hour(expected_start_utc, 'expected_start_utc')
        end = self._utc_hour(expected_end_utc, 'expected_end_utc')
        if end <= start:
            raise ValueError('expected_end_utc must be after expected_start_utc')
        duration = end - start
        if duration % timedelta(hours=1):
            raise ValueError('quality window must contain whole hours')

        expected_hours = int(duration / timedelta(hours=1))
        expected_timestamps = {
            start + timedelta(hours=offset) for offset in range(expected_hours)
        }
        seen_identities: set[tuple[int, datetime, str]] = set()
        received_timestamps: set[datetime] = set()
        missing_counts: Counter[str] = Counter()
        range_counts: Counter[str] = Counter()
        results: list[RecordQualityResult] = []

        for index, observation in enumerate(observations):
            observed_utc = self._utc_hour(
                observation.observed_at_utc,
                f'observations[{index}].observed_at_utc',
            )
            identity = (observation.location_id, observed_utc, observation.source)
            issue_codes: list[str] = []
            categories: list[str] = []

            if identity in seen_identities:
                issue_codes.append(QUALITY_DUPLICATE)
                categories.append(QUALITY_DUPLICATE)
            else:
                seen_identities.add(identity)
                received_timestamps.add(observed_utc)

            if observed_utc not in expected_timestamps:
                issue_codes.append(QUALITY_OUTSIDE_WINDOW)
                categories.append(QUALITY_OUTSIDE_WINDOW)

            for field_name, (minimum, maximum) in self.value_ranges.items():
                value = getattr(observation, field_name)
                if value is None:
                    missing_counts[field_name] += 1
                    issue_codes.append(f'missing:{field_name}')
                    if QUALITY_MISSING not in categories:
                        categories.append(QUALITY_MISSING)
                    continue
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(float(value))
                    or not minimum <= float(value) <= maximum
                ):
                    range_counts[field_name] += 1
                    issue_codes.append(f'out_of_range:{field_name}')
                    if QUALITY_OUT_OF_RANGE not in categories:
                        categories.append(QUALITY_OUT_OF_RANGE)

            if observation.is_interpolated:
                issue_codes.append(QUALITY_INTERPOLATED)
                categories.append(QUALITY_INTERPOLATED)

            quality_flag = '+'.join(categories) if categories else QUALITY_VALID
            rejected = any(
                category in categories
                for category in (
                    QUALITY_DUPLICATE,
                    QUALITY_OUT_OF_RANGE,
                    QUALITY_OUTSIDE_WINDOW,
                )
            )
            results.append(
                RecordQualityResult(
                    record_index=index,
                    observed_at_utc=observed_utc,
                    quality_flag=quality_flag,
                    issue_codes=tuple(issue_codes),
                    rejected=rejected,
                )
            )

        missing_hours = tuple(sorted(expected_timestamps - received_timestamps))
        duplicate_records = sum(
            QUALITY_DUPLICATE in result.quality_flag.split('+') for result in results
        )
        out_of_range_records = sum(
            QUALITY_OUT_OF_RANGE in result.quality_flag.split('+') for result in results
        )
        missing_value_records = sum(
            QUALITY_MISSING in result.quality_flag.split('+') for result in results
        )
        interpolated_records = sum(
            QUALITY_INTERPOLATED in result.quality_flag.split('+') for result in results
        )
        rejected_records = sum(result.rejected for result in results)
        valid_records = sum(result.quality_flag == QUALITY_VALID for result in results)
        unique_hours = len(received_timestamps & expected_timestamps)
        coverage_pct = round(unique_hours / expected_hours * 100, 2)

        if rejected_records:
            overall_flag = 'invalid'
        elif missing_hours or missing_value_records or interpolated_records:
            overall_flag = 'warning'
        else:
            overall_flag = 'valid'

        return WeatherQualityReport(
            expected_start_utc=start,
            expected_end_utc=end,
            expected_hours=expected_hours,
            received_records=len(observations),
            unique_hours=unique_hours,
            accepted_records=len(observations) - rejected_records,
            rejected_records=rejected_records,
            valid_records=valid_records,
            missing_value_records=missing_value_records,
            out_of_range_records=out_of_range_records,
            duplicate_records=duplicate_records,
            interpolated_records=interpolated_records,
            missing_hours=missing_hours,
            field_missing_counts=MappingProxyType(dict(missing_counts)),
            field_out_of_range_counts=MappingProxyType(dict(range_counts)),
            coverage_pct=coverage_pct,
            overall_quality_flag=overall_flag,
            records=tuple(results),
        )

    @staticmethod
    def _utc_hour(value: datetime, field_name: str) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f'{field_name} must be timezone-aware')
        normalized = value.astimezone(timezone.utc)
        if normalized.minute or normalized.second or normalized.microsecond:
            raise ValueError(f'{field_name} must fall on an exact hour')
        return normalized
