"""Expanding-window, as-of T6.4 validation over T6.1 historical data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from uuid import uuid4

from karuvottam.baseline_comparison import (
    APPROACHES,
    COMBINED_MODEL_VERSION,
    KARUVOTTAM_MODEL_VERSION,
    SEASONAL_MODEL_VERSION,
    BaselineComparisonEngine,
    BaselineComparisonSpec,
    BaselinePrediction,
    DatasetExample,
    EvaluationDatasetReader,
)
from karuvottam.evaluation_metrics import (
    EVALUATION_VERSION,
    EvaluationMetricSpec,
    EvaluationMetricsEngine,
    EvaluationPrediction,
    MetricRow,
    ReliabilityRow,
)


VALIDATION_VERSION = 'rolling-origin-validation-1.0'
EXTRA_DATASET_COLUMNS = frozenset(
    {
        'dataset_version',
        'dataset_key',
        'season_type',
        'season_year',
        'source_window_key',
        'source_window_start_local',
        'source_window_end_local',
        'calendar_rule_version',
        'timeline_model_version',
        'measurement_contract_version',
    }
)
PREDICTION_COLUMNS = (
    'validation_version',
    'validation_key',
    'fold_key',
    'fold_index',
    'training_start_year',
    'training_end_year',
    'evaluation_year',
    'as_of_cutoff_local',
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
    'source_quality_flag',
    'target_quality_flag',
    'observed_precipitation_mm',
    'observed_wet_day',
    'predicted_precipitation_mm',
    'predicted_wet_probability_pct',
    'status',
    'reason_code',
    'training_candidate_count',
    'neighbor_count',
)
FOLD_COLUMNS = (
    'validation_version',
    'validation_key',
    'fold_key',
    'fold_index',
    'training_start_year',
    'training_end_year',
    'evaluation_year',
    'season_type',
    'source_window_key',
    'as_of_cutoff_local',
    'latest_eligible_training_outcome',
    'eligible_training_outcomes',
    'excluded_not_yet_observed_outcomes',
    'evaluation_rows',
    'prediction_rows',
    'leakage_check',
)
METRIC_COLUMNS = (
    'validation_version',
    'validation_key',
    'scope',
    'fold_key',
    'evaluation_year',
    *MetricRow.__dataclass_fields__.keys(),
)
RELIABILITY_COLUMNS = (
    'validation_version',
    'validation_key',
    'scope',
    'fold_key',
    'evaluation_year',
    *ReliabilityRow.__dataclass_fields__.keys(),
)


@dataclass(frozen=True)
class RollingValidationSpec:
    training_start_year: int
    first_evaluation_year: int
    last_evaluation_year: int
    wet_day_threshold_mm: float = 0.1
    karuvottam_neighbors: int = 3
    combined_neighbors: int = 25
    classification_threshold_pct: float = 50.0
    reliability_bin_count: int = 10
    horizon_bin_days: int = 30

    def __post_init__(self) -> None:
        if self.training_start_year < 1:
            raise ValueError('training_start_year must be positive')
        if self.first_evaluation_year <= self.training_start_year:
            raise ValueError('first evaluation year must follow training start year')
        if self.last_evaluation_year < self.first_evaluation_year:
            raise ValueError('evaluation year range is invalid')
        BaselineComparisonSpec(
            self.training_start_year,
            self.first_evaluation_year - 1,
            self.first_evaluation_year,
            self.first_evaluation_year,
            self.wet_day_threshold_mm,
            self.karuvottam_neighbors,
            self.combined_neighbors,
        )
        self.metric_spec()

    def metric_spec(self) -> EvaluationMetricSpec:
        return EvaluationMetricSpec(
            classification_threshold_pct=self.classification_threshold_pct,
            reliability_bin_count=self.reliability_bin_count,
            horizon_bin_days=self.horizon_bin_days,
        )


@dataclass(frozen=True)
class SourceWindowMetadata:
    dataset_version: str
    dataset_key: str
    season_type: str
    season_year: int
    source_window_key: str
    start_local: datetime
    end_local: datetime
    calendar_rule_version: str
    timeline_model_version: str
    measurement_contract_version: str


@dataclass(frozen=True)
class ValidationDataset:
    examples: tuple[DatasetExample, ...]
    source_manifest: Mapping[str, object]
    dataset_sha256: str
    windows: Mapping[str, SourceWindowMetadata]
    dataset_version: str
    calendar_rule_version: str
    timeline_model_version: str
    measurement_contract_version: str


@dataclass(frozen=True)
class FoldAudit:
    fold_key: str
    fold_index: int
    training_start_year: int
    training_end_year: int
    evaluation_year: int
    season_type: str
    source_window_key: str
    as_of_cutoff_local: datetime
    latest_eligible_training_outcome: date | None
    eligible_training_outcomes: int
    excluded_not_yet_observed_outcomes: int
    evaluation_rows: int
    prediction_rows: int
    leakage_check: str = 'passed'


@dataclass(frozen=True)
class ScopedMetric:
    scope: str
    fold_key: str
    evaluation_year: int | None
    metric: MetricRow


@dataclass(frozen=True)
class ScopedReliability:
    scope: str
    fold_key: str
    evaluation_year: int | None
    reliability: ReliabilityRow


@dataclass(frozen=True)
class ValidationPrediction:
    fold_key: str
    fold_index: int
    training_start_year: int
    training_end_year: int
    evaluation_year: int
    as_of_cutoff_local: datetime
    prediction: BaselinePrediction


@dataclass(frozen=True)
class TimeSeriesValidationArtifact:
    validation_key: str
    predictions_path: Path
    folds_path: Path
    metrics_path: Path
    reliability_path: Path
    summary_path: Path
    manifest_path: Path
    fold_count: int
    prediction_rows: int
    evaluated_predictions: int
    leakage_checks: int


def _aware_datetime(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError(f'{field_name} must be an ISO datetime') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f'{field_name} must be timezone-aware')
    return parsed


def _single(values: set[str], field_name: str) -> str:
    if len(values) != 1:
        raise ValueError(f'{field_name} must contain exactly one version')
    value = next(iter(values))
    if not value:
        raise ValueError(f'{field_name} must not be blank')
    return value


class ValidationDatasetReader:
    """Verify T6.1 data and retain source-window as-of/version metadata."""

    def __init__(self, reader: EvaluationDatasetReader | None = None) -> None:
        self.reader = reader or EvaluationDatasetReader()

    def read(
        self,
        dataset_path: str | Path,
        manifest_path: str | Path,
    ) -> ValidationDataset:
        examples, manifest, digest = self.reader.read(dataset_path, manifest_path)
        content = Path(dataset_path).read_text(encoding='utf-8')
        reader = csv.DictReader(io.StringIO(content))
        missing = sorted(
            EXTRA_DATASET_COLUMNS - frozenset(reader.fieldnames or ())
        )
        if missing:
            raise ValueError(
                f'evaluation dataset is missing validation columns: {missing}'
            )
        windows: dict[str, SourceWindowMetadata] = {}
        dataset_versions: set[str] = set()
        calendar_versions: set[str] = set()
        timeline_versions: set[str] = set()
        measurement_versions: set[str] = set()
        manifest_key = manifest.get('dataset_key')
        for row_number, row in enumerate(reader, start=2):
            if row['dataset_key'] != manifest_key:
                raise ValueError(f'row {row_number} has a different dataset_key')
            try:
                season_year = int(row['season_year'])
            except ValueError as exc:
                raise ValueError('season_year must be an integer') from exc
            start = _aware_datetime(
                row['source_window_start_local'], 'source_window_start_local'
            )
            end = _aware_datetime(
                row['source_window_end_local'], 'source_window_end_local'
            )
            if end <= start:
                raise ValueError('source window end must follow its start')
            metadata = SourceWindowMetadata(
                dataset_version=row['dataset_version'],
                dataset_key=row['dataset_key'],
                season_type=row['season_type'],
                season_year=season_year,
                source_window_key=row['source_window_key'],
                start_local=start,
                end_local=end,
                calendar_rule_version=row['calendar_rule_version'],
                timeline_model_version=row['timeline_model_version'],
                measurement_contract_version=row[
                    'measurement_contract_version'
                ],
            )
            previous = windows.setdefault(metadata.source_window_key, metadata)
            if previous != metadata:
                raise ValueError(
                    'source window metadata changes within the same key'
                )
            dataset_versions.add(metadata.dataset_version)
            calendar_versions.add(metadata.calendar_rule_version)
            timeline_versions.add(metadata.timeline_model_version)
            measurement_versions.add(metadata.measurement_contract_version)
        if {example.source_window_key for example in examples} != set(windows):
            raise ValueError('source-window metadata does not match dataset examples')
        dataset_version = _single(dataset_versions, 'dataset_version')
        if manifest.get('dataset_version') != dataset_version:
            raise ValueError('dataset version does not match its manifest')
        return ValidationDataset(
            examples=examples,
            source_manifest=manifest,
            dataset_sha256=digest,
            windows=windows,
            dataset_version=dataset_version,
            calendar_rule_version=_single(
                calendar_versions, 'calendar_rule_version'
            ),
            timeline_model_version=_single(
                timeline_versions, 'timeline_model_version'
            ),
            measurement_contract_version=_single(
                measurement_versions, 'measurement_contract_version'
            ),
        )


class TimeSeriesValidationService:
    def __init__(
        self,
        reader: ValidationDatasetReader | None = None,
    ) -> None:
        self.reader = reader or ValidationDatasetReader()

    def build(
        self,
        dataset_path: str | Path,
        dataset_manifest_path: str | Path,
        output_directory: str | Path,
        spec: RollingValidationSpec,
        *,
        built_at: datetime | None = None,
    ) -> TimeSeriesValidationArtifact:
        built_value = built_at or datetime.now(timezone.utc)
        if built_value.tzinfo is None or built_value.utcoffset() is None:
            raise ValueError('built_at must be timezone-aware')
        dataset = self.reader.read(dataset_path, dataset_manifest_path)
        self._validate_requested_years(dataset, spec)
        validation_key = self._validation_key(dataset, spec)
        metric_engine = EvaluationMetricsEngine(spec.metric_spec())
        validation_predictions: list[ValidationPrediction] = []
        evaluation_predictions: list[EvaluationPrediction] = []
        audits: list[FoldAudit] = []
        scoped_metrics: list[ScopedMetric] = []
        scoped_reliability: list[ScopedReliability] = []

        for fold_index, evaluation_year in enumerate(
            range(spec.first_evaluation_year, spec.last_evaluation_year + 1),
            start=1,
        ):
            fold_key = f'{validation_key}:year-{evaluation_year}'
            windows = sorted(
                (
                    window
                    for window in dataset.windows.values()
                    if window.season_year == evaluation_year
                ),
                key=lambda item: (item.start_local, item.source_window_key),
            )
            cutoffs = {
                window.source_window_key: window.start_local.date()
                for window in windows
            }
            comparison_spec = BaselineComparisonSpec(
                training_start_year=spec.training_start_year,
                training_end_year=evaluation_year - 1,
                evaluation_start_year=evaluation_year,
                evaluation_end_year=evaluation_year,
                wet_day_threshold_mm=spec.wet_day_threshold_mm,
                karuvottam_neighbors=spec.karuvottam_neighbors,
                combined_neighbors=spec.combined_neighbors,
            )
            fold_predictions = BaselineComparisonEngine(comparison_spec).run(
                dataset.examples,
                training_outcome_cutoffs=cutoffs,
            )
            fold_evaluation = tuple(
                self._evaluation_prediction(
                    item, validation_key, dataset.dataset_sha256, spec
                )
                for item in fold_predictions
            )
            metrics, reliability = metric_engine.evaluate(fold_evaluation)
            scoped_metrics.extend(
                ScopedMetric('fold', fold_key, evaluation_year, row)
                for row in metrics
            )
            scoped_reliability.extend(
                ScopedReliability(
                    'fold', fold_key, evaluation_year, row
                )
                for row in reliability
            )
            evaluation_predictions.extend(fold_evaluation)
            for item in fold_predictions:
                window = dataset.windows[item.example.source_window_key]
                validation_predictions.append(
                    ValidationPrediction(
                        fold_key=fold_key,
                        fold_index=fold_index,
                        training_start_year=spec.training_start_year,
                        training_end_year=evaluation_year - 1,
                        evaluation_year=evaluation_year,
                        as_of_cutoff_local=window.start_local,
                        prediction=item,
                    )
                )
            audits.extend(
                self._fold_audits(
                    dataset,
                    spec,
                    fold_key,
                    fold_index,
                    evaluation_year,
                    windows,
                    fold_predictions,
                )
            )

        pooled_metrics, pooled_reliability = metric_engine.evaluate(
            evaluation_predictions
        )
        scoped_metrics.extend(
            ScopedMetric('pooled', 'all-folds', None, row)
            for row in pooled_metrics
        )
        scoped_reliability.extend(
            ScopedReliability('pooled', 'all-folds', None, row)
            for row in pooled_reliability
        )
        output = Path(output_directory)
        output.mkdir(parents=True, exist_ok=True)
        predictions_path = output / 'rolling_predictions.csv'
        folds_path = output / 'rolling_folds.csv'
        metrics_path = output / 'rolling_metrics.csv'
        reliability_path = output / 'rolling_reliability.csv'
        summary_path = output / 'rolling_summary.md'
        manifest_path = output / 'validation_manifest.json'
        contents = {
            predictions_path: self._predictions_csv(
                validation_predictions,
                validation_key,
                dataset.dataset_sha256,
                spec,
            ),
            folds_path: self._folds_csv(audits, validation_key),
            metrics_path: self._metrics_csv(scoped_metrics, validation_key),
            reliability_path: self._reliability_csv(
                scoped_reliability, validation_key
            ),
            summary_path: self._summary(
                scoped_metrics, validation_key, dataset, spec
            ),
        }
        for path, content in contents.items():
            self._write_atomic(path, content)
        evaluated = sum(item.evaluable for item in evaluation_predictions)
        manifest = self._manifest(
            validation_key,
            dataset,
            dataset_manifest_path,
            spec,
            built_value,
            validation_predictions,
            audits,
            scoped_metrics,
            scoped_reliability,
            evaluated,
            contents,
        )
        self._write_atomic(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(),
        )
        return TimeSeriesValidationArtifact(
            validation_key=validation_key,
            predictions_path=predictions_path,
            folds_path=folds_path,
            metrics_path=metrics_path,
            reliability_path=reliability_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            fold_count=spec.last_evaluation_year - spec.first_evaluation_year + 1,
            prediction_rows=len(validation_predictions),
            evaluated_predictions=evaluated,
            leakage_checks=len(audits),
        )

    @staticmethod
    def _validate_requested_years(
        dataset: ValidationDataset,
        spec: RollingValidationSpec,
    ) -> None:
        available = {example.season_year for example in dataset.examples}
        required = set(
            range(spec.training_start_year, spec.last_evaluation_year + 1)
        )
        missing = sorted(required - available)
        if missing:
            raise ValueError(f'dataset is missing requested season years: {missing}')
        for year in range(
            spec.first_evaluation_year, spec.last_evaluation_year + 1
        ):
            seasons = {
                window.season_type
                for window in dataset.windows.values()
                if window.season_year == year
            }
            if seasons != {'aadi', 'margazhi'}:
                raise ValueError(
                    f'evaluation year {year} must contain Aadi and Margazhi windows'
                )

    @staticmethod
    def _evaluation_prediction(
        prediction: BaselinePrediction,
        validation_key: str,
        dataset_sha256: str,
        spec: RollingValidationSpec,
    ) -> EvaluationPrediction:
        example = prediction.example
        observed_wet = (
            None
            if example.observed_precipitation_mm is None
            else int(
                example.observed_precipitation_mm
                >= spec.wet_day_threshold_mm
            )
        )
        return EvaluationPrediction(
            comparison_key=validation_key,
            dataset_key=example.dataset_key,
            dataset_sha256=dataset_sha256,
            approach=prediction.approach,
            model_version=prediction.model_version,
            wet_day_threshold_mm=spec.wet_day_threshold_mm,
            season_type=example.season_type,
            season_year=example.season_year,
            source_window_key=example.source_window_key,
            target_day_number=example.target_day_number,
            target_date_local=date.fromisoformat(example.target_date_local),
            target_quality_flag=example.target_quality_flag,
            observed_precipitation_mm=example.observed_precipitation_mm,
            observed_wet_day=observed_wet,
            predicted_precipitation_mm=prediction.predicted_precipitation_mm,
            predicted_wet_probability_pct=prediction.predicted_wet_probability_pct,
            status=prediction.status,
        )

    @staticmethod
    def _fold_audits(
        dataset: ValidationDataset,
        spec: RollingValidationSpec,
        fold_key: str,
        fold_index: int,
        evaluation_year: int,
        windows: Sequence[SourceWindowMetadata],
        predictions: Sequence[BaselinePrediction],
    ) -> tuple[FoldAudit, ...]:
        nominal_training = tuple(
            example
            for example in dataset.examples
            if spec.training_start_year
            <= example.season_year
            <= evaluation_year - 1
            and example.complete_outcome
        )
        audits = []
        for window in windows:
            cutoff = window.start_local.date()
            eligible = tuple(
                example
                for example in nominal_training
                if date.fromisoformat(example.target_date_local) < cutoff
            )
            excluded = tuple(
                example
                for example in nominal_training
                if date.fromisoformat(example.target_date_local) >= cutoff
            )
            latest = max(
                (
                    date.fromisoformat(example.target_date_local)
                    for example in eligible
                ),
                default=None,
            )
            if latest is not None and latest >= cutoff:
                raise ValueError('training outcome leakage detected')
            evaluation_rows = sum(
                example.source_window_key == window.source_window_key
                for example in dataset.examples
                if example.season_year == evaluation_year
            )
            prediction_rows = sum(
                item.example.source_window_key == window.source_window_key
                for item in predictions
            )
            if prediction_rows != evaluation_rows * len(APPROACHES):
                raise ValueError('fold prediction identities are incomplete')
            audits.append(
                FoldAudit(
                    fold_key=fold_key,
                    fold_index=fold_index,
                    training_start_year=spec.training_start_year,
                    training_end_year=evaluation_year - 1,
                    evaluation_year=evaluation_year,
                    season_type=window.season_type,
                    source_window_key=window.source_window_key,
                    as_of_cutoff_local=window.start_local,
                    latest_eligible_training_outcome=latest,
                    eligible_training_outcomes=len(eligible),
                    excluded_not_yet_observed_outcomes=len(excluded),
                    evaluation_rows=evaluation_rows,
                    prediction_rows=prediction_rows,
                )
            )
        return tuple(audits)

    @staticmethod
    def _validation_key(
        dataset: ValidationDataset,
        spec: RollingValidationSpec,
    ) -> str:
        identity = {
            'validation_version': VALIDATION_VERSION,
            'evaluation_metrics_version': EVALUATION_VERSION,
            'dataset_key': dataset.source_manifest.get('dataset_key'),
            'dataset_sha256': dataset.dataset_sha256,
            'calendar_rule_version': dataset.calendar_rule_version,
            'timeline_model_version': dataset.timeline_model_version,
            'measurement_contract_version': dataset.measurement_contract_version,
            'models': TimeSeriesValidationService._model_versions(),
            'spec': asdict(spec),
        }
        encoded = json.dumps(
            identity, sort_keys=True, separators=(',', ':')
        ).encode()
        return f'{VALIDATION_VERSION}:{hashlib.sha256(encoded).hexdigest()[:16]}'

    @staticmethod
    def _model_versions() -> dict[str, str]:
        return {
            'seasonal_climatology': SEASONAL_MODEL_VERSION,
            'karuvottam_only': KARUVOTTAM_MODEL_VERSION,
            'combined': COMBINED_MODEL_VERSION,
        }

    @staticmethod
    def _predictions_csv(
        rows: Sequence[ValidationPrediction],
        validation_key: str,
        dataset_sha256: str,
        spec: RollingValidationSpec,
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=PREDICTION_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for row in rows:
            item = row.prediction
            example = item.example
            observed_wet = (
                ''
                if example.observed_precipitation_mm is None
                else int(
                    example.observed_precipitation_mm
                    >= spec.wet_day_threshold_mm
                )
            )
            writer.writerow(
                {
                    'validation_version': VALIDATION_VERSION,
                    'validation_key': validation_key,
                    'fold_key': row.fold_key,
                    'fold_index': row.fold_index,
                    'training_start_year': row.training_start_year,
                    'training_end_year': row.training_end_year,
                    'evaluation_year': row.evaluation_year,
                    'as_of_cutoff_local': row.as_of_cutoff_local.isoformat(),
                    'dataset_key': example.dataset_key,
                    'dataset_sha256': dataset_sha256,
                    'approach': item.approach,
                    'model_version': item.model_version,
                    'wet_day_threshold_mm': spec.wet_day_threshold_mm,
                    'season_type': example.season_type,
                    'season_year': example.season_year,
                    'source_window_key': example.source_window_key,
                    'target_day_number': example.target_day_number,
                    'target_date_local': example.target_date_local,
                    'source_quality_flag': example.source_quality_flag,
                    'target_quality_flag': example.target_quality_flag,
                    'observed_precipitation_mm': example.observed_precipitation_mm,
                    'observed_wet_day': observed_wet,
                    'predicted_precipitation_mm': item.predicted_precipitation_mm,
                    'predicted_wet_probability_pct': item.predicted_wet_probability_pct,
                    'status': item.status,
                    'reason_code': item.reason_code,
                    'training_candidate_count': item.training_candidate_count,
                    'neighbor_count': item.neighbor_count,
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _folds_csv(
        rows: Sequence[FoldAudit], validation_key: str
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=FOLD_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    'validation_version': VALIDATION_VERSION,
                    'validation_key': validation_key,
                    **asdict(row),
                    'as_of_cutoff_local': row.as_of_cutoff_local.isoformat(),
                    'latest_eligible_training_outcome': (
                        ''
                        if row.latest_eligible_training_outcome is None
                        else row.latest_eligible_training_outcome.isoformat()
                    ),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _metrics_csv(
        rows: Sequence[ScopedMetric], validation_key: str
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=METRIC_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    'validation_version': VALIDATION_VERSION,
                    'validation_key': validation_key,
                    'scope': row.scope,
                    'fold_key': row.fold_key,
                    'evaluation_year': row.evaluation_year,
                    **asdict(row.metric),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _reliability_csv(
        rows: Sequence[ScopedReliability], validation_key: str
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=RELIABILITY_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    'validation_version': VALIDATION_VERSION,
                    'validation_key': validation_key,
                    'scope': row.scope,
                    'fold_key': row.fold_key,
                    'evaluation_year': row.evaluation_year,
                    **asdict(row.reliability),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _summary(
        rows: Sequence[ScopedMetric],
        validation_key: str,
        dataset: ValidationDataset,
        spec: RollingValidationSpec,
    ) -> bytes:
        pooled = {
            row.metric.approach: row.metric
            for row in rows
            if row.scope == 'pooled'
            and row.metric.dimension == 'overall'
        }
        fold_overall = {
            approach: [
                row.metric
                for row in rows
                if row.scope == 'fold'
                and row.metric.dimension == 'overall'
                and row.metric.approach == approach
            ]
            for approach in APPROACHES
        }
        lines = [
            '# T6.4 rolling-origin validation summary',
            '',
            f'- Validation: `{validation_key}`',
            f'- Dataset: `{dataset.source_manifest.get("dataset_key")}`',
            f'- Training begins: `{spec.training_start_year}`',
            f'- Evaluation folds: `{spec.first_evaluation_year}–{spec.last_evaluation_year}`',
            '- Training outcomes are admitted only when their target date is before each source-window start.',
            '',
            '| Approach | Pooled rows | F1 | ROC-AUC | Brier | MAE mm | RMSE mm | Fold F1 range | Fold Brier range |',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|',
        ]
        for approach in APPROACHES:
            metric = pooled[approach]
            fold_rows = fold_overall[approach]
            lines.append(
                '| '
                + ' | '.join(
                    (
                        approach,
                        str(metric.evaluated_rows),
                        TimeSeriesValidationService._display(metric.f1),
                        TimeSeriesValidationService._display(metric.roc_auc),
                        TimeSeriesValidationService._display(metric.brier_score),
                        TimeSeriesValidationService._display(metric.mae_mm),
                        TimeSeriesValidationService._display(metric.rmse_mm),
                        TimeSeriesValidationService._range(
                            [row.f1 for row in fold_rows]
                        ),
                        TimeSeriesValidationService._range(
                            [row.brier_score for row in fold_rows]
                        ),
                    )
                )
                + ' |'
            )
        lines.extend(
            [
                '',
                '## Guardrails and limits',
                '',
                '- Every fold trains only on earlier season years.',
                '- Per-window as-of cutoffs exclude outcomes not yet observed at forecast time.',
                '- Feature scaling and neighbour selection are refit inside every fold after the cutoff.',
                '- All dataset, rule, measurement, metric, validation, and model versions are recorded in the manifest.',
                '- ERA5 is reanalysis rather than a local rain gauge.',
                '- These empirical probabilities remain unpublished; calibration evidence and the publication gate are separate.',
                '- T6.5 should interpret incremental value and uncertainty without unsupported accuracy claims.',
                '',
            ]
        )
        return '\n'.join(lines).encode('utf-8')

    @staticmethod
    def _display(value: float | None) -> str:
        return '—' if value is None else f'{value:.6f}'.rstrip('0').rstrip('.')

    @staticmethod
    def _range(values: Sequence[float | None]) -> str:
        available = [value for value in values if value is not None]
        if not available:
            return '—'
        return (
            f'{min(available):.6f}'.rstrip('0').rstrip('.')
            + '–'
            + f'{max(available):.6f}'.rstrip('0').rstrip('.')
        )

    @staticmethod
    def _manifest(
        validation_key: str,
        dataset: ValidationDataset,
        dataset_manifest_path: str | Path,
        spec: RollingValidationSpec,
        built_at: datetime,
        predictions: Sequence[ValidationPrediction],
        audits: Sequence[FoldAudit],
        metrics: Sequence[ScopedMetric],
        reliability: Sequence[ScopedReliability],
        evaluated: int,
        contents: Mapping[Path, bytes],
    ) -> dict[str, object]:
        return {
            'validation_version': VALIDATION_VERSION,
            'validation_key': validation_key,
            'built_at_utc': built_at.astimezone(timezone.utc).isoformat().replace(
                '+00:00', 'Z'
            ),
            'source_dataset': {
                'dataset_key': dataset.source_manifest.get('dataset_key'),
                'dataset_version': dataset.dataset_version,
                'dataset_sha256': dataset.dataset_sha256,
                'manifest_path': str(Path(dataset_manifest_path)),
            },
            'versions': {
                'calendar_rule': dataset.calendar_rule_version,
                'timeline_model': dataset.timeline_model_version,
                'measurement_contract': dataset.measurement_contract_version,
                'evaluation_metrics': EVALUATION_VERSION,
                'validation': VALIDATION_VERSION,
                'models': TimeSeriesValidationService._model_versions(),
            },
            'spec': asdict(spec),
            'guardrails': [
                'Every evaluation year is strictly later than its nominal training years.',
                'Each source window has its own as-of cutoff at source_window_start_local.',
                'Training target dates must be strictly earlier than the applicable cutoff.',
                'Feature scaling and neighbour selection are refit using cutoff-eligible training rows only.',
                'Evaluation outcomes are retained for scoring but are never passed to prediction functions.',
                'The same out-of-fold identities are emitted for all three approaches.',
            ],
            'publication_state': {
                'probability_output_enabled': False,
                'reason': 'rolling_validation_does_not_replace_probability_calibration_gate',
            },
            'counts': {
                'folds': spec.last_evaluation_year
                - spec.first_evaluation_year
                + 1,
                'source_window_leakage_checks': len(audits),
                'prediction_rows': len(predictions),
                'evaluated_predictions': evaluated,
                'metric_rows': len(metrics),
                'reliability_rows': len(reliability),
            },
            'files': {
                path.name: {
                    'sha256': hashlib.sha256(content).hexdigest(),
                    **(
                        {'rows': len(content.decode('utf-8').splitlines()) - 1}
                        if path.suffix == '.csv'
                        else {}
                    ),
                }
                for path, content in contents.items()
            },
        }

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
        description='Run expanding, as-of rolling-origin validation for T6.4'
    )
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--training-start-year', type=int, required=True)
    parser.add_argument('--first-evaluation-year', type=int, required=True)
    parser.add_argument('--last-evaluation-year', type=int, required=True)
    parser.add_argument('--wet-day-threshold-mm', type=float, default=0.1)
    parser.add_argument('--karuvottam-neighbors', type=int, default=3)
    parser.add_argument('--combined-neighbors', type=int, default=25)
    parser.add_argument('--classification-threshold-pct', type=float, default=50.0)
    parser.add_argument('--reliability-bin-count', type=int, default=10)
    parser.add_argument('--horizon-bin-days', type=int, default=30)
    return parser


def main() -> None:
    args = _parser().parse_args()
    spec = RollingValidationSpec(
        training_start_year=args.training_start_year,
        first_evaluation_year=args.first_evaluation_year,
        last_evaluation_year=args.last_evaluation_year,
        wet_day_threshold_mm=args.wet_day_threshold_mm,
        karuvottam_neighbors=args.karuvottam_neighbors,
        combined_neighbors=args.combined_neighbors,
        classification_threshold_pct=args.classification_threshold_pct,
        reliability_bin_count=args.reliability_bin_count,
        horizon_bin_days=args.horizon_bin_days,
    )
    artifact = TimeSeriesValidationService().build(
        args.dataset,
        args.manifest,
        args.output,
        spec,
    )
    print(
        f'Built {artifact.fold_count} rolling folds, '
        f'{artifact.prediction_rows} predictions, and '
        f'{artifact.leakage_checks} source-window leakage checks at '
        f'{artifact.summary_path}; validation_key={artifact.validation_key}'
    )


if __name__ == '__main__':
    main()
