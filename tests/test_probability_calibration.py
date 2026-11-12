from datetime import datetime, timedelta, timezone

import pytest

from karuvottam.probability_calibration import (
    CALIBRATION_MODEL_VERSION,
    CalibrationPolicy,
    CalibrationSample,
    ProbabilityCalibrationEngine,
)


BASE = datetime(2018, 1, 1, tzinfo=timezone.utc)


def strong_samples(window_count=8, samples_per_window=30):
    samples = []
    for window_index in range(window_count):
        window_end = BASE + timedelta(days=window_index * 365)
        for sample_index in range(samples_per_window):
            observed_rain = sample_index >= samples_per_window // 2
            samples.append(
                CalibrationSample(
                    source_window_key=f'aadi:{2018 + window_index}:2.0',
                    source_window_end=window_end,
                    target_datetime=window_end + timedelta(days=sample_index + 1),
                    research_score=90.0 if observed_rain else 10.0,
                    observed_rain=observed_rain,
                )
            )
    return samples


def test_time_ordered_holdout_produces_brier_and_reliability_metrics():
    report = ProbabilityCalibrationEngine().fit_evaluate(strong_samples())

    assert report.status == 'validated'
    assert report.probability_output_enabled
    assert report.model_version == CALIBRATION_MODEL_VERSION
    assert report.training_window_keys == tuple(
        f'aadi:{year}:2.0' for year in range(2018, 2023)
    )
    assert report.evaluation_window_keys == tuple(
        f'aadi:{year}:2.0' for year in range(2023, 2026)
    )
    assert report.training_samples == 150
    assert report.evaluation_samples == 90
    assert report.training_period_end < report.evaluation_period_start
    assert report.brier_score is not None
    assert report.baseline_brier_score is not None
    assert report.brier_score < report.baseline_brier_score
    assert report.expected_calibration_error is not None
    assert report.expected_calibration_error < 0.15
    assert len([item for item in report.reliability_bins if item.sample_count]) == 2


def test_calibrated_probability_is_available_only_after_gate_passes():
    engine = ProbabilityCalibrationEngine()
    validated = engine.fit_evaluate(strong_samples())
    withheld = engine.fit_evaluate(strong_samples(window_count=2, samples_per_window=10))

    low_probability = engine.predict_probability(10.0, validated)

    assert low_probability is not None
    assert 0 <= low_probability < 0.1
    assert engine.predict_probability(10.0, withheld) is None
    assert not withheld.probability_output_enabled
    assert 'insufficient_training_samples' in withheld.reason_codes


def test_input_order_does_not_change_time_split_or_metrics():
    samples = strong_samples()
    engine = ProbabilityCalibrationEngine()

    first = engine.fit_evaluate(samples)
    second = engine.fit_evaluate(list(reversed(samples)))

    assert first == second


def test_single_class_evidence_is_withheld():
    samples = [
        CalibrationSample(
            source_window_key=sample.source_window_key,
            source_window_end=sample.source_window_end,
            target_datetime=sample.target_datetime,
            research_score=sample.research_score,
            observed_rain=False,
        )
        for sample in strong_samples()
    ]

    report = ProbabilityCalibrationEngine().fit_evaluate(samples)

    assert not report.probability_output_enabled
    assert 'single_class_training_data' in report.reason_codes
    assert 'single_class_evaluation_data' in report.reason_codes


def test_no_baseline_improvement_withholds_probability():
    samples = strong_samples()
    uninformative = [
        CalibrationSample(
            source_window_key=sample.source_window_key,
            source_window_end=sample.source_window_end,
            target_datetime=sample.target_datetime,
            research_score=50.0,
            observed_rain=sample.observed_rain,
        )
        for sample in samples
    ]

    report = ProbabilityCalibrationEngine().fit_evaluate(uninformative)

    assert not report.probability_output_enabled
    assert 'no_brier_improvement_over_climatology' in report.reason_codes


def test_window_group_is_never_split_between_training_and_evaluation():
    report = ProbabilityCalibrationEngine().fit_evaluate(strong_samples())

    assert set(report.training_window_keys).isdisjoint(report.evaluation_window_keys)


def test_overlapping_training_outcomes_withhold_publication():
    samples = strong_samples()
    evaluation_start = BASE + timedelta(days=5 * 365)
    last_training_key = 'aadi:2022:2.0'
    changed_target = min(
        sample.target_datetime
        for sample in samples
        if sample.source_window_key == last_training_key
    )
    adjusted = [
        CalibrationSample(
            source_window_key=sample.source_window_key,
            source_window_end=sample.source_window_end,
            target_datetime=(
                evaluation_start + timedelta(days=1)
                if sample.source_window_key == last_training_key
                and sample.target_datetime == changed_target
                else sample.target_datetime
            ),
            research_score=sample.research_score,
            observed_rain=sample.observed_rain,
        )
        for sample in samples
    ]

    report = ProbabilityCalibrationEngine().fit_evaluate(adjusted)

    assert not report.probability_output_enabled
    assert 'training_outcomes_overlap_evaluation_period' in report.reason_codes


def test_duplicate_sample_identity_is_rejected():
    sample = strong_samples(window_count=1, samples_per_window=1)[0]

    with pytest.raises(ValueError, match='duplicate calibration sample'):
        ProbabilityCalibrationEngine().fit_evaluate([sample, sample])


@pytest.mark.parametrize(
    ('change', 'message'),
    [
        ({'source_window_key': ' '}, 'must not be blank'),
        ({'source_window_end': BASE.replace(tzinfo=None)}, 'timezone-aware'),
        ({'target_datetime': BASE.replace(tzinfo=None)}, 'timezone-aware'),
        ({'target_datetime': BASE}, 'must be after'),
        ({'research_score': -0.1}, 'from 0 to 100'),
        ({'research_score': 100.1}, 'from 0 to 100'),
        ({'observed_rain': 1}, 'must be boolean'),
    ],
)
def test_invalid_samples_fail_explicitly(change, message):
    values = {
        'source_window_key': 'aadi:2018:2.0',
        'source_window_end': BASE,
        'target_datetime': BASE + timedelta(days=1),
        'research_score': 50.0,
        'observed_rain': True,
    }
    values.update(change)

    with pytest.raises(ValueError, match=message):
        ProbabilityCalibrationEngine().fit_evaluate([CalibrationSample(**values)])


def test_inconsistent_window_end_for_same_key_is_rejected():
    samples = strong_samples(window_count=1, samples_per_window=2)
    samples[1] = CalibrationSample(
        source_window_key=samples[1].source_window_key,
        source_window_end=samples[1].source_window_end + timedelta(hours=1),
        target_datetime=samples[1].target_datetime,
        research_score=samples[1].research_score,
        observed_rain=samples[1].observed_rain,
    )

    with pytest.raises(ValueError, match='one end timestamp'):
        ProbabilityCalibrationEngine().fit_evaluate(samples)


@pytest.mark.parametrize(
    ('overrides', 'message'),
    [
        ({'training_fraction': 0}, 'within'),
        ({'training_fraction': 1}, 'within'),
        ({'minimum_training_samples': 0}, 'must be positive'),
        ({'maximum_expected_calibration_error': 1.1}, 'between 0 and 1'),
    ],
)
def test_invalid_policy_is_rejected_during_construction(overrides, message):
    with pytest.raises(ValueError, match=message):
        CalibrationPolicy(**overrides)
