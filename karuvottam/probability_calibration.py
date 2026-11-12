"""Leakage-safe probability calibration with evidence-gated publication."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


CALIBRATION_MODEL_VERSION = 'score-bin-calibration-1.0'
SCORE_BIN_EDGES = (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
PROBABILITY_BIN_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


@dataclass(frozen=True)
class CalibrationSample:
    source_window_key: str
    source_window_end: datetime
    target_datetime: datetime
    research_score: float
    observed_rain: bool


@dataclass(frozen=True)
class CalibrationPolicy:
    training_fraction: float = 0.7
    minimum_training_samples: int = 140
    minimum_evaluation_samples: int = 60
    minimum_training_windows: int = 4
    minimum_evaluation_windows: int = 2
    minimum_reliability_bin_samples: int = 10
    maximum_expected_calibration_error: float = 0.15
    require_baseline_improvement: bool = True

    def __post_init__(self) -> None:
        if not 0 < self.training_fraction < 1:
            raise ValueError('training_fraction must be within (0, 1)')
        for name in (
            'minimum_training_samples',
            'minimum_evaluation_samples',
            'minimum_training_windows',
            'minimum_evaluation_windows',
            'minimum_reliability_bin_samples',
        ):
            if getattr(self, name) < 1:
                raise ValueError(f'{name} must be positive')
        if not 0 <= self.maximum_expected_calibration_error <= 1:
            raise ValueError(
                'maximum_expected_calibration_error must be between 0 and 1'
            )


@dataclass(frozen=True)
class ScoreCalibrationBin:
    lower_score: float
    upper_score: float
    upper_inclusive: bool
    sample_count: int
    rain_count: int
    calibrated_probability: float


@dataclass(frozen=True)
class ReliabilityBin:
    lower_probability: float
    upper_probability: float
    upper_inclusive: bool
    sample_count: int
    mean_predicted_probability: float | None
    observed_frequency: float | None


@dataclass(frozen=True)
class CalibrationReport:
    status: str
    probability_output_enabled: bool
    reason_codes: tuple[str, ...]
    model_version: str
    training_window_keys: tuple[str, ...]
    evaluation_window_keys: tuple[str, ...]
    training_samples: int
    evaluation_samples: int
    training_period_start: datetime | None
    training_period_end: datetime | None
    evaluation_period_start: datetime | None
    evaluation_period_end: datetime | None
    brier_score: float | None
    baseline_brier_score: float | None
    expected_calibration_error: float | None
    calibration_bins: tuple[ScoreCalibrationBin, ...]
    reliability_bins: tuple[ReliabilityBin, ...]


class ProbabilityCalibrationEngine:
    """Fit on earlier windows and evaluate only on later held-out windows."""

    def __init__(self, policy: CalibrationPolicy | None = None) -> None:
        self.policy = policy or CalibrationPolicy()

    def fit_evaluate(
        self,
        samples: Sequence[CalibrationSample],
    ) -> CalibrationReport:
        normalized = tuple(self._validate_sample(sample) for sample in samples)
        groups = self._group_by_window(normalized)
        ordered_groups = sorted(
            groups.items(),
            key=lambda item: (item[1][0].source_window_end, item[0]),
        )
        split_index = math.floor(len(ordered_groups) * self.policy.training_fraction)
        if len(ordered_groups) > 1:
            split_index = min(max(split_index, 1), len(ordered_groups) - 1)

        training_groups = ordered_groups[:split_index]
        evaluation_groups = ordered_groups[split_index:]
        training = tuple(
            sample for _, group in training_groups for sample in group
        )
        evaluation = tuple(
            sample for _, group in evaluation_groups for sample in group
        )
        reasons = self._preflight_reasons(
            training_groups,
            evaluation_groups,
            training,
            evaluation,
        )

        if not training:
            return self._report_without_metrics(
                reasons or ('no_training_data',), training_groups, evaluation_groups
            )

        training_rate = sum(sample.observed_rain for sample in training) / len(training)
        calibration_bins = self._fit_bins(training, training_rate)
        if not evaluation:
            return self._report_without_metrics(
                reasons or ('no_evaluation_data',),
                training_groups,
                evaluation_groups,
                calibration_bins=calibration_bins,
            )

        predicted = tuple(
            self._probability_for_score(sample.research_score, calibration_bins)
            for sample in evaluation
        )
        observed = tuple(float(sample.observed_rain) for sample in evaluation)
        brier = self._mean_squared_error(predicted, observed)
        baseline = self._mean_squared_error(
            tuple(training_rate for _ in evaluation),
            observed,
        )
        reliability = self._reliability_bins(predicted, observed)
        ece = self._expected_calibration_error(reliability, len(evaluation))

        populated = [item for item in reliability if item.sample_count]
        if len(populated) < 2:
            reasons.append('insufficient_populated_reliability_bins')
        if any(
            item.sample_count < self.policy.minimum_reliability_bin_samples
            for item in populated
        ):
            reasons.append('underfilled_reliability_bin')
        if self.policy.require_baseline_improvement and brier >= baseline:
            reasons.append('no_brier_improvement_over_climatology')
        if ece > self.policy.maximum_expected_calibration_error:
            reasons.append('calibration_error_above_limit')

        unique_reasons = tuple(dict.fromkeys(reasons))
        enabled = not unique_reasons
        return CalibrationReport(
            status='validated' if enabled else 'withheld',
            probability_output_enabled=enabled,
            reason_codes=unique_reasons,
            model_version=CALIBRATION_MODEL_VERSION,
            training_window_keys=tuple(key for key, _ in training_groups),
            evaluation_window_keys=tuple(key for key, _ in evaluation_groups),
            training_samples=len(training),
            evaluation_samples=len(evaluation),
            training_period_start=min(sample.target_datetime for sample in training),
            training_period_end=max(sample.target_datetime for sample in training),
            evaluation_period_start=min(sample.target_datetime for sample in evaluation),
            evaluation_period_end=max(sample.target_datetime for sample in evaluation),
            brier_score=round(brier, 6),
            baseline_brier_score=round(baseline, 6),
            expected_calibration_error=round(ece, 6),
            calibration_bins=calibration_bins,
            reliability_bins=reliability,
        )

    def predict_probability(
        self,
        research_score: float,
        report: CalibrationReport,
    ) -> float | None:
        self._validate_score(research_score)
        if not report.probability_output_enabled:
            return None
        if report.model_version != CALIBRATION_MODEL_VERSION:
            raise ValueError('calibration report model version is not supported')
        return self._probability_for_score(research_score, report.calibration_bins)

    def _preflight_reasons(
        self,
        training_groups,
        evaluation_groups,
        training,
        evaluation,
    ):
        reasons: list[str] = []
        if len(training_groups) < self.policy.minimum_training_windows:
            reasons.append('insufficient_training_windows')
        if len(evaluation_groups) < self.policy.minimum_evaluation_windows:
            reasons.append('insufficient_evaluation_windows')
        if len(training) < self.policy.minimum_training_samples:
            reasons.append('insufficient_training_samples')
        if len(evaluation) < self.policy.minimum_evaluation_samples:
            reasons.append('insufficient_evaluation_samples')
        if training and len({sample.observed_rain for sample in training}) < 2:
            reasons.append('single_class_training_data')
        if evaluation and len({sample.observed_rain for sample in evaluation}) < 2:
            reasons.append('single_class_evaluation_data')
        if training and evaluation:
            training_outcome_end = max(
                sample.target_datetime for sample in training
            )
            first_evaluation_window = min(
                sample.source_window_end for sample in evaluation
            )
            if training_outcome_end >= first_evaluation_window:
                reasons.append('training_outcomes_overlap_evaluation_period')
        return reasons

    @staticmethod
    def _validate_sample(sample: CalibrationSample) -> CalibrationSample:
        if not sample.source_window_key.strip():
            raise ValueError('source_window_key must not be blank')
        for field_name, value in (
            ('source_window_end', sample.source_window_end),
            ('target_datetime', sample.target_datetime),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f'{field_name} must be timezone-aware')
        if sample.target_datetime <= sample.source_window_end:
            raise ValueError('target_datetime must be after source_window_end')
        ProbabilityCalibrationEngine._validate_score(sample.research_score)
        if not isinstance(sample.observed_rain, bool):
            raise ValueError('observed_rain must be boolean')
        return sample

    @staticmethod
    def _validate_score(score: float) -> None:
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
        ):
            raise ValueError('research_score must be a finite value from 0 to 100')

    @staticmethod
    def _group_by_window(samples):
        groups: dict[str, list[CalibrationSample]] = {}
        ends: dict[str, datetime] = {}
        identities: set[tuple[str, datetime]] = set()
        for sample in samples:
            identity = (sample.source_window_key, sample.target_datetime)
            if identity in identities:
                raise ValueError('duplicate calibration sample identity')
            identities.add(identity)
            previous_end = ends.setdefault(
                sample.source_window_key,
                sample.source_window_end,
            )
            if previous_end != sample.source_window_end:
                raise ValueError('a source window key must have one end timestamp')
            groups.setdefault(sample.source_window_key, []).append(sample)
        return {
            key: tuple(sorted(group, key=lambda sample: sample.target_datetime))
            for key, group in groups.items()
        }

    @staticmethod
    def _fit_bins(training, fallback_probability):
        bins = []
        for index, (lower, upper) in enumerate(
            zip(SCORE_BIN_EDGES, SCORE_BIN_EDGES[1:])
        ):
            upper_inclusive = index == len(SCORE_BIN_EDGES) - 2
            members = [
                sample
                for sample in training
                if lower <= sample.research_score
                and (
                    sample.research_score <= upper
                    if upper_inclusive
                    else sample.research_score < upper
                )
            ]
            rain_count = sum(sample.observed_rain for sample in members)
            probability = (
                (rain_count + 1) / (len(members) + 2)
                if members
                else fallback_probability
            )
            bins.append(
                ScoreCalibrationBin(
                    lower_score=lower,
                    upper_score=upper,
                    upper_inclusive=upper_inclusive,
                    sample_count=len(members),
                    rain_count=rain_count,
                    calibrated_probability=round(probability, 6),
                )
            )
        return tuple(bins)

    @staticmethod
    def _probability_for_score(score, bins):
        for item in bins:
            if item.lower_score <= score and (
                score <= item.upper_score
                if item.upper_inclusive
                else score < item.upper_score
            ):
                return item.calibrated_probability
        raise ValueError('research_score falls outside calibration bins')

    @staticmethod
    def _mean_squared_error(predicted, observed):
        return math.fsum(
            (forecast - actual) ** 2
            for forecast, actual in zip(predicted, observed)
        ) / len(observed)

    @staticmethod
    def _reliability_bins(predicted, observed):
        result = []
        for index, (lower, upper) in enumerate(
            zip(PROBABILITY_BIN_EDGES, PROBABILITY_BIN_EDGES[1:])
        ):
            upper_inclusive = index == len(PROBABILITY_BIN_EDGES) - 2
            indices = [
                position
                for position, probability in enumerate(predicted)
                if lower <= probability
                and (probability <= upper if upper_inclusive else probability < upper)
            ]
            result.append(
                ReliabilityBin(
                    lower_probability=lower,
                    upper_probability=upper,
                    upper_inclusive=upper_inclusive,
                    sample_count=len(indices),
                    mean_predicted_probability=(
                        round(
                            math.fsum(predicted[i] for i in indices) / len(indices),
                            6,
                        )
                        if indices
                        else None
                    ),
                    observed_frequency=(
                        round(
                            math.fsum(observed[i] for i in indices) / len(indices),
                            6,
                        )
                        if indices
                        else None
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _expected_calibration_error(reliability, total_samples):
        return math.fsum(
            item.sample_count / total_samples
            * abs(item.mean_predicted_probability - item.observed_frequency)
            for item in reliability
            if item.sample_count
            and item.mean_predicted_probability is not None
            and item.observed_frequency is not None
        )

    def _report_without_metrics(
        self,
        reasons,
        training_groups,
        evaluation_groups,
        *,
        calibration_bins=(),
    ):
        training = tuple(sample for _, group in training_groups for sample in group)
        evaluation = tuple(sample for _, group in evaluation_groups for sample in group)
        return CalibrationReport(
            status='withheld',
            probability_output_enabled=False,
            reason_codes=tuple(dict.fromkeys(reasons)),
            model_version=CALIBRATION_MODEL_VERSION,
            training_window_keys=tuple(key for key, _ in training_groups),
            evaluation_window_keys=tuple(key for key, _ in evaluation_groups),
            training_samples=len(training),
            evaluation_samples=len(evaluation),
            training_period_start=min(
                (s.target_datetime for s in training),
                default=None,
            ),
            training_period_end=max((s.target_datetime for s in training), default=None),
            evaluation_period_start=min(
                (s.target_datetime for s in evaluation),
                default=None,
            ),
            evaluation_period_end=max((s.target_datetime for s in evaluation), default=None),
            brier_score=None,
            baseline_brier_score=None,
            expected_calibration_error=None,
            calibration_bins=tuple(calibration_bins),
            reliability_bins=(),
        )
