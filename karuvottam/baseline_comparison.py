"""Deterministic baseline predictions over a T6.1 evaluation dataset."""

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
from statistics import fmean, pstdev
from typing import Mapping, Sequence
from uuid import uuid4


COMPARISON_VERSION = 'baseline-comparison-1.0'
SEASONAL_MODEL_VERSION = 'seasonal-climatology-1.0'
KARUVOTTAM_MODEL_VERSION = 'karuvottam-knn-1.0'
COMBINED_MODEL_VERSION = 'combined-knn-1.0'
APPROACHES = ('seasonal_climatology', 'karuvottam_only', 'combined')
SOURCE_FEATURES = (
    'source_precipitation_mm',
    'source_mean_temperature_c',
    'source_mean_relative_humidity_pct',
    'source_mean_cloud_cover_pct',
    'source_mean_wind_speed_kmh',
)
REQUIRED_COLUMNS = frozenset(
    {
        'dataset_version',
        'dataset_key',
        'season_type',
        'season_year',
        'source_window_key',
        'target_day_number',
        'target_date_local',
        'source_quality_flag',
        'target_quality_flag',
        'observed_precipitation_mm',
        *SOURCE_FEATURES,
    }
)
OUTPUT_COLUMNS = (
    'comparison_version',
    'comparison_key',
    'dataset_key',
    'dataset_sha256',
    'approach',
    'model_version',
    'training_start_year',
    'training_end_year',
    'evaluation_start_year',
    'evaluation_end_year',
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


@dataclass(frozen=True)
class BaselineComparisonSpec:
    training_start_year: int
    training_end_year: int
    evaluation_start_year: int
    evaluation_end_year: int
    wet_day_threshold_mm: float = 0.1
    karuvottam_neighbors: int = 3
    combined_neighbors: int = 25

    def __post_init__(self) -> None:
        if self.training_start_year < 1:
            raise ValueError('training_start_year must be positive')
        if self.training_end_year < self.training_start_year:
            raise ValueError('training year range is invalid')
        if self.evaluation_start_year <= self.training_end_year:
            raise ValueError('evaluation years must begin after training years')
        if self.evaluation_end_year < self.evaluation_start_year:
            raise ValueError('evaluation year range is invalid')
        if self.wet_day_threshold_mm < 0:
            raise ValueError('wet_day_threshold_mm must not be negative')
        if self.karuvottam_neighbors < 1 or self.combined_neighbors < 1:
            raise ValueError('neighbor counts must be positive')


@dataclass(frozen=True)
class DatasetExample:
    dataset_key: str
    season_type: str
    season_year: int
    source_window_key: str
    target_day_number: int
    target_date_local: str
    target_month: int
    source_quality_flag: str
    target_quality_flag: str
    observed_precipitation_mm: float | None
    source_features: tuple[float | None, ...]

    @property
    def complete_source(self) -> bool:
        return self.source_quality_flag == 'complete' and all(
            value is not None for value in self.source_features
        )

    @property
    def complete_outcome(self) -> bool:
        return (
            self.target_quality_flag == 'complete'
            and self.observed_precipitation_mm is not None
        )


@dataclass(frozen=True)
class BaselinePrediction:
    approach: str
    model_version: str
    example: DatasetExample
    predicted_precipitation_mm: float | None
    predicted_wet_probability_pct: float | None
    status: str
    reason_code: str | None
    training_candidate_count: int
    neighbor_count: int


@dataclass(frozen=True)
class BaselineComparisonArtifact:
    comparison_key: str
    predictions_path: Path
    manifest_path: Path
    predictions_sha256: str
    evaluation_rows: int
    prediction_rows: int
    available_predictions: int
    unavailable_predictions: int


def _optional_float(value: str, field_name: str) -> float | None:
    if value == '':
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f'{field_name} must be numeric or blank') from exc
    if not math.isfinite(parsed):
        raise ValueError(f'{field_name} must be finite')
    return parsed


def _integer(value: str, field_name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f'{field_name} must be an integer') from exc


def _mean_amount(examples: Sequence[DatasetExample]) -> float:
    return round(
        fmean(
            example.observed_precipitation_mm
            for example in examples
            if example.observed_precipitation_mm is not None
        ),
        6,
    )


def _wet_probability(
    examples: Sequence[DatasetExample], threshold: float
) -> float:
    wet = sum(
        example.observed_precipitation_mm is not None
        and example.observed_precipitation_mm >= threshold
        for example in examples
    )
    return round(wet / len(examples) * 100, 6)


class EvaluationDatasetReader:
    """Load and checksum-verify the stable T6.1 CSV contract."""

    def read(
        self,
        dataset_csv_path: str | Path,
        manifest_path: str | Path,
    ) -> tuple[tuple[DatasetExample, ...], Mapping[str, object], str]:
        csv_path = Path(dataset_csv_path)
        manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        csv_bytes = csv_path.read_bytes()
        digest = hashlib.sha256(csv_bytes).hexdigest()
        expected_digest = manifest.get('files', {}).get(csv_path.name, {}).get('sha256')
        if expected_digest != digest:
            raise ValueError('evaluation dataset checksum does not match its manifest')
        dataset_key = manifest.get('dataset_key')
        if not isinstance(dataset_key, str) or not dataset_key:
            raise ValueError('manifest dataset_key is missing')

        reader = csv.DictReader(io.StringIO(csv_bytes.decode('utf-8')))
        columns = frozenset(reader.fieldnames or ())
        missing = sorted(REQUIRED_COLUMNS - columns)
        if missing:
            raise ValueError(f'evaluation dataset is missing columns: {missing}')
        examples = []
        seen: set[tuple[str, int, int]] = set()
        for row_number, row in enumerate(reader, start=2):
            if row['dataset_key'] != dataset_key:
                raise ValueError(f'row {row_number} has a different dataset_key')
            season_year = _integer(row['season_year'], 'season_year')
            day_number = _integer(row['target_day_number'], 'target_day_number')
            identity = (row['season_type'], season_year, day_number)
            if identity in seen:
                raise ValueError(f'duplicate evaluation row identity: {identity}')
            seen.add(identity)
            try:
                target_month = datetime.fromisoformat(row['target_date_local']).month
            except ValueError as exc:
                raise ValueError(
                    f'row {row_number} has an invalid target_date_local'
                ) from exc
            examples.append(
                DatasetExample(
                    dataset_key=dataset_key,
                    season_type=row['season_type'],
                    season_year=season_year,
                    source_window_key=row['source_window_key'],
                    target_day_number=day_number,
                    target_date_local=row['target_date_local'],
                    target_month=target_month,
                    source_quality_flag=row['source_quality_flag'],
                    target_quality_flag=row['target_quality_flag'],
                    observed_precipitation_mm=_optional_float(
                        row['observed_precipitation_mm'],
                        'observed_precipitation_mm',
                    ),
                    source_features=tuple(
                        _optional_float(row[name], name) for name in SOURCE_FEATURES
                    ),
                )
            )
        if not examples:
            raise ValueError('evaluation dataset contains no rows')
        return tuple(examples), manifest, digest


class BaselineComparisonEngine:
    """Generate matched preliminary predictions without reading evaluation outcomes."""

    def __init__(self, spec: BaselineComparisonSpec) -> None:
        self.spec = spec

    def run(
        self,
        examples: Sequence[DatasetExample],
        *,
        training_outcome_cutoffs: Mapping[str, date] | None = None,
    ) -> tuple[BaselinePrediction, ...]:
        training = tuple(
            example
            for example in examples
            if self.spec.training_start_year
            <= example.season_year
            <= self.spec.training_end_year
            and example.complete_outcome
        )
        evaluation = tuple(
            example
            for example in examples
            if self.spec.evaluation_start_year
            <= example.season_year
            <= self.spec.evaluation_end_year
        )
        if not training:
            raise ValueError('no complete training outcomes in the requested range')
        if not evaluation:
            raise ValueError('no evaluation rows in the requested range')
        default_scale = (
            None
            if training_outcome_cutoffs is not None
            else self._feature_scale(training)
        )
        predictions: list[BaselinePrediction] = []
        for example in evaluation:
            available_training = training
            scale = default_scale
            if training_outcome_cutoffs is not None:
                cutoff = training_outcome_cutoffs.get(example.source_window_key)
                if cutoff is None:
                    raise ValueError(
                        'training outcome cutoff is missing for evaluation window '
                        f'{example.source_window_key}'
                    )
                if datetime.fromisoformat(example.target_date_local).date() < cutoff:
                    raise ValueError(
                        'evaluation target date precedes its training outcome cutoff'
                    )
                available_training = tuple(
                    candidate
                    for candidate in training
                    if datetime.fromisoformat(candidate.target_date_local).date()
                    < cutoff
                )
                scale = self._feature_scale(available_training)
            assert scale is not None
            predictions.extend(
                (
                    self._seasonal(example, available_training),
                    self._karuvottam(example, available_training, scale),
                    self._combined(example, available_training, scale),
                )
            )
        return tuple(predictions)

    def _seasonal(
        self,
        example: DatasetExample,
        training: Sequence[DatasetExample],
    ) -> BaselinePrediction:
        candidates = tuple(
            row
            for row in training
            if row.season_type == example.season_type
            and row.target_month == example.target_month
        )
        reason = None
        if not candidates:
            candidates = tuple(
                row for row in training if row.season_type == example.season_type
            )
            reason = 'fallback_to_season_climatology'
        return self._aggregate_prediction(
            'seasonal_climatology',
            SEASONAL_MODEL_VERSION,
            example,
            candidates,
            reason_code=reason,
            neighbor_count=0,
        )

    def _karuvottam(
        self,
        example: DatasetExample,
        training: Sequence[DatasetExample],
        scale: Sequence[float],
    ) -> BaselinePrediction:
        if not example.complete_source:
            return self._unavailable(
                'karuvottam_only',
                KARUVOTTAM_MODEL_VERSION,
                example,
                'source_features_unavailable',
            )
        candidates = tuple(
            row
            for row in training
            if row.season_type == example.season_type
            and row.target_day_number == example.target_day_number
            and row.complete_source
        )
        neighbors = self._nearest(
            example,
            candidates,
            scale,
            self.spec.karuvottam_neighbors,
            combined=False,
        )
        return self._aggregate_prediction(
            'karuvottam_only',
            KARUVOTTAM_MODEL_VERSION,
            example,
            neighbors,
            training_candidate_count=len(candidates),
            neighbor_count=len(neighbors),
        )

    def _combined(
        self,
        example: DatasetExample,
        training: Sequence[DatasetExample],
        scale: Sequence[float],
    ) -> BaselinePrediction:
        if not example.complete_source:
            return self._unavailable(
                'combined',
                COMBINED_MODEL_VERSION,
                example,
                'source_features_unavailable',
            )
        candidates = tuple(
            row
            for row in training
            if row.season_type == example.season_type and row.complete_source
        )
        neighbors = self._nearest(
            example,
            candidates,
            scale,
            self.spec.combined_neighbors,
            combined=True,
        )
        return self._aggregate_prediction(
            'combined',
            COMBINED_MODEL_VERSION,
            example,
            neighbors,
            training_candidate_count=len(candidates),
            neighbor_count=len(neighbors),
        )

    def _aggregate_prediction(
        self,
        approach: str,
        model_version: str,
        example: DatasetExample,
        candidates: Sequence[DatasetExample],
        *,
        reason_code: str | None = None,
        training_candidate_count: int | None = None,
        neighbor_count: int = 0,
    ) -> BaselinePrediction:
        if not candidates:
            return self._unavailable(
                approach,
                model_version,
                example,
                'no_training_candidates',
                training_candidate_count=training_candidate_count or 0,
            )
        return BaselinePrediction(
            approach=approach,
            model_version=model_version,
            example=example,
            predicted_precipitation_mm=_mean_amount(candidates),
            predicted_wet_probability_pct=_wet_probability(
                candidates, self.spec.wet_day_threshold_mm
            ),
            status='available',
            reason_code=reason_code,
            training_candidate_count=(
                len(candidates)
                if training_candidate_count is None
                else training_candidate_count
            ),
            neighbor_count=neighbor_count,
        )

    @staticmethod
    def _unavailable(
        approach: str,
        model_version: str,
        example: DatasetExample,
        reason_code: str,
        *,
        training_candidate_count: int = 0,
    ) -> BaselinePrediction:
        return BaselinePrediction(
            approach=approach,
            model_version=model_version,
            example=example,
            predicted_precipitation_mm=None,
            predicted_wet_probability_pct=None,
            status='unavailable',
            reason_code=reason_code,
            training_candidate_count=training_candidate_count,
            neighbor_count=0,
        )

    @staticmethod
    def _feature_scale(training: Sequence[DatasetExample]) -> tuple[float, ...]:
        complete = [example for example in training if example.complete_source]
        if not complete:
            return tuple(1.0 for _ in SOURCE_FEATURES)
        scales = []
        for index in range(len(SOURCE_FEATURES)):
            values = [
                example.source_features[index]
                for example in complete
                if example.source_features[index] is not None
            ]
            standard_deviation = pstdev(values) if len(values) > 1 else 0.0
            scales.append(standard_deviation if standard_deviation > 0 else 1.0)
        return tuple(scales)

    def _nearest(
        self,
        example: DatasetExample,
        candidates: Sequence[DatasetExample],
        scale: Sequence[float],
        count: int,
        *,
        combined: bool,
    ) -> tuple[DatasetExample, ...]:
        distances = []
        for candidate in candidates:
            distance = sum(
                ((left - right) / divisor) ** 2
                for left, right, divisor in zip(
                    example.source_features,
                    candidate.source_features,
                    scale,
                    strict=True,
                )
                if left is not None and right is not None
            )
            if combined:
                angle = 2 * math.pi * (
                    example.target_month - candidate.target_month
                ) / 12
                month_distance = 2 - 2 * math.cos(angle)
                maximum_day = max(
                    1,
                    180 if example.season_type == 'aadi' else 140,
                )
                horizon_distance = (
                    (example.target_day_number - candidate.target_day_number)
                    / maximum_day
                ) ** 2
                distance += month_distance + horizon_distance
            distances.append((distance, candidate.season_year, candidate.target_date_local, candidate))
        distances.sort(key=lambda item: item[:3])
        return tuple(item[3] for item in distances[:count])


class BaselineComparisonService:
    def __init__(
        self,
        reader: EvaluationDatasetReader | None = None,
    ) -> None:
        self.reader = reader or EvaluationDatasetReader()

    def build(
        self,
        dataset_csv_path: str | Path,
        dataset_manifest_path: str | Path,
        output_directory: str | Path,
        spec: BaselineComparisonSpec,
        *,
        built_at: datetime | None = None,
    ) -> BaselineComparisonArtifact:
        built_value = built_at or datetime.now(timezone.utc)
        if built_value.tzinfo is None or built_value.utcoffset() is None:
            raise ValueError('built_at must be timezone-aware')
        examples, source_manifest, dataset_digest = self.reader.read(
            dataset_csv_path, dataset_manifest_path
        )
        predictions = BaselineComparisonEngine(spec).run(examples)
        dataset_key = predictions[0].example.dataset_key
        comparison_key = self._comparison_key(dataset_key, dataset_digest, spec)
        csv_bytes = self._prediction_csv(
            predictions,
            comparison_key,
            dataset_digest,
            spec,
        )
        digest = hashlib.sha256(csv_bytes).hexdigest()
        output = Path(output_directory)
        output.mkdir(parents=True, exist_ok=True)
        predictions_path = output / 'baseline_predictions.csv'
        manifest_path = output / 'baseline_manifest.json'
        self._write_atomic(predictions_path, csv_bytes)
        available = sum(item.status == 'available' for item in predictions)
        evaluation_rows = len(predictions) // len(APPROACHES)
        approach_counts = {
            approach: {
                'rows': sum(item.approach == approach for item in predictions),
                'available': sum(
                    item.approach == approach and item.status == 'available'
                    for item in predictions
                ),
            }
            for approach in APPROACHES
        }
        manifest = {
            'comparison_version': COMPARISON_VERSION,
            'comparison_key': comparison_key,
            'built_at_utc': built_value.astimezone(timezone.utc).isoformat().replace(
                '+00:00', 'Z'
            ),
            'source_dataset': {
                'dataset_key': dataset_key,
                'dataset_version': source_manifest.get('dataset_version'),
                'dataset_sha256': dataset_digest,
                'manifest_path': str(Path(dataset_manifest_path)),
            },
            'split': asdict(spec),
            'models': {
                'seasonal_climatology': {
                    'version': SEASONAL_MODEL_VERSION,
                    'description': 'Training-period mean rainfall and wet frequency by source season and target Gregorian month; season fallback only when a month has no candidates.',
                },
                'karuvottam_only': {
                    'version': KARUVOTTAM_MODEL_VERSION,
                    'description': 'Nearest prior source windows using only aggregated Karuvottam weather features, matched on season and forecast day number.',
                },
                'combined': {
                    'version': COMBINED_MODEL_VERSION,
                    'description': 'Nearest prior rows using Karuvottam source features plus target month and forecast-horizon distance.',
                },
            },
            'guardrails': [
                'Training season years strictly precede every evaluation season year.',
                'Evaluation observed rainfall is copied to output for later scoring but is never passed to prediction functions.',
                'Only complete training outcomes are used.',
                'Empirical wet frequencies are preliminary model estimates, not calibrated public forecast probabilities.',
                'All three approaches are emitted for the same evaluation row identities.',
            ],
            'counts': {
                'evaluation_rows': evaluation_rows,
                'prediction_rows': len(predictions),
                'available_predictions': available,
                'unavailable_predictions': len(predictions) - available,
                'by_approach': approach_counts,
            },
            'files': {
                predictions_path.name: {
                    'sha256': digest,
                    'rows': len(predictions),
                }
            },
        }
        self._write_atomic(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(),
        )
        return BaselineComparisonArtifact(
            comparison_key=comparison_key,
            predictions_path=predictions_path,
            manifest_path=manifest_path,
            predictions_sha256=digest,
            evaluation_rows=evaluation_rows,
            prediction_rows=len(predictions),
            available_predictions=available,
            unavailable_predictions=len(predictions) - available,
        )

    @staticmethod
    def _comparison_key(
        dataset_key: str,
        dataset_digest: str,
        spec: BaselineComparisonSpec,
    ) -> str:
        identity = {
            'comparison_version': COMPARISON_VERSION,
            'dataset_key': dataset_key,
            'dataset_sha256': dataset_digest,
            'spec': asdict(spec),
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()
        return f'{COMPARISON_VERSION}:{hashlib.sha256(encoded).hexdigest()[:16]}'

    @staticmethod
    def _prediction_csv(
        predictions: Sequence[BaselinePrediction],
        comparison_key: str,
        dataset_digest: str,
        spec: BaselineComparisonSpec,
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=OUTPUT_COLUMNS, lineterminator='\n')
        writer.writeheader()
        for prediction in predictions:
            example = prediction.example
            observed_wet = (
                None
                if example.observed_precipitation_mm is None
                else int(
                    example.observed_precipitation_mm
                    >= spec.wet_day_threshold_mm
                )
            )
            writer.writerow(
                {
                    'comparison_version': COMPARISON_VERSION,
                    'comparison_key': comparison_key,
                    'dataset_key': example.dataset_key,
                    'dataset_sha256': dataset_digest,
                    'approach': prediction.approach,
                    'model_version': prediction.model_version,
                    'training_start_year': spec.training_start_year,
                    'training_end_year': spec.training_end_year,
                    'evaluation_start_year': spec.evaluation_start_year,
                    'evaluation_end_year': spec.evaluation_end_year,
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
                    'predicted_precipitation_mm': prediction.predicted_precipitation_mm,
                    'predicted_wet_probability_pct': prediction.predicted_wet_probability_pct,
                    'status': prediction.status,
                    'reason_code': prediction.reason_code,
                    'training_candidate_count': prediction.training_candidate_count,
                    'neighbor_count': prediction.neighbor_count,
                }
            )
        return output.getvalue().encode('utf-8')

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
        description='Generate matched baseline predictions for T6.2'
    )
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--training-start-year', type=int, required=True)
    parser.add_argument('--training-end-year', type=int, required=True)
    parser.add_argument('--evaluation-start-year', type=int, required=True)
    parser.add_argument('--evaluation-end-year', type=int, required=True)
    parser.add_argument('--wet-day-threshold-mm', type=float, default=0.1)
    parser.add_argument('--karuvottam-neighbors', type=int, default=3)
    parser.add_argument('--combined-neighbors', type=int, default=25)
    return parser


def main() -> None:
    args = _parser().parse_args()
    spec = BaselineComparisonSpec(
        training_start_year=args.training_start_year,
        training_end_year=args.training_end_year,
        evaluation_start_year=args.evaluation_start_year,
        evaluation_end_year=args.evaluation_end_year,
        wet_day_threshold_mm=args.wet_day_threshold_mm,
        karuvottam_neighbors=args.karuvottam_neighbors,
        combined_neighbors=args.combined_neighbors,
    )
    artifact = BaselineComparisonService().build(
        args.dataset,
        args.manifest,
        args.output,
        spec,
    )
    print(
        f'Built {artifact.prediction_rows} matched predictions for '
        f'{artifact.evaluation_rows} evaluation rows at '
        f'{artifact.predictions_path}; sha256={artifact.predictions_sha256}'
    )


if __name__ == '__main__':
    main()
