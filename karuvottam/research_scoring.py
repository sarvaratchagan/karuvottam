"""Deterministic, explicitly experimental scoring of Karuvottam observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from karuvottam.data_access import WeatherObservation
from karuvottam.weather_quality import WeatherQualityReport


MODEL_VERSION = 'research-index-1.0'
MINIMUM_FIELD_COVERAGE_PCT = 80.0

COMPONENT_WEIGHTS: Mapping[str, float] = MappingProxyType(
    {
        'precipitation': 30.0,
        'humidity': 25.0,
        'cloud': 20.0,
        'temperature': 10.0,
        'wind': 15.0,
    }
)

FIELD_COMPONENTS: Mapping[str, str] = MappingProxyType(
    {
        'precipitation_mm': 'precipitation',
        'relative_humidity_pct': 'humidity',
        'cloud_cover_pct': 'cloud',
        'temperature_c': 'temperature',
        'wind_speed_kmh': 'wind',
    }
)

# Piecewise-linear anchors: (observed window mean, component points).
COMPONENT_ANCHORS: Mapping[str, tuple[tuple[float, float], ...]] = MappingProxyType(
    {
        'precipitation': ((0.0, 0.0), (0.1, 6.0), (1.0, 18.0), (5.0, 30.0)),
        'humidity': (
            (0.0, 0.0),
            (50.0, 0.0),
            (70.0, 10.0),
            (85.0, 20.0),
            (100.0, 25.0),
        ),
        'cloud': (
            (0.0, 0.0),
            (20.0, 0.0),
            (50.0, 8.0),
            (80.0, 16.0),
            (100.0, 20.0),
        ),
        # Cooler window means receive more points only as an experimental proxy.
        'temperature': (
            (-90.0, 10.0),
            (24.0, 10.0),
            (30.0, 5.0),
            (36.0, 0.0),
            (65.0, 0.0),
        ),
        'wind': ((0.0, 0.0), (8.0, 5.0), (20.0, 12.0), (35.0, 15.0), (300.0, 15.0)),
    }
)


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    source_field: str
    mean_value: float
    available_records: int
    coverage_pct: float
    points: float
    maximum_points: float


@dataclass(frozen=True)
class ResearchScore:
    status: str
    score: float | None
    maximum_score: float
    model_version: str
    label: str
    quality_flag: str
    reason_codes: tuple[str, ...]
    components: tuple[ScoreComponent, ...]

    @property
    def is_available(self) -> bool:
        return self.status == 'available'


class ResearchScoringEngine:
    """Produce a repeatable research index without probability semantics."""

    def __init__(self, minimum_field_coverage_pct: float = MINIMUM_FIELD_COVERAGE_PCT):
        if not 0 < minimum_field_coverage_pct <= 100:
            raise ValueError('minimum_field_coverage_pct must be within (0, 100]')
        self.minimum_field_coverage_pct = float(minimum_field_coverage_pct)

    def score(
        self,
        observations: Sequence[WeatherObservation],
        quality_report: WeatherQualityReport,
    ) -> ResearchScore:
        if len(observations) != quality_report.received_records:
            raise ValueError('observations must match the quality report record count')
        if not observations:
            return self._unavailable(
                quality_report.overall_quality_flag,
                ('no_records',),
            )
        if quality_report.overall_quality_flag == 'invalid':
            return self._unavailable('invalid', ('invalid_quality_report',))
        if quality_report.coverage_pct < self.minimum_field_coverage_pct:
            return self._unavailable(
                quality_report.overall_quality_flag,
                ('insufficient_time_coverage',),
            )

        accepted_indices = {
            result.record_index
            for result in quality_report.records
            if not result.rejected
        }
        accepted = [
            observation
            for index, observation in enumerate(observations)
            if index in accepted_indices
        ]
        if not accepted:
            return self._unavailable(
                quality_report.overall_quality_flag,
                ('no_accepted_records',),
            )

        components: list[ScoreComponent] = []
        low_coverage: list[str] = []
        for field_name, component_name in FIELD_COMPONENTS.items():
            values = [
                float(value)
                for observation in accepted
                if (value := getattr(observation, field_name)) is not None
            ]
            coverage = round(len(values) / len(accepted) * 100, 2)
            if coverage < self.minimum_field_coverage_pct:
                low_coverage.append(field_name)
                continue
            mean_value = math.fsum(sorted(values)) / len(values)
            points = self._interpolate(
                mean_value,
                COMPONENT_ANCHORS[component_name],
            )
            components.append(
                ScoreComponent(
                    name=component_name,
                    source_field=field_name,
                    mean_value=round(mean_value, 4),
                    available_records=len(values),
                    coverage_pct=coverage,
                    points=round(points, 2),
                    maximum_points=COMPONENT_WEIGHTS[component_name],
                )
            )

        if low_coverage:
            reasons = tuple(f'insufficient_coverage:{field}' for field in low_coverage)
            return self._unavailable(
                quality_report.overall_quality_flag,
                reasons,
                tuple(components),
            )

        total = round(math.fsum(component.points for component in components), 2)
        reasons = (
            ('quality_warning',)
            if quality_report.overall_quality_flag == 'warning'
            else ()
        )
        return ResearchScore(
            status='available',
            score=total,
            maximum_score=100.0,
            model_version=MODEL_VERSION,
            label='experimental_research_index_not_probability',
            quality_flag=quality_report.overall_quality_flag,
            reason_codes=reasons,
            components=tuple(components),
        )

    @staticmethod
    def _interpolate(
        value: float,
        anchors: tuple[tuple[float, float], ...],
    ) -> float:
        if value <= anchors[0][0]:
            return anchors[0][1]
        for (left_value, left_points), (right_value, right_points) in zip(
            anchors,
            anchors[1:],
        ):
            if value <= right_value:
                width = right_value - left_value
                position = (value - left_value) / width
                return left_points + position * (right_points - left_points)
        return anchors[-1][1]

    @staticmethod
    def _unavailable(
        quality_flag: str,
        reasons: tuple[str, ...],
        components: tuple[ScoreComponent, ...] = (),
    ) -> ResearchScore:
        return ResearchScore(
            status='unavailable',
            score=None,
            maximum_score=100.0,
            model_version=MODEL_VERSION,
            label='experimental_research_index_not_probability',
            quality_flag=quality_flag,
            reason_codes=reasons,
            components=components,
        )
