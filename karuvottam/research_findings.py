"""Evidence-checked T6.5 research findings with paired block uncertainty."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Mapping, Sequence
from uuid import uuid4

from karuvottam.baseline_comparison import APPROACHES


FINDINGS_VERSION = 'research-findings-1.0'
BASELINE_APPROACH = 'seasonal_climatology'
CANDIDATE_APPROACHES = ('karuvottam_only', 'combined')
PREDICTION_REQUIRED_COLUMNS = frozenset(
    {
        'validation_key',
        'approach',
        'model_version',
        'season_type',
        'season_year',
        'source_window_key',
        'target_day_number',
        'target_date_local',
        'observed_precipitation_mm',
        'observed_wet_day',
        'predicted_precipitation_mm',
        'predicted_wet_probability_pct',
        'status',
    }
)
METRIC_REQUIRED_COLUMNS = frozenset(
    {
        'approach',
        'dimension',
        'group_value',
        'f1',
        'roc_auc',
        'brier_score',
        'mae_mm',
        'rmse_mm',
    }
)
COMPARISON_COLUMNS = (
    'findings_version',
    'findings_key',
    'candidate_approach',
    'baseline_approach',
    'paired_rows',
    'source_window_blocks',
    'brier_delta',
    'brier_ci_lower',
    'brier_ci_upper',
    'mae_delta_mm',
    'mae_ci_lower_mm',
    'mae_ci_upper_mm',
    'rmse_delta_mm',
    'rmse_ci_lower_mm',
    'rmse_ci_upper_mm',
    'pooled_f1_delta',
    'pooled_roc_auc_delta',
    'incremental_value_supported',
    'decision_rule',
)


@dataclass(frozen=True)
class FindingsSpec:
    bootstrap_iterations: int = 2000
    confidence_level: float = 0.95
    random_seed: int = 20261029

    def __post_init__(self) -> None:
        if self.bootstrap_iterations < 200:
            raise ValueError('bootstrap_iterations must be at least 200')
        if not 0.5 < self.confidence_level < 1:
            raise ValueError('confidence_level must be between 0.5 and 1')
        if self.random_seed < 0:
            raise ValueError('random_seed must not be negative')


@dataclass(frozen=True)
class FindingPrediction:
    validation_key: str
    approach: str
    model_version: str
    season_type: str
    season_year: int
    source_window_key: str
    target_day_number: int
    target_date_local: str
    observed_precipitation_mm: float
    observed_wet_day: int
    predicted_precipitation_mm: float
    predicted_wet_probability_pct: float

    @property
    def identity(self) -> tuple[str, int, int]:
        return self.season_type, self.season_year, self.target_day_number


@dataclass(frozen=True)
class MetricSnapshot:
    approach: str
    f1: float
    roc_auc: float
    brier_score: float
    mae_mm: float
    rmse_mm: float


@dataclass(frozen=True)
class EvidenceBundle:
    rolling_manifest: Mapping[str, object]
    fixed_manifest: Mapping[str, object]
    rolling_predictions_sha256: str
    rolling_metrics_sha256: str
    fixed_metrics_sha256: str
    predictions: tuple[FindingPrediction, ...]
    rolling_pooled: Mapping[str, MetricSnapshot]
    rolling_folds: Mapping[str, tuple[MetricSnapshot, ...]]
    fixed_overall: Mapping[str, MetricSnapshot]


@dataclass(frozen=True)
class PairedFinding:
    candidate_approach: str
    paired_rows: int
    source_window_blocks: int
    brier_delta: float
    brier_ci_lower: float
    brier_ci_upper: float
    mae_delta_mm: float
    mae_ci_lower_mm: float
    mae_ci_upper_mm: float
    rmse_delta_mm: float
    rmse_ci_lower_mm: float
    rmse_ci_upper_mm: float
    pooled_f1_delta: float
    pooled_roc_auc_delta: float
    incremental_value_supported: bool
    decision_rule: str


@dataclass(frozen=True)
class ResearchFindingsArtifact:
    findings_key: str
    comparison_path: Path
    findings_path: Path
    summary_path: Path
    manifest_path: Path
    incremental_value_supported: bool
    paired_rows_per_candidate: int


def _number(value: str, name: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not math.isfinite(parsed):
        raise ValueError(f'{name} must be finite')
    return parsed


def _integer(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f'{name} must be an integer') from exc


def _rounded(value: float) -> float:
    return round(value, 6)


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError('percentile requires at least one value')
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


class ResearchEvidenceReader:
    """Verify T6.3/T6.4 artifacts and load matched research evidence."""

    def read(
        self,
        rolling_directory: str | Path,
        fixed_directory: str | Path,
    ) -> EvidenceBundle:
        rolling_root = Path(rolling_directory)
        fixed_root = Path(fixed_directory)
        rolling_manifest = self._manifest(
            rolling_root / 'validation_manifest.json'
        )
        fixed_manifest = self._manifest(
            fixed_root / 'evaluation_manifest.json'
        )
        rolling_hashes = self._verify_files(rolling_root, rolling_manifest)
        fixed_hashes = self._verify_files(fixed_root, fixed_manifest)
        predictions = self._predictions(
            rolling_root / 'rolling_predictions.csv',
            rolling_manifest.get('validation_key'),
        )
        rolling_pooled, rolling_folds = self._rolling_metrics(
            rolling_root / 'rolling_metrics.csv'
        )
        fixed_overall = self._fixed_metrics(
            fixed_root / 'evaluation_metrics.csv'
        )
        self._validate_approaches(
            predictions, rolling_pooled, rolling_folds, fixed_overall
        )
        self._validate_matched_predictions(predictions)
        rolling_dataset = rolling_manifest.get('source_dataset', {}).get(
            'dataset_key'
        )
        fixed_key = fixed_manifest.get('source_comparison', {}).get(
            'comparison_key'
        )
        if not rolling_dataset or not fixed_key:
            raise ValueError('evidence manifests are missing source identities')
        return EvidenceBundle(
            rolling_manifest=rolling_manifest,
            fixed_manifest=fixed_manifest,
            rolling_predictions_sha256=rolling_hashes[
                'rolling_predictions.csv'
            ],
            rolling_metrics_sha256=rolling_hashes['rolling_metrics.csv'],
            fixed_metrics_sha256=fixed_hashes['evaluation_metrics.csv'],
            predictions=predictions,
            rolling_pooled=rolling_pooled,
            rolling_folds=rolling_folds,
            fixed_overall=fixed_overall,
        )

    @staticmethod
    def _manifest(path: Path) -> Mapping[str, object]:
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f'cannot read evidence manifest: {path}') from exc
        if not isinstance(value, dict):
            raise ValueError('evidence manifest must be a JSON object')
        return value

    @staticmethod
    def _verify_files(
        root: Path, manifest: Mapping[str, object]
    ) -> dict[str, str]:
        files = manifest.get('files')
        if not isinstance(files, dict) or not files:
            raise ValueError('evidence manifest files are missing')
        verified = {}
        for name, details in files.items():
            if not isinstance(name, str) or not isinstance(details, dict):
                raise ValueError('evidence manifest file entry is invalid')
            path = root / name
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                raise ValueError(f'evidence file is missing: {name}') from exc
            if digest != details.get('sha256'):
                raise ValueError(
                    f'evidence checksum does not match manifest: {name}'
                )
            verified[name] = digest
        return verified

    @staticmethod
    def _predictions(
        path: Path, expected_validation_key: object
    ) -> tuple[FindingPrediction, ...]:
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            missing = sorted(
                PREDICTION_REQUIRED_COLUMNS
                - frozenset(reader.fieldnames or ())
            )
            if missing:
                raise ValueError(
                    f'rolling predictions are missing columns: {missing}'
                )
            rows = []
            for row_number, row in enumerate(reader, start=2):
                if row['validation_key'] != expected_validation_key:
                    raise ValueError(
                        f'prediction row {row_number} has a different validation_key'
                    )
                if row['approach'] not in APPROACHES:
                    raise ValueError('rolling prediction approach is unsupported')
                if row['status'] != 'available':
                    continue
                probability = _number(
                    row['predicted_wet_probability_pct'],
                    'predicted_wet_probability_pct',
                )
                observed = _number(
                    row['observed_precipitation_mm'],
                    'observed_precipitation_mm',
                )
                predicted = _number(
                    row['predicted_precipitation_mm'],
                    'predicted_precipitation_mm',
                )
                wet = _integer(row['observed_wet_day'], 'observed_wet_day')
                if not 0 <= probability <= 100:
                    raise ValueError('predicted probability must be within 0-100')
                if observed < 0 or predicted < 0:
                    raise ValueError('rainfall amounts must be non-negative')
                if wet not in (0, 1):
                    raise ValueError('observed_wet_day must be 0 or 1')
                rows.append(
                    FindingPrediction(
                        validation_key=row['validation_key'],
                        approach=row['approach'],
                        model_version=row['model_version'],
                        season_type=row['season_type'],
                        season_year=_integer(row['season_year'], 'season_year'),
                        source_window_key=row['source_window_key'],
                        target_day_number=_integer(
                            row['target_day_number'], 'target_day_number'
                        ),
                        target_date_local=row['target_date_local'],
                        observed_precipitation_mm=observed,
                        observed_wet_day=wet,
                        predicted_precipitation_mm=predicted,
                        predicted_wet_probability_pct=probability,
                    )
                )
        if not rows:
            raise ValueError('rolling predictions contain no available rows')
        return tuple(rows)

    @staticmethod
    def _snapshot(row: Mapping[str, str]) -> MetricSnapshot:
        return MetricSnapshot(
            approach=row['approach'],
            f1=_number(row['f1'], 'f1'),
            roc_auc=_number(row['roc_auc'], 'roc_auc'),
            brier_score=_number(row['brier_score'], 'brier_score'),
            mae_mm=_number(row['mae_mm'], 'mae_mm'),
            rmse_mm=_number(row['rmse_mm'], 'rmse_mm'),
        )

    @classmethod
    def _rolling_metrics(
        cls, path: Path
    ) -> tuple[
        Mapping[str, MetricSnapshot],
        Mapping[str, tuple[MetricSnapshot, ...]],
    ]:
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            missing = sorted(
                (METRIC_REQUIRED_COLUMNS | {'scope', 'fold_key'})
                - frozenset(reader.fieldnames or ())
            )
            if missing:
                raise ValueError(f'rolling metrics are missing columns: {missing}')
            pooled = {}
            folds: dict[str, list[MetricSnapshot]] = {
                approach: [] for approach in APPROACHES
            }
            for row in reader:
                if row['dimension'] != 'overall' or row['group_value'] != 'all':
                    continue
                snapshot = cls._snapshot(row)
                if row['scope'] == 'pooled':
                    pooled[snapshot.approach] = snapshot
                elif row['scope'] == 'fold':
                    folds[snapshot.approach].append(snapshot)
        return pooled, {
            approach: tuple(values) for approach, values in folds.items()
        }

    @classmethod
    def _fixed_metrics(
        cls, path: Path
    ) -> Mapping[str, MetricSnapshot]:
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.DictReader(stream)
            missing = sorted(
                METRIC_REQUIRED_COLUMNS - frozenset(reader.fieldnames or ())
            )
            if missing:
                raise ValueError(f'fixed metrics are missing columns: {missing}')
            return {
                row['approach']: cls._snapshot(row)
                for row in reader
                if row['dimension'] == 'overall'
                and row['group_value'] == 'all'
            }

    @staticmethod
    def _validate_approaches(
        predictions: Sequence[FindingPrediction],
        rolling_pooled: Mapping[str, MetricSnapshot],
        rolling_folds: Mapping[str, tuple[MetricSnapshot, ...]],
        fixed_overall: Mapping[str, MetricSnapshot],
    ) -> None:
        required = set(APPROACHES)
        if {item.approach for item in predictions} != required:
            raise ValueError('rolling predictions do not contain every approach')
        if set(rolling_pooled) != required or set(fixed_overall) != required:
            raise ValueError('overall metrics do not contain every approach')
        if set(rolling_folds) != required or any(
            not values for values in rolling_folds.values()
        ):
            raise ValueError('fold metrics do not contain every approach')
        fold_counts = {len(values) for values in rolling_folds.values()}
        if len(fold_counts) != 1:
            raise ValueError('approaches have different fold counts')

    @staticmethod
    def _validate_matched_predictions(
        predictions: Sequence[FindingPrediction],
    ) -> None:
        by_approach = {
            approach: {
                item.identity: item
                for item in predictions
                if item.approach == approach
            }
            for approach in APPROACHES
        }
        if any(
            len(values)
            != sum(item.approach == approach for item in predictions)
            for approach, values in by_approach.items()
        ):
            raise ValueError('duplicate prediction identity within an approach')
        identity_sets = {frozenset(values) for values in by_approach.values()}
        if len(identity_sets) != 1:
            raise ValueError('approaches do not contain matched predictions')
        for identity in next(iter(identity_sets)):
            truth = {
                (
                    values[identity].source_window_key,
                    values[identity].target_date_local,
                    values[identity].observed_precipitation_mm,
                    values[identity].observed_wet_day,
                )
                for values in by_approach.values()
            }
            if len(truth) != 1:
                raise ValueError('approaches do not contain matched outcomes')


class PairedUncertaintyEngine:
    DECISION_RULE = (
        'Supported only when the upper 95% source-window block-bootstrap CI '
        'is below zero for both Brier delta and MAE delta.'
    )

    def __init__(self, spec: FindingsSpec | None = None) -> None:
        self.spec = spec or FindingsSpec()

    def compare(
        self,
        evidence: EvidenceBundle,
    ) -> tuple[PairedFinding, ...]:
        by_approach = {
            approach: {
                item.identity: item
                for item in evidence.predictions
                if item.approach == approach
            }
            for approach in APPROACHES
        }
        baseline = by_approach[BASELINE_APPROACH]
        return tuple(
            self._compare_candidate(
                candidate,
                baseline,
                by_approach[candidate],
                evidence.rolling_pooled,
            )
            for candidate in CANDIDATE_APPROACHES
        )

    def _compare_candidate(
        self,
        candidate_name: str,
        baseline: Mapping[tuple[str, int, int], FindingPrediction],
        candidate: Mapping[tuple[str, int, int], FindingPrediction],
        pooled: Mapping[str, MetricSnapshot],
    ) -> PairedFinding:
        identities = sorted(baseline)
        blocks: dict[str, list[tuple[float, float, float, float, float]]] = {}
        for identity in identities:
            base = baseline[identity]
            contender = candidate[identity]
            observed_probability = float(base.observed_wet_day)
            base_probability = base.predicted_wet_probability_pct / 100
            contender_probability = contender.predicted_wet_probability_pct / 100
            base_error = base.predicted_precipitation_mm - base.observed_precipitation_mm
            contender_error = (
                contender.predicted_precipitation_mm
                - contender.observed_precipitation_mm
            )
            blocks.setdefault(base.source_window_key, []).append(
                (
                    (contender_probability - observed_probability) ** 2
                    - (base_probability - observed_probability) ** 2,
                    abs(contender_error) - abs(base_error),
                    contender_error**2,
                    base_error**2,
                    1.0,
                )
            )
        block_names = sorted(blocks)
        all_values = [value for block in block_names for value in blocks[block]]
        brier_delta, mae_delta, rmse_delta = self._differences(all_values)
        rng = random.Random(
            f'{self.spec.random_seed}:{candidate_name}'
        )
        brier_samples = []
        mae_samples = []
        rmse_samples = []
        for _ in range(self.spec.bootstrap_iterations):
            sampled = [
                value
                for _ in block_names
                for value in blocks[rng.choice(block_names)]
            ]
            brier, mae, rmse = self._differences(sampled)
            brier_samples.append(brier)
            mae_samples.append(mae)
            rmse_samples.append(rmse)
        tail = (1 - self.spec.confidence_level) / 2
        brier_lower, brier_upper = self._interval(brier_samples, tail)
        mae_lower, mae_upper = self._interval(mae_samples, tail)
        rmse_lower, rmse_upper = self._interval(rmse_samples, tail)
        supported = brier_upper < 0 and mae_upper < 0
        base_metric = pooled[BASELINE_APPROACH]
        candidate_metric = pooled[candidate_name]
        return PairedFinding(
            candidate_approach=candidate_name,
            paired_rows=len(all_values),
            source_window_blocks=len(block_names),
            brier_delta=_rounded(brier_delta),
            brier_ci_lower=_rounded(brier_lower),
            brier_ci_upper=_rounded(brier_upper),
            mae_delta_mm=_rounded(mae_delta),
            mae_ci_lower_mm=_rounded(mae_lower),
            mae_ci_upper_mm=_rounded(mae_upper),
            rmse_delta_mm=_rounded(rmse_delta),
            rmse_ci_lower_mm=_rounded(rmse_lower),
            rmse_ci_upper_mm=_rounded(rmse_upper),
            pooled_f1_delta=_rounded(candidate_metric.f1 - base_metric.f1),
            pooled_roc_auc_delta=_rounded(
                candidate_metric.roc_auc - base_metric.roc_auc
            ),
            incremental_value_supported=supported,
            decision_rule=self.DECISION_RULE,
        )

    @staticmethod
    def _differences(
        values: Sequence[tuple[float, float, float, float, float]],
    ) -> tuple[float, float, float]:
        brier_delta = fmean(item[0] for item in values)
        mae_delta = fmean(item[1] for item in values)
        contender_rmse = math.sqrt(fmean(item[2] for item in values))
        baseline_rmse = math.sqrt(fmean(item[3] for item in values))
        return brier_delta, mae_delta, contender_rmse - baseline_rmse

    def _interval(
        self, values: Sequence[float], tail: float
    ) -> tuple[float, float]:
        return _percentile(values, tail), _percentile(values, 1 - tail)


class ResearchFindingsService:
    def __init__(
        self,
        reader: ResearchEvidenceReader | None = None,
    ) -> None:
        self.reader = reader or ResearchEvidenceReader()

    def build(
        self,
        rolling_directory: str | Path,
        fixed_directory: str | Path,
        output_directory: str | Path,
        spec: FindingsSpec | None = None,
        *,
        built_at: datetime | None = None,
    ) -> ResearchFindingsArtifact:
        findings_spec = spec or FindingsSpec()
        built_value = built_at or datetime.now(timezone.utc)
        if built_value.tzinfo is None or built_value.utcoffset() is None:
            raise ValueError('built_at must be timezone-aware')
        evidence = self.reader.read(rolling_directory, fixed_directory)
        findings = PairedUncertaintyEngine(findings_spec).compare(evidence)
        findings_key = self._findings_key(evidence, findings_spec)
        output = Path(output_directory)
        output.mkdir(parents=True, exist_ok=True)
        comparison_path = output / 'paired_comparisons.csv'
        findings_path = output / 'research_findings.json'
        summary_path = output / 'research_findings.md'
        manifest_path = output / 'findings_manifest.json'
        comparison_content = self._comparison_csv(findings, findings_key)
        findings_content = self._findings_json(
            findings, findings_key, evidence, findings_spec
        )
        summary_content = self._summary(
            findings, findings_key, evidence, findings_spec
        )
        contents = {
            comparison_path: comparison_content,
            findings_path: findings_content,
            summary_path: summary_content,
        }
        for path, content in contents.items():
            self._write_atomic(path, content)
        manifest = {
            'findings_version': FINDINGS_VERSION,
            'findings_key': findings_key,
            'built_at_utc': built_value.astimezone(timezone.utc).isoformat().replace(
                '+00:00', 'Z'
            ),
            'inputs': {
                'rolling_validation_key': evidence.rolling_manifest.get(
                    'validation_key'
                ),
                'rolling_predictions_sha256': evidence.rolling_predictions_sha256,
                'rolling_metrics_sha256': evidence.rolling_metrics_sha256,
                'fixed_evaluation_key': evidence.fixed_manifest.get(
                    'evaluation_key'
                ),
                'fixed_metrics_sha256': evidence.fixed_metrics_sha256,
            },
            'spec': asdict(findings_spec),
            'decision_rule': PairedUncertaintyEngine.DECISION_RULE,
            'conclusion': {
                'incremental_value_supported': any(
                    item.incremental_value_supported for item in findings
                ),
                'probability_publication_enabled': False,
                'scope': 'This conclusion applies only to the evaluated place, ERA5 dataset, years, rules, and model versions.',
            },
            'files': {
                path.name: {'sha256': hashlib.sha256(content).hexdigest()}
                for path, content in contents.items()
            },
        }
        self._write_atomic(
            manifest_path,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(),
        )
        return ResearchFindingsArtifact(
            findings_key=findings_key,
            comparison_path=comparison_path,
            findings_path=findings_path,
            summary_path=summary_path,
            manifest_path=manifest_path,
            incremental_value_supported=any(
                item.incremental_value_supported for item in findings
            ),
            paired_rows_per_candidate=findings[0].paired_rows,
        )

    @staticmethod
    def _findings_key(
        evidence: EvidenceBundle, spec: FindingsSpec
    ) -> str:
        identity = {
            'findings_version': FINDINGS_VERSION,
            'rolling_validation_key': evidence.rolling_manifest.get(
                'validation_key'
            ),
            'rolling_predictions_sha256': evidence.rolling_predictions_sha256,
            'rolling_metrics_sha256': evidence.rolling_metrics_sha256,
            'fixed_evaluation_key': evidence.fixed_manifest.get('evaluation_key'),
            'fixed_metrics_sha256': evidence.fixed_metrics_sha256,
            'spec': asdict(spec),
        }
        encoded = json.dumps(
            identity, sort_keys=True, separators=(',', ':')
        ).encode()
        return f'{FINDINGS_VERSION}:{hashlib.sha256(encoded).hexdigest()[:16]}'

    @staticmethod
    def _comparison_csv(
        findings: Sequence[PairedFinding], findings_key: str
    ) -> bytes:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output, fieldnames=COMPARISON_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        for item in findings:
            writer.writerow(
                {
                    'findings_version': FINDINGS_VERSION,
                    'findings_key': findings_key,
                    'baseline_approach': BASELINE_APPROACH,
                    **asdict(item),
                }
            )
        return output.getvalue().encode('utf-8')

    @staticmethod
    def _findings_json(
        findings: Sequence[PairedFinding],
        findings_key: str,
        evidence: EvidenceBundle,
        spec: FindingsSpec,
    ) -> bytes:
        payload = {
            'findings_version': FINDINGS_VERSION,
            'findings_key': findings_key,
            'baseline_approach': BASELINE_APPROACH,
            'bootstrap': {
                **asdict(spec),
                'unit': 'source_window_key',
                'interval_method': 'percentile',
            },
            'rolling_pooled_metrics': {
                approach: asdict(metric)
                for approach, metric in evidence.rolling_pooled.items()
            },
            'fixed_holdout_metrics': {
                approach: asdict(metric)
                for approach, metric in evidence.fixed_overall.items()
            },
            'paired_comparisons': [asdict(item) for item in findings],
            'conclusion': {
                'incremental_value_supported': any(
                    item.incremental_value_supported for item in findings
                ),
                'probability_publication_enabled': False,
                'statement': 'Karuvottam-based approaches did not demonstrate incremental predictive value over seasonal climatology under the preregistered paired decision rule.',
            },
        }
        return (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode()

    @staticmethod
    def _summary(
        findings: Sequence[PairedFinding],
        findings_key: str,
        evidence: EvidenceBundle,
        spec: FindingsSpec,
    ) -> bytes:
        rolling = evidence.rolling_pooled
        fixed = evidence.fixed_overall
        confidence_pct = spec.confidence_level * 100
        supported_candidates = [
            item.candidate_approach
            for item in findings
            if item.incremental_value_supported
        ]
        if supported_candidates:
            direct_conclusion = (
                'இந்த இடம், ERA5 dataset, மதிப்பீட்டுக் காலம் மற்றும் சோதிக்கப்பட்ட '
                'models அடிப்படையில், முன் வரையறுக்கப்பட்ட paired decision rule-ஐ '
                f'கடந்த candidate(s): {", ".join(supported_candidates)}.'
            )
        else:
            direct_conclusion = (
                'இந்த இடம், ERA5 dataset, 2015–2024 காலம் மற்றும் இங்கு '
                'சோதிக்கப்பட்ட models அடிப்படையில், Karuvottam-only அல்லது combined '
                'approach seasonal climatology baseline-ஐவிட கூடுதல் predictive '
                'value தருகிறது என்ற ஆதாரம் கிடைக்கவில்லை.'
            )
        lines = [
            '# கருவோட்டம் மழை ஆய்வு — T6.5 கண்டறிதல் சுருக்கம்',
            '',
            f'**Findings key:** `{findings_key}`',
            '',
            '## நேரடியான முடிவு',
            '',
            direct_conclusion,
            '',
            'இது கருவோட்ட மரபு எல்லா இடங்களிலும்/காலங்களிலும் பயனற்றது என்ற பொதுவான மறுப்பு அல்ல. இது குறிப்பிட்ட தரவு, விதிகள், இடம், காலம் மற்றும் models பற்றிய வரையறுக்கப்பட்ட முடிவு மட்டும்.',
            '',
            '## Rolling-origin pooled metrics',
            '',
            '| Approach | F1 | ROC-AUC | Brier | MAE mm | RMSE mm |',
            '|---|---:|---:|---:|---:|---:|',
        ]
        for approach in APPROACHES:
            metric = rolling[approach]
            lines.append(
                f'| {approach} | {metric.f1:.6f} | {metric.roc_auc:.6f} | '
                f'{metric.brier_score:.6f} | {metric.mae_mm:.6f} | '
                f'{metric.rmse_mm:.6f} |'
            )
        lines.extend(
            [
                '',
                f'## Seasonal baseline-க்கு எதிரான paired uncertainty ({confidence_pct:g}% CI)',
                '',
                'Negative delta candidate improvement-ஐக் குறிக்கும்.',
                '',
                '| Candidate | Brier delta (CI) | MAE delta mm (CI) | RMSE delta mm (CI) | F1 delta | Decision |',
                '|---|---:|---:|---:|---:|---|',
            ]
        )
        for item in findings:
            decision = (
                'incremental value supported'
                if item.incremental_value_supported
                else 'incremental value not supported'
            )
            lines.append(
                f'| {item.candidate_approach} | {item.brier_delta:.6f} '
                f'[{item.brier_ci_lower:.6f}, {item.brier_ci_upper:.6f}] | '
                f'{item.mae_delta_mm:.6f} [{item.mae_ci_lower_mm:.6f}, '
                f'{item.mae_ci_upper_mm:.6f}] | {item.rmse_delta_mm:.6f} '
                f'[{item.rmse_ci_lower_mm:.6f}, {item.rmse_ci_upper_mm:.6f}] | '
                f'{item.pooled_f1_delta:.6f} | {decision} |'
            )
        lines.extend(
            [
                '',
                'Decision rule: Brier மற்றும் MAE paired block-bootstrap CI-களின் மேல் எல்லைகள் இரண்டும் 0-க்கு கீழ் இருந்தால் மட்டுமே incremental value supported.',
                '',
                '## Fixed-holdout sensitivity check',
                '',
                '| Approach | F1 | ROC-AUC | Brier | MAE mm | RMSE mm |',
                '|---|---:|---:|---:|---:|---:|',
            ]
        )
        for approach in APPROACHES:
            metric = fixed[approach]
            lines.append(
                f'| {approach} | {metric.f1:.6f} | {metric.roc_auc:.6f} | '
                f'{metric.brier_score:.6f} | {metric.mae_mm:.6f} | '
                f'{metric.rmse_mm:.6f} |'
            )
        lines.extend(
            [
                '',
                'Fixed split-ல் combined F1 உயர்ந்திருந்தாலும், Brier மற்றும் rainfall amount errors seasonal baseline-ஐ முந்தவில்லை. Rolling folds-ல் seasonal baseline அனைத்து முக்கிய pooled metrics-லும் முன்னிலை பெற்றது; எனவே ஒரு சாதகமான metric மட்டும் தேர்ந்தெடுத்து வெற்றி claim செய்யப்படவில்லை.',
                '',
                '## வரம்புகள்',
                '',
                '- ERA5 grid reanalysis உள்ளூர் rain gauge அல்ல.',
                '- ஐந்து annual folds மற்றும் பத்து source-window blocks மட்டுமே உள்ளன.',
                '- Bootstrap source-window dependence-ஐப் பாதுகாக்கிறது; அது புதிய இடங்கள் அல்லது வேறு காலங்களுக்கு generalization உறுதி அல்ல.',
                '- Models எளிய deterministic baselines; இது அனைத்து சாத்தியமான Karuvottam formulations-ன் சோதனை அல்ல.',
                '- Multiple model/metric comparisons காரணமாக isolated favourable values confirmatory evidence அல்ல.',
                '- Calibrated probability publication gate கடக்கவில்லை. UI probability தொடர்ந்து disabled.',
                '',
                '## அடுத்த ஆய்வு நடவடிக்கைகள்',
                '',
                '- உள்ளூர் rain-gauge observations கிடைத்தால் அதே protocol-ல் மீண்டும் மதிப்பிடுதல்.',
                '- மேலும் இடங்கள் மற்றும் நீண்ட independent காலப்பகுதிகளில் external validation செய்தல்.',
                '- Model மாற்றங்களுக்கு முன் primary metrics மற்றும் thresholds-ஐ முன்பதிவு செய்தல்.',
                '- புதிய model தற்போதைய seasonal baseline-ஐ leakage-safe paired evaluation-ல் தெளிவாக முந்தினால் மட்டுமே publication gate-ஐ மீளாய்வு செய்தல்.',
                '',
            ]
        )
        return '\n'.join(lines).encode('utf-8')

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
        description='Publish checksum-verified T6.5 research findings'
    )
    parser.add_argument('--rolling', type=Path, required=True)
    parser.add_argument('--fixed', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap-iterations', type=int, default=2000)
    parser.add_argument('--confidence-level', type=float, default=0.95)
    parser.add_argument('--random-seed', type=int, default=20261029)
    return parser


def main() -> None:
    args = _parser().parse_args()
    artifact = ResearchFindingsService().build(
        args.rolling,
        args.fixed,
        args.output,
        FindingsSpec(
            bootstrap_iterations=args.bootstrap_iterations,
            confidence_level=args.confidence_level,
            random_seed=args.random_seed,
        ),
    )
    print(
        f'Published T6.5 findings for {artifact.paired_rows_per_candidate} '
        f'paired rows at {artifact.summary_path}; '
        f'incremental_value_supported={artifact.incremental_value_supported}; '
        f'findings_key={artifact.findings_key}'
    )


if __name__ == '__main__':
    main()
