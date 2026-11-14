"""Reproducible T6.3 metrics over matched T6.2 holdout predictions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Iterable, Mapping, Sequence
from uuid import uuid4

from karuvottam.baseline_comparison import APPROACHES


EVALUATION_VERSION = 'evaluation-metrics-1.0'
REQUIRED_COLUMNS = frozenset(
    {
        'comparison_version',
        'comparison_key',
        'dataset_key',
        'dataset_sha256',
        'approach',
        'model_version',
        'wet_day_threshold_mm',
        'season_type',
        'season_year',
        'source_window_key',
        'target_day_number',
        'target_date_local',
        'target_quality_flag',
        'observed_precipitation_mm',
        'observed_wet_day',
        'predicted_precipitation_mm',
        'predicted_wet_probability_pct',
        'status',
    }
)
METRIC_COLUMNS = (
    'evaluation_version',
    'evaluation_key',
    'comparison_key',
    'approach',
    'model_version',
    'dimension',
    'group_value',
    'total_rows',
    'available_rows',
    'evaluated_rows',
    'wet_days',
    'dry_days',
    'true_positive',
    'false_positive',
    'true_negative',
    'false_negative',
    'precision',
    'recall',
    'f1',
    'roc_auc',
    'brier_score',
    'expected_calibration_error',
    'mae_mm',
    'rmse_mm',
    'bias_mm',
    'correlation',
)
RELIABILITY_COLUMNS = (
    'evaluation_version',
    'evaluation_key',
    'comparison_key',
    'approach',
    'model_version',
    'dimension',
    'group_value',
    'bin_index',
    'lower_probability_pct',
    'upper_probability_pct',
    'upper_inclusive',
    'sample_count',
    'mean_predicted_probability_pct',
    'observed_wet_frequency_pct',
    'absolute_gap_pct',
)


@dataclass(frozen=True)
class EvaluationMetricSpec:
    classification_threshold_pct: float = 50.0
    reliability_bin_count: int = 10
    horizon_bin_days: int = 30

    def __post_init__(self) -> None:
        if not 0 <= self.classification_threshold_pct <= 100:
            raise ValueError('classification_threshold_pct must be between 0 and 100')
        if self.reliability_bin_count < 2:
            raise ValueError('reliability_bin_count must be at least 2')
        if 100 % self.reliability_bin_count:
            raise ValueError('reliability_bin_count must divide 100 exactly')
        if self.horizon_bin_days < 1:
            raise ValueError('horizon_bin_days must be positive')


@dataclass(frozen=True)
class EvaluationPrediction:
    comparison_key: str
    dataset_key: str
    dataset_sha256: str
    approach: str
    model_version: str
    wet_day_threshold_mm: float
    season_type: str
    season_year: int
    source_window_key: str
    target_day_number: int
    target_date_local: date
    target_quality_flag: str
    observed_precipitation_mm: float | None
    observed_wet_day: int | None
    predicted_precipitation_mm: float | None
    predicted_wet_probability_pct: float | None
    status: str

    @property
    def identity(self) -> tuple[str, int, int]:
        return self.season_type, self.season_year, self.target_day_number

    @property
    def evaluable(self) -> bool:
        return (
            self.status == 'available'
            and self.target_quality_flag == 'complete'
            and self.observed_precipitation_mm is not None
            and self.observed_wet_day is not None
            and self.predicted_precipitation_mm is not None
            and self.predicted_wet_probability_pct is not None
        )


@dataclass(frozen=True)
class MetricRow:
    approach: str
    model_version: str
    dimension: str
    group_value: str
    total_rows: int
    available_rows: int
    evaluated_rows: int
    wet_days: int
    dry_days: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float | None
    recall: float | None
    f1: float | None
    roc_auc: float | None
    brier_score: float | None
    expected_calibration_error: float | None
    mae_mm: float | None
    rmse_mm: float | None
    bias_mm: float | None
    correlation: float | None


@dataclass(frozen=True)
class ReliabilityRow:
    approach: str
    model_version: str
    dimension: str
    group_value: str
    bin_index: int
    lower_probability_pct: float
    upper_probability_pct: float
    upper_inclusive: bool
    sample_count: int
    mean_predicted_probability_pct: float | None
    observed_wet_frequency_pct: float | None
    absolute_gap_pct: float | None


@dataclass(frozen=True)
class EvaluationMetricsArtifact:
    evaluation_key: str
    metrics_path: Path
    reliability_path: Path
    summary_path: Path
    manifest_path: Path
    metric_rows: int
    reliability_rows: int
    evaluated_predictions: int


def _optional_number(value: str, name: str) -> float | None:
    if value == '':
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f'{name} must be numeric or blank') from exc
    if not math.isfinite(number):
        raise ValueError(f'{name} must be finite')
    return number


def _integer(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f'{name} must be an integer') from exc


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _roc_auc(probabilities: Sequence[float], outcomes: Sequence[int]) -> float | None:
    positive_count = sum(outcomes)
    negative_count = len(outcomes) - positive_count
    if not positive_count or not negative_count:
        return None
    ordered = sorted(zip(probabilities, outcomes, strict=True), key=lambda item: item[0])
    positive_rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = ((index + 1) + end) / 2
        positive_rank_sum += average_rank * sum(
            outcome for _, outcome in ordered[index:end]
        )
        index = end
    return (
        positive_rank_sum - positive_count * (positive_count + 1) / 2
    ) / (positive_count * negative_count)


def _correlation(predicted: Sequence[float], observed: Sequence[float]) -> float | None:
    if len(predicted) < 2:
        return None
    predicted_mean = fmean(predicted)
    observed_mean = fmean(observed)
    covariance = sum(
        (left - predicted_mean) * (right - observed_mean)
        for left, right in zip(predicted, observed, strict=True)
    )
    predicted_spread = math.sqrt(sum((value - predicted_mean) ** 2 for value in predicted))
    observed_spread = math.sqrt(sum((value - observed_mean) ** 2 for value in observed))
    if predicted_spread == 0 or observed_spread == 0:
        return None
    return covariance / (predicted_spread * observed_spread)


class BaselinePredictionReader:
    """Read and verify the stable T6.2 prediction artifact."""

    def read(
        self,
        predictions_path: str | Path,
        manifest_path: str | Path,
    ) -> tuple[tuple[EvaluationPrediction, ...], Mapping[str, object], str]:
        path = Path(predictions_path)
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        expected = manifest.get('files', {}).get(path.name, {}).get('sha256')
        if digest != expected:
            raise ValueError('baseline prediction checksum does not match its manifest')
        comparison_key = manifest.get('comparison_key')
        if not isinstance(comparison_key, str) or not comparison_key:
            raise ValueError('baseline manifest comparison_key is missing')
        comparison_version = manifest.get('comparison_version')
        if not isinstance(comparison_version, str) or not comparison_version:
            raise ValueError('baseline manifest comparison_version is missing')

        reader = csv.DictReader(io.StringIO(content.decode('utf-8')))
        missing = sorted(REQUIRED_COLUMNS - frozenset(reader.fieldnames or ()))
        if missing:
            raise ValueError(f'baseline predictions are missing columns: {missing}')
        predictions = tuple(
            self._prediction(
                row, row_number, comparison_key, comparison_version
            )
            for row_number, row in enumerate(reader, start=2)
        )
        if not predictions:
            raise ValueError('baseline predictions contain no rows')
        self._validate_matched_identities(predictions)
        self._validate_matched_outcomes(predictions)
        return predictions, manifest, digest

    @staticmethod
    def _prediction(
        row: Mapping[str, str],
        row_number: int,
        comparison_key: str,
        comparison_version: str,
    ) -> EvaluationPrediction:
        if row['comparison_key'] != comparison_key:
            raise ValueError(f'row {row_number} has a different comparison_key')
        if row['comparison_version'] != comparison_version:
            raise ValueError(f'row {row_number} has a different comparison_version')
        if row['approach'] not in APPROACHES:
            raise ValueError(f'row {row_number} has an unsupported approach')
        try:
            target_date = date.fromisoformat(row['target_date_local'])
        except ValueError as exc:
            raise ValueError(f'row {row_number} has an invalid target_date_local') from exc
        observed = _optional_number(
            row['observed_precipitation_mm'], 'observed_precipitation_mm'
        )
        predicted = _optional_number(
            row['predicted_precipitation_mm'], 'predicted_precipitation_mm'
        )
        probability = _optional_number(
            row['predicted_wet_probability_pct'],
            'predicted_wet_probability_pct',
        )
        wet_value = row['observed_wet_day']
        wet = None if wet_value == '' else _integer(wet_value, 'observed_wet_day')
        threshold = _optional_number(row['wet_day_threshold_mm'], 'wet_day_threshold_mm')
        if threshold is None or threshold < 0:
            raise ValueError('wet_day_threshold_mm must be non-negative')
        if observed is not None and observed < 0:
            raise ValueError('observed_precipitation_mm must be non-negative')
        if predicted is not None and predicted < 0:
            raise ValueError('predicted_precipitation_mm must be non-negative')
        if probability is not None and not 0 <= probability <= 100:
            raise ValueError('predicted_wet_probability_pct must be between 0 and 100')
        if wet not in (None, 0, 1):
            raise ValueError('observed_wet_day must be 0, 1, or blank')
        if observed is not None and wet is not None and wet != int(observed >= threshold):
            raise ValueError(f'row {row_number} has inconsistent observed_wet_day')
        status = row['status']
        if status not in {'available', 'unavailable'}:
            raise ValueError(f'row {row_number} has an unsupported status')
        return EvaluationPrediction(
            comparison_key=comparison_key,
            dataset_key=row['dataset_key'],
            dataset_sha256=row['dataset_sha256'],
            approach=row['approach'],
            model_version=row['model_version'],
            wet_day_threshold_mm=threshold,
            season_type=row['season_type'],
            season_year=_integer(row['season_year'], 'season_year'),
            source_window_key=row['source_window_key'],
            target_day_number=_integer(row['target_day_number'], 'target_day_number'),
            target_date_local=target_date,
            target_quality_flag=row['target_quality_flag'],
            observed_precipitation_mm=observed,
            observed_wet_day=wet,
            predicted_precipitation_mm=predicted,
            predicted_wet_probability_pct=probability,
            status=status,
        )

    @staticmethod
    def _validate_matched_identities(predictions: Sequence[EvaluationPrediction]) -> None:
        identities = {
            approach: [item.identity for item in predictions if item.approach == approach]
            for approach in APPROACHES
        }
        if any(not values for values in identities.values()):
            raise ValueError('all baseline approaches must be present')
        if any(len(values) != len(set(values)) for values in identities.values()):
            raise ValueError('duplicate evaluation identity within an approach')
        if len({frozenset(values) for values in identities.values()}) != 1:
            raise ValueError('baseline approaches do not contain matched identities')

    @staticmethod
    def _validate_matched_outcomes(
        predictions: Sequence[EvaluationPrediction],
    ) -> None:
        expected: dict[tuple[str, int, int], tuple[object, ...]] = {}
        for item in predictions:
            outcome = (
                item.dataset_key,
                item.dataset_sha256,
                item.wet_day_threshold_mm,
                item.source_window_key,
                item.target_date_local,
                item.target_quality_flag,
                item.observed_precipitation_mm,
                item.observed_wet_day,
            )
            previous = expected.setdefault(item.identity, outcome)
            if previous != outcome:
                raise ValueError(
                    'baseline approaches do not contain matched outcomes'
                )


class EvaluationMetricsEngine:
    def __init__(self, spec: EvaluationMetricSpec | None = None,
                 approaches: tuple[str, ...] = APPROACHES) -> None:
        self.spec = spec or EvaluationMetricSpec()
        if not approaches or len(approaches) != len(set(approaches)):
            raise ValueError('approaches must be nonempty and unique')
        self.approaches = approaches

    def evaluate(
        self,
        predictions: Sequence[EvaluationPrediction],
    ) -> tuple[tuple[MetricRow, ...], tuple[ReliabilityRow, ...]]:
        metric_rows: list[MetricRow] = []
        reliability_rows: list[ReliabilityRow] = []
        for approach in self.approaches:
            approach_rows = tuple(
                item for item in predictions if item.approach == approach
            )
            versions = {item.model_version for item in approach_rows}
            if len(versions) != 1:
                raise ValueError(f'{approach} has inconsistent model versions')
            model_version = next(iter(versions))
            for dimension, group_value, rows in self._groups(approach_rows):
                reliability = self._reliability(
                    rows, approach, model_version, dimension, group_value
                )
                reliability_rows.extend(reliability)
                metric_rows.append(
                    self._metric(
                        rows,
                        reliability,
                        approach,
                        model_version,
                        dimension,
                        group_value,
                    )
                )
        return tuple(metric_rows), tuple(reliability_rows)

    def _groups(
        self,
        records: Sequence[EvaluationPrediction],
    ) -> Iterable[tuple[str, str, tuple[EvaluationPrediction, ...]]]:
        yield 'overall', 'all', tuple(records)
        for season in sorted({item.season_type for item in records}):
            yield 'season', season, tuple(
                item for item in records if item.season_type == season
            )
        for month in sorted({item.target_date_local.month for item in records}):
            yield 'month', f'{month:02d}', tuple(
                item for item in records if item.target_date_local.month == month
            )
        bins = sorted({self._horizon_bin(item.target_day_number) for item in records})
        for lower, upper in bins:
            label = f'{lower:03d}-{upper:03d}'
            yield 'horizon', label, tuple(
                item
                for item in records
                if lower <= item.target_day_number <= upper
            )

    def _horizon_bin(self, day_number: int) -> tuple[int, int]:
        if day_number < 1:
            raise ValueError('target_day_number must be positive')
        lower = ((day_number - 1) // self.spec.horizon_bin_days) * self.spec.horizon_bin_days + 1
        return lower, lower + self.spec.horizon_bin_days - 1

    def _metric(
        self,
        records: Sequence[EvaluationPrediction],
        reliability: Sequence[ReliabilityRow],
        approach: str,
        model_version: str,
        dimension: str,
        group_value: str,
    ) -> MetricRow:
        evaluated = tuple(item for item in records if item.evaluable)
        probabilities = tuple(
            item.predicted_wet_probability_pct / 100
            for item in evaluated
            if item.predicted_wet_probability_pct is not None
        )
        outcomes = tuple(
            item.observed_wet_day
            for item in evaluated
            if item.observed_wet_day is not None
        )
        predicted_amounts = tuple(
            item.predicted_precipitation_mm
            for item in evaluated
            if item.predicted_precipitation_mm is not None
        )
        observed_amounts = tuple(
            item.observed_precipitation_mm
            for item in evaluated
            if item.observed_precipitation_mm is not None
        )
        predicted_wet = tuple(
            probability * 100 >= self.spec.classification_threshold_pct
            for probability in probabilities
        )
        tp = sum(predicted and observed == 1 for predicted, observed in zip(predicted_wet, outcomes, strict=True))
        fp = sum(predicted and observed == 0 for predicted, observed in zip(predicted_wet, outcomes, strict=True))
        tn = sum(not predicted and observed == 0 for predicted, observed in zip(predicted_wet, outcomes, strict=True))
        fn = sum(not predicted and observed == 1 for predicted, observed in zip(predicted_wet, outcomes, strict=True))
        precision = _safe_ratio(tp, tp + fp)
        recall = _safe_ratio(tp, tp + fn)
        f1 = (
            None
            if precision is None or recall is None
            else 0.0
            if precision + recall == 0
            else 2 * precision * recall / (precision + recall)
        )
        errors = tuple(
            predicted - observed
            for predicted, observed in zip(
                predicted_amounts, observed_amounts, strict=True
            )
        )
        brier = (
            fmean((probability - observed) ** 2 for probability, observed in zip(probabilities, outcomes, strict=True))
            if evaluated
            else None
        )
        ece = (
            sum(
                row.sample_count * row.absolute_gap_pct / 100
                for row in reliability
                if row.absolute_gap_pct is not None
            )
            / len(evaluated)
            if evaluated
            else None
        )
        return MetricRow(
            approach=approach,
            model_version=model_version,
            dimension=dimension,
            group_value=group_value,
            total_rows=len(records),
            available_rows=sum(item.status == 'available' for item in records),
            evaluated_rows=len(evaluated),
            wet_days=sum(outcomes),
            dry_days=len(outcomes) - sum(outcomes),
            true_positive=tp,
            false_positive=fp,
            true_negative=tn,
            false_negative=fn,
            precision=_rounded(precision),
            recall=_rounded(recall),
            f1=_rounded(f1),
            roc_auc=_rounded(_roc_auc(probabilities, outcomes)),
            brier_score=_rounded(brier),
            expected_calibration_error=_rounded(ece),
            mae_mm=_rounded(fmean(abs(value) for value in errors) if errors else None),
            rmse_mm=_rounded(math.sqrt(fmean(value**2 for value in errors)) if errors else None),
            bias_mm=_rounded(fmean(errors) if errors else None),
            correlation=_rounded(_correlation(predicted_amounts, observed_amounts)),
        )

    def _reliability(
        self,
        records: Sequence[EvaluationPrediction],
        approach: str,
        model_version: str,
        dimension: str,
        group_value: str,
    ) -> tuple[ReliabilityRow, ...]:
        evaluated = tuple(item for item in records if item.evaluable)
        width = 100 / self.spec.reliability_bin_count
        rows = []
        for index in range(self.spec.reliability_bin_count):
            lower = index * width
            upper = (index + 1) * width
            upper_inclusive = index == self.spec.reliability_bin_count - 1
            samples = tuple(
                item
                for item in evaluated
                if item.predicted_wet_probability_pct is not None
                and lower <= item.predicted_wet_probability_pct
                and (
                    item.predicted_wet_probability_pct <= upper
                    if upper_inclusive
                    else item.predicted_wet_probability_pct < upper
                )
            )
            mean_probability = (
                fmean(
                    item.predicted_wet_probability_pct
                    for item in samples
                    if item.predicted_wet_probability_pct is not None
                )
                if samples
                else None
            )
            frequency = (
                fmean(
                    item.observed_wet_day * 100
                    for item in samples
                    if item.observed_wet_day is not None
                )
                if samples
                else None
            )
            rows.append(
                ReliabilityRow(
                    approach=approach,
                    model_version=model_version,
                    dimension=dimension,
                    group_value=group_value,
                    bin_index=index + 1,
                    lower_probability_pct=lower,
                    upper_probability_pct=upper,
                    upper_inclusive=upper_inclusive,
                    sample_count=len(samples),
                    mean_predicted_probability_pct=_rounded(mean_probability),
                    observed_wet_frequency_pct=_rounded(frequency),
                    absolute_gap_pct=_rounded(
                        abs(mean_probability - frequency)
                        if mean_probability is not None and frequency is not None
                        else None
                    ),
                )
            )
        return tuple(rows)


class EvaluationMetricsService:
    def __init__(
        self,
        reader: BaselinePredictionReader | None = None,
    ) -> None:
        self.reader = reader or BaselinePredictionReader()

    def build(
        self,
        predictions_path: str | Path,
        baseline_manifest_path: str | Path,
        output_directory: str | Path,
        spec: EvaluationMetricSpec | None = None,
        *,
        built_at: datetime | None = None,
    ) -> EvaluationMetricsArtifact:
        metric_spec = spec or EvaluationMetricSpec()
        built_value = built_at or datetime.now(timezone.utc)
        if built_value.tzinfo is None or built_value.utcoffset() is None:
            raise ValueError('built_at must be timezone-aware')
        predictions, source_manifest, source_digest = self.reader.read(
            predictions_path, baseline_manifest_path
        )
        metrics, reliability = EvaluationMetricsEngine(metric_spec).evaluate(predictions)
        comparison_key = predictions[0].comparison_key
        evaluation_key = self._evaluation_key(
            comparison_key, source_digest, metric_spec
        )
        output = Path(output_directory)
        output.mkdir(parents=True, exist_ok=True)
        metrics_path = output / 'evaluation_metrics.csv'
        reliability_path = output / 'evaluation_reliability.csv'
        summary_path = output / 'evaluation_summary.md'
        manifest_path = output / 'evaluation_manifest.json'
        metrics_content = self._metrics_csv(
            metrics, evaluation_key, comparison_key
        )
        reliability_content = self._reliability_csv(
            reliability, evaluation_key, comparison_key
        )
        summary_content = self._summary(
            metrics, evaluation_key, comparison_key, metric_spec
        )
        self._write_atomic(metrics_path, metrics_content)
        self._write_atomic(reliability_path, reliability_content)
        self._write_atomic(summary_path, summary_content)
        evaluated_predictions = sum(
            item.evaluable for item in predictions
        )
        files = {
            metrics_path.name: self._file_details(metrics_content, len(metrics)),
            reliability_path.name: self._file_details(
                reliability_content, len(reliability)
            ),
            summary_path.name: self._file_details(summary_content, None),
        }
        manifest = {
            'evaluation_version': EVALUATION_VERSION,
            'evaluation_key': evaluation_key,
            'built_at_utc': built_value.astimezone(timezone.utc).isoformat().replace(
                '+00:00', 'Z'
            ),
            'source_comparison': {
                'comparison_key': comparison_key,
                'comparison_version': source_manifest.get('comparison_version'),
                'predictions_sha256': source_digest,
                'manifest_path': str(Path(baseline_manifest_path)),
            },
            'metric_spec': asdict(metric_spec),
            'metric_definitions': {
                'classification': 'Wet is observed rainfall at or above the T6.2 wet-day threshold; predicted wet uses the configured empirical-probability cutoff.',
                'roc_auc': 'Tie-aware rank AUC; blank for a single-class group.',
                'brier_score': 'Mean squared error of empirical wet probability on a 0-1 scale.',
                'expected_calibration_error': 'Sample-weighted absolute reliability gap on a 0-1 scale.',
                'bias_mm': 'Mean predicted minus observed daily precipitation.',
                'correlation': 'Pearson correlation; blank when either series has zero variance.',
                'horizon': f'Forecast-day bands of {metric_spec.horizon_bin_days} days.',
            },
            'limitations': [
                'ERA5 reanalysis rainfall is not a local rain-gauge observation.',
                'Empirical wet frequencies are preliminary and are not calibrated public forecast probabilities.',
                'Subgroup metrics with few wet or dry days are unstable; single-class ROC-AUC is intentionally blank.',
                'T6.3 scores one fixed temporal holdout; rolling time-series validation and uncertainty are T6.4 work.',
                'Metrics do not by themselves authorize probability publication in the application UI.',
            ],
            'counts': {
                'prediction_rows': len(predictions),
                'evaluated_predictions': evaluated_predictions,
                'metric_rows': len(metrics),
                'reliability_rows': len(reliability),
            },
            'files': files,
        }
        self._write_atomic(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(),
        )
        return EvaluationMetricsArtifact(
            evaluation_key=evaluation_key,
            metrics_path=metrics_path,
            reliability_path=reliability_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            metric_rows=len(metrics),
            reliability_rows=len(reliability),
            evaluated_predictions=evaluated_predictions,
        )

    @staticmethod
    def _evaluation_key(
        comparison_key: str,
        source_digest: str,
        spec: EvaluationMetricSpec,
    ) -> str:
        identity = {
            'evaluation_version': EVALUATION_VERSION,
            'comparison_key': comparison_key,
            'predictions_sha256': source_digest,
            'metric_spec': asdict(spec),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
        return f'{EVALUATION_VERSION}:{hashlib.sha256(encoded).hexdigest()[:16]}'

    @staticmethod
    def _metrics_csv(
        metrics: Sequence[MetricRow],
        evaluation_key: str,
        comparison_key: str,
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=METRIC_COLUMNS, lineterminator='\n')
        writer.writeheader()
        for metric in metrics:
            writer.writerow(
                {
                    'evaluation_version': EVALUATION_VERSION,
                    'evaluation_key': evaluation_key,
                    'comparison_key': comparison_key,
                    **asdict(metric),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _reliability_csv(
        reliability: Sequence[ReliabilityRow],
        evaluation_key: str,
        comparison_key: str,
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=RELIABILITY_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for row in reliability:
            writer.writerow(
                {
                    'evaluation_version': EVALUATION_VERSION,
                    'evaluation_key': evaluation_key,
                    'comparison_key': comparison_key,
                    **asdict(row),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _summary(
        metrics: Sequence[MetricRow],
        evaluation_key: str,
        comparison_key: str,
        spec: EvaluationMetricSpec,
    ) -> bytes:
        overall = [
            row
            for row in metrics
            if row.dimension == 'overall' and row.group_value == 'all'
        ]
        lines = [
            '# T6.3 evaluation summary',
            '',
            f'- Evaluation: `{evaluation_key}`',
            f'- Source comparison: `{comparison_key}`',
            f'- Predicted-wet cutoff: `{spec.classification_threshold_pct:g}%`',
            f'- Reliability bins: `{spec.reliability_bin_count}`',
            f'- Horizon band: `{spec.horizon_bin_days}` days',
            '',
            '| Approach | Rows | Precision | Recall | F1 | ROC-AUC | Brier | MAE mm | RMSE mm | Bias mm | Correlation |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|',
        ]
        for row in overall:
            values = [
                row.approach,
                str(row.evaluated_rows),
                EvaluationMetricsService._display(row.precision),
                EvaluationMetricsService._display(row.recall),
                EvaluationMetricsService._display(row.f1),
                EvaluationMetricsService._display(row.roc_auc),
                EvaluationMetricsService._display(row.brier_score),
                EvaluationMetricsService._display(row.mae_mm),
                EvaluationMetricsService._display(row.rmse_mm),
                EvaluationMetricsService._display(row.bias_mm),
                EvaluationMetricsService._display(row.correlation),
            ]
            lines.append('| ' + ' | '.join(values) + ' |')
        lines.extend(
            [
                '',
                '## Interpretation limits',
                '',
                '- These results use ERA5 reanalysis, not a local rain gauge.',
                '- Wet probabilities are empirical model outputs and are not calibrated for public forecasts.',
                '- Month, season, and horizon rows are available in `evaluation_metrics.csv`.',
                '- Reliability-bin evidence is available in `evaluation_reliability.csv`.',
                '- T6.4 must add rolling temporal validation and uncertainty before scientific conclusions.',
                '',
            ]
        )
        return '\n'.join(lines).encode('utf-8')

    @staticmethod
    def _display(value: float | None) -> str:
        return '—' if value is None else f'{value:.6f}'.rstrip('0').rstrip('.')

    @staticmethod
    def _file_details(content: bytes, rows: int | None) -> dict[str, object]:
        details: dict[str, object] = {
            'sha256': hashlib.sha256(content).hexdigest()
        }
        if rows is not None:
            details['rows'] = rows
        return details

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        temporary = path.parent / f'.{path.name}.{uuid4().hex}.tmp'
        try:
            temporary.write_bytes(content)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='Evaluate T6.2 matched baseline predictions for T6.3'
    )
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--classification-threshold-pct', type=float, default=50.0)
    parser.add_argument('--reliability-bin-count', type=int, default=10)
    parser.add_argument('--horizon-bin-days', type=int, default=30)
    return parser


def main() -> None:
    args = _parser().parse_args()
    spec = EvaluationMetricSpec(
        classification_threshold_pct=args.classification_threshold_pct,
        reliability_bin_count=args.reliability_bin_count,
        horizon_bin_days=args.horizon_bin_days,
    )
    artifact = EvaluationMetricsService().build(
        args.predictions,
        args.manifest,
        args.output,
        spec,
    )
    print(
        f'Built {artifact.metric_rows} metric rows and '
        f'{artifact.reliability_rows} reliability rows at '
        f'{artifact.metrics_path}; evaluation_key={artifact.evaluation_key}'
    )


if __name__ == '__main__':
    main()
