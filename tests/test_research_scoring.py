from datetime import datetime, timedelta, timezone

import pytest

from karuvottam.data_access import WeatherObservation
from karuvottam.research_scoring import ResearchScoringEngine
from karuvottam.weather_quality import WeatherQualityValidator


START = datetime(2026, 6, 1, tzinfo=timezone.utc)


def observation(hour, **overrides):
    observed = START + timedelta(hours=hour)
    values = {
        'location_id': 1,
        'observed_at_utc': observed,
        'observed_at_local': observed,
        'source': 'test',
        'quality_flag': 'raw',
        'temperature_c': 27.0,
        'relative_humidity_pct': 85.0,
        'precipitation_mm': 1.0,
        'cloud_cover_pct': 80.0,
        'wind_speed_kmh': 20.0,
        'wind_direction_deg': 180.0,
        'pressure_hpa': 1005.0,
    }
    values.update(overrides)
    return WeatherObservation(**values)


def quality(observations, hours=None):
    hours = len(observations) if hours is None else hours
    return WeatherQualityValidator().validate(
        observations,
        expected_start_utc=START,
        expected_end_utc=START + timedelta(hours=hours),
    )


def test_documented_anchor_values_produce_expected_component_score():
    observations = [observation(0), observation(1)]

    result = ResearchScoringEngine().score(observations, quality(observations))

    assert result.status == 'available'
    assert result.score == 73.5
    assert result.maximum_score == 100.0
    assert result.label == 'experimental_research_index_not_probability'
    assert [component.points for component in result.components] == [
        18.0,
        20.0,
        16.0,
        7.5,
        12.0,
    ]


def test_identical_values_are_order_invariant_and_repeatable():
    observations = [
        observation(0, precipitation_mm=0.1),
        observation(1, precipitation_mm=5.0),
    ]
    report = quality(observations)
    engine = ResearchScoringEngine()

    first = engine.score(observations, report)
    second = engine.score(observations, report)
    reversed_observations = list(reversed(observations))
    reversed_report = quality(reversed_observations)

    assert first == second
    assert engine.score(reversed_observations, reversed_report).score == first.score


def test_invalid_quality_report_never_produces_a_score():
    observations = [observation(0), observation(0)]

    result = ResearchScoringEngine().score(observations, quality(observations))

    assert result.status == 'unavailable'
    assert result.score is None
    assert result.reason_codes == ('invalid_quality_report',)


def test_insufficient_required_field_coverage_is_explicit():
    observations = [
        observation(0, cloud_cover_pct=None),
        observation(1, cloud_cover_pct=None),
        observation(2, cloud_cover_pct=None),
        observation(3),
        observation(4),
    ]

    result = ResearchScoringEngine().score(observations, quality(observations))

    assert result.status == 'unavailable'
    assert result.score is None
    assert result.reason_codes == ('insufficient_coverage:cloud_cover_pct',)


def test_warning_quality_is_retained_with_available_score():
    observations = [observation(0), observation(1, is_interpolated=True)]

    result = ResearchScoringEngine().score(observations, quality(observations))

    assert result.is_available
    assert result.quality_flag == 'warning'
    assert result.reason_codes == ('quality_warning',)


def test_insufficient_time_coverage_is_unavailable():
    observations = [observation(0)]

    result = ResearchScoringEngine().score(observations, quality(observations, hours=2))

    assert result.score is None
    assert result.reason_codes == ('insufficient_time_coverage',)


def test_empty_input_is_unavailable_instead_of_invented():
    result = ResearchScoringEngine().score([], quality([], hours=2))

    assert result.score is None
    assert result.reason_codes == ('no_records',)


def test_mismatched_quality_report_is_rejected():
    observations = [observation(0)]

    with pytest.raises(ValueError, match='record count'):
        ResearchScoringEngine().score(observations, quality([], hours=1))


@pytest.mark.parametrize('coverage', [0, -1, 100.1])
def test_invalid_minimum_coverage_is_rejected(coverage):
    with pytest.raises(ValueError, match='within'):
        ResearchScoringEngine(coverage)
