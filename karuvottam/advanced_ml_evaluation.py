"""Research-only, as-of rolling evaluation of two advanced ML candidates."""

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
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean
from uuid import uuid4

import numpy as np
import sklearn
from sklearn.ensemble import (HistGradientBoostingClassifier,
                              HistGradientBoostingRegressor,
                              RandomForestClassifier, RandomForestRegressor)
from sklearn.linear_model import LogisticRegression

from config import PROJECT_ROOT
from karuvottam.baseline_comparison import DatasetExample
from karuvottam.evaluation_metrics import (EvaluationMetricsEngine,
                                           EvaluationPrediction)
from karuvottam.time_series_validation import (ValidationDataset,
                                                ValidationDatasetReader)

VERSION = 'advanced-ml-evaluation-1.0'
MODELS = ('random_forest', 'hist_gradient_boosting')
MODEL_VERSIONS = {'random_forest': 'random-forest-1.0',
                  'hist_gradient_boosting': 'hist-gradient-boosting-1.0'}
MODEL_CONFIG = {
    'random_forest': {'n_estimators': 64, 'max_depth': 5,
                      'min_samples_leaf': 20},
    'hist_gradient_boosting': {'max_iter': 64, 'max_leaf_nodes': 7,
                               'min_samples_leaf': 30,
                               'l2_regularization': 10,
                               'early_stopping': False},
}
FEATURES = ('source_precipitation_mm', 'source_mean_temperature_c',
            'source_mean_relative_humidity_pct', 'source_mean_cloud_cover_pct',
            'source_mean_wind_speed_kmh', 'is_margazhi', 'horizon_fraction',
            'target_month_sin', 'target_month_cos')
PREDICTION_COLUMNS = ('evaluation_version', 'evaluation_key', 'dataset_key',
    'dataset_sha256', 'baseline_validation_key', 'approach', 'model_version',
    'season_type', 'season_year', 'source_window_key', 'as_of_cutoff_local',
    'target_day_number', 'target_date_local', 'target_quality_flag',
    'observed_precipitation_mm', 'observed_wet_day',
    'raw_wet_probability_pct', 'predicted_wet_probability_pct',
    'predicted_precipitation_mm', 'status', 'reason_code',
    'training_rows', 'training_windows', 'calibration_rows',
    'calibration_windows', 'latest_training_outcome')


@dataclass(frozen=True)
class AdvancedSpec:
    training_start_year: int = 2015
    first_evaluation_year: int = 2020
    last_evaluation_year: int = 2024
    wet_day_threshold_mm: float = 0.1
    seed: int = 20261114
    bootstrap_iterations: int = 1000

    def __post_init__(self):
        if (self.training_start_year < 1 or
                self.first_evaluation_year < self.training_start_year + 3 or
                self.last_evaluation_year < self.first_evaluation_year or
                self.wet_day_threshold_mm < 0 or
                self.bootstrap_iterations < 200):
            raise ValueError('invalid advanced ML evaluation specification')


def _feature(row: DatasetExample) -> tuple[float, ...]:
    if not row.complete_source:
        raise ValueError('source features are unavailable')
    month_angle = 2 * math.pi * row.target_month / 12
    horizon = 180 if row.season_type == 'aadi' else 140
    return (*row.source_features, float(row.season_type == 'margazhi'),
            row.target_day_number / horizon,
            math.sin(month_angle), math.cos(month_angle))


def eligible_training(dataset: ValidationDataset, window_key: str,
                      spec: AdvancedSpec) -> tuple[DatasetExample, ...]:
    """Only earlier season years with outcomes known before source-window start."""
    window = dataset.windows[window_key]
    cutoff = window.start_local.date()
    return tuple(row for row in dataset.examples
                 if spec.training_start_year <= row.season_year < window.season_year
                 and row.complete_source and row.complete_outcome
                 and date.fromisoformat(row.target_date_local) < cutoff)


def _estimators(model: str, seed: int):
    if model == 'random_forest':
        parameters = MODEL_CONFIG[model]
        return (RandomForestClassifier(**parameters, random_state=seed, n_jobs=1),
                RandomForestRegressor(**parameters, random_state=seed, n_jobs=1))
    if model == 'hist_gradient_boosting':
        parameters = MODEL_CONFIG[model]
        return (HistGradientBoostingClassifier(**parameters, random_state=seed),
                HistGradientBoostingRegressor(**parameters, random_state=seed))
    raise ValueError('unsupported advanced model')


def _fit(rows: tuple[DatasetExample, ...], model: str, spec: AdvancedSpec):
    if len({row.source_window_key for row in rows}) < 4:
        raise ValueError('too few independent training windows')
    features = np.asarray([_feature(row) for row in rows], dtype=float)
    wet = np.asarray([row.observed_precipitation_mm >= spec.wet_day_threshold_mm
                      for row in rows], dtype=int)
    if len(set(wet)) != 2:
        raise ValueError('training outcomes contain only one class')
    amount = np.asarray([math.log1p(row.observed_precipitation_mm) for row in rows])
    classifier, regressor = _estimators(model, spec.seed)
    classifier.fit(features, wet)
    regressor.fit(features, amount)
    return classifier, regressor


def _logit(probability: float) -> float:
    value = min(.9999, max(.0001, probability))
    return math.log(value / (1 - value))


def _calibrator(dataset: ValidationDataset, outer_window_key: str,
                model: str, spec: AdvancedSpec):
    """Fit sigmoid calibration on earlier, as-of out-of-fold windows only."""
    outer = dataset.windows[outer_window_key]
    years = range(max(spec.training_start_year + 2, outer.season_year - 2),
                  outer.season_year)
    logits: list[float] = []
    outcomes: list[int] = []
    used_windows: set[str] = set()
    for year in years:
        inner = sorted((window for window in dataset.windows.values()
                        if window.season_year == year and
                        window.start_local < outer.start_local),
                       key=lambda item: item.start_local)
        for window in inner:
            train = eligible_training(dataset, window.source_window_key, spec)
            calibration_rows = tuple(row for row in dataset.examples
                if row.source_window_key == window.source_window_key
                and row.complete_source and row.complete_outcome
                and date.fromisoformat(row.target_date_local) < outer.start_local.date())
            if not calibration_rows or len({r.source_window_key for r in train}) < 4:
                continue
            try:
                classifier, _ = _fit(train, model, spec)
            except ValueError:
                continue
            raw = classifier.predict_proba(
                np.asarray([_feature(row) for row in calibration_rows], dtype=float))[:, 1]
            logits.extend(_logit(float(value)) for value in raw)
            outcomes.extend(int(row.observed_precipitation_mm >= spec.wet_day_threshold_mm)
                            for row in calibration_rows)
            used_windows.add(window.source_window_key)
    if len(used_windows) < 2 or len(set(outcomes)) != 2:
        raise ValueError('insufficient prior out-of-fold calibration evidence')
    calibrator = LogisticRegression(C=0.1, solver='lbfgs', max_iter=200,
                                    random_state=spec.seed)
    calibrator.fit(np.asarray(logits).reshape(-1, 1), outcomes)
    return calibrator, len(outcomes), len(used_windows)


def _baseline_rows(root: Path, dataset: ValidationDataset, spec: AdvancedSpec):
    manifest = json.loads((root / 'validation_manifest.json').read_text())
    content = (root / 'rolling_predictions.csv').read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if (manifest['files']['rolling_predictions.csv']['sha256'] != digest or
        manifest['source_dataset']['dataset_key'] != dataset.source_manifest['dataset_key'] or
        manifest['source_dataset']['dataset_sha256'] != dataset.dataset_sha256 or
        manifest['spec']['training_start_year'] != spec.training_start_year or
        manifest['spec']['first_evaluation_year'] != spec.first_evaluation_year or
        manifest['spec']['last_evaluation_year'] != spec.last_evaluation_year or
        float(manifest['spec']['wet_day_threshold_mm']) != spec.wet_day_threshold_mm):
        raise ValueError('rolling baseline provenance or split does not match')
    rows = {}
    for row in csv.DictReader(io.StringIO(content.decode('utf-8'))):
        if row['approach'] != 'seasonal_climatology':
            continue
        identity = (row['season_type'], int(row['season_year']),
                    int(row['target_day_number']))
        if identity in rows:
            raise ValueError('duplicate rolling baseline identity')
        rows[identity] = row
    expected = {(row.season_type, row.season_year, row.target_day_number)
                for row in dataset.examples
                if spec.first_evaluation_year <= row.season_year <= spec.last_evaluation_year}
    if set(rows) != expected:
        raise ValueError('rolling baseline identities do not match the dataset')
    examples = {(row.season_type, row.season_year, row.target_day_number): row
                for row in dataset.examples}
    for identity, row in rows.items():
        example = examples[identity]
        window = dataset.windows[example.source_window_key]
        observed = example.observed_precipitation_mm
        if (row['validation_key'] != manifest['validation_key'] or
            row['dataset_key'] != dataset.source_manifest['dataset_key'] or
            row['dataset_sha256'] != dataset.dataset_sha256 or
            row['source_window_key'] != example.source_window_key or
            row['target_date_local'] != example.target_date_local or
            row['target_quality_flag'] != example.target_quality_flag or
            date.fromisoformat(row['as_of_cutoff_local'][:10]) != window.start_local.date() or
            (None if row['observed_precipitation_mm'] == '' else
             float(row['observed_precipitation_mm'])) != observed or
            (None if observed is None else
             int(observed >= spec.wet_day_threshold_mm)) !=
            (None if row['observed_wet_day'] == '' else int(row['observed_wet_day']))):
            raise ValueError('rolling baseline row provenance does not match the dataset')
    return rows, manifest, digest


def _eval_prediction(row: dict, key: str, dataset: ValidationDataset,
                     threshold: float) -> EvaluationPrediction:
    observed = row['observed_precipitation_mm']
    return EvaluationPrediction(
        comparison_key=key, dataset_key=dataset.source_manifest['dataset_key'],
        dataset_sha256=dataset.dataset_sha256, approach=row['approach'],
        model_version=row['model_version'], wet_day_threshold_mm=threshold,
        season_type=row['season_type'], season_year=row['season_year'],
        source_window_key=row['source_window_key'],
        target_day_number=row['target_day_number'],
        target_date_local=date.fromisoformat(row['target_date_local']),
        target_quality_flag=row['target_quality_flag'],
        observed_precipitation_mm=observed,
        observed_wet_day=None if observed is None else int(observed >= threshold),
        predicted_precipitation_mm=row['predicted_precipitation_mm'],
        predicted_wet_probability_pct=row['predicted_wet_probability_pct'],
        status=row['status'])


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower) if lower != upper else ordered[lower]


def _paired(candidate: list[dict], baseline: dict, spec: AdvancedSpec):
    blocks: dict[str, list[tuple[float, float]]] = {}
    for row in candidate:
        identity = (row['season_type'], row['season_year'], row['target_day_number'])
        prior = baseline[identity]
        if row['status'] != 'available' or prior['status'] != 'available':
            continue
        observed = row['observed_precipitation_mm']
        if observed is None:
            continue
        outcome = float(observed >= spec.wet_day_threshold_mm)
        baseline_outcome = float(prior['observed_precipitation_mm'])
        if (row['source_window_key'] != prior['source_window_key'] or
            row['target_date_local'] != prior['target_date_local'] or
            observed != baseline_outcome or
            int(prior['observed_wet_day']) != int(outcome)):
            raise ValueError('advanced and baseline outcomes are not paired')
        brier = ((row['predicted_wet_probability_pct'] / 100 - outcome) ** 2
                 - (float(prior['predicted_wet_probability_pct']) / 100 - outcome) ** 2)
        mae = (abs(row['predicted_precipitation_mm'] - observed)
               - abs(float(prior['predicted_precipitation_mm']) - observed))
        blocks.setdefault(row['source_window_key'], []).append((brier, mae))
    if not blocks:
        raise ValueError('no paired evaluation rows')
    values = [pair for rows in blocks.values() for pair in rows]
    rng = random.Random(spec.seed)
    keys = sorted(blocks)
    draws = [[], []]
    for _ in range(spec.bootstrap_iterations):
        sampled = [pair for key in (rng.choice(keys) for _ in keys)
                   for pair in blocks[key]]
        for index in (0, 1):
            draws[index].append(fmean(pair[index] for pair in sampled))
    return {'paired_rows': len(values), 'source_window_blocks': len(blocks),
            'brier_delta': round(fmean(pair[0] for pair in values), 6),
            'brier_ci_95': [round(_percentile(draws[0], q), 6) for q in (.025, .975)],
            'mae_delta_mm': round(fmean(pair[1] for pair in values), 6),
            'mae_ci_95_mm': [round(_percentile(draws[1], q), 6) for q in (.025, .975)]}


def _atomic(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_file_checksums(output_dir: Path, manifest: dict) -> None:
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('advanced ML manifest has no files')
    for name, expected in files.items():
        if Path(name).name != name:
            raise ValueError('advanced ML artifact filename is unsafe')
        content = (output_dir / name).read_bytes()
        if (len(content) != expected['bytes'] or
                hashlib.sha256(content).hexdigest() != expected['sha256']):
            raise ValueError(f'advanced ML artifact checksum mismatch: {name}')


def verify(dataset_dir: Path, baseline_dir: Path, output_dir: Path) -> dict:
    manifest = json.loads((output_dir / 'advanced_manifest.json').read_text())
    if manifest.get('version') != VERSION:
        raise ValueError('unsupported advanced ML artifact version')
    verify_file_checksums(output_dir, manifest)
    dataset = ValidationDatasetReader().read(
        dataset_dir / 'evaluation_dataset.csv', dataset_dir / 'manifest.json')
    spec = AdvancedSpec(**manifest['spec'])
    _, baseline_manifest, baseline_digest = _baseline_rows(
        baseline_dir, dataset, spec)
    summary = json.loads((output_dir / 'advanced_summary.json').read_text())
    if (manifest['dataset_sha256'] != dataset.dataset_sha256 or
            manifest['baseline_sha256'] != baseline_digest or
            manifest['source_dataset_key'] != dataset.source_manifest['dataset_key'] or
            manifest['baseline_validation_key'] != baseline_manifest['validation_key'] or
            summary['evaluation_key'] != manifest['evaluation_key'] or
            summary['publication_state']['probability_output_enabled']):
        raise ValueError('advanced ML input provenance or publication state changed')
    seen: set[tuple] = set()
    with (output_dir / 'advanced_predictions.csv').open(newline='', encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            identity = (row['approach'], row['season_type'], row['season_year'],
                        row['target_day_number'])
            if identity in seen or row['approach'] not in MODELS:
                raise ValueError('duplicate or unsupported advanced prediction identity')
            seen.add(identity)
            if (row['evaluation_key'] != manifest['evaluation_key'] or
                    row['dataset_sha256'] != dataset.dataset_sha256 or
                    row['baseline_validation_key'] != baseline_manifest['validation_key'] or
                    date.fromisoformat(row['latest_training_outcome']) >=
                    date.fromisoformat(row['as_of_cutoff_local'][:10])):
                raise ValueError('advanced prediction violates as-of provenance')
    if len(seen) != summary['prediction_rows']:
        raise ValueError('advanced prediction row count changed')
    return {'evaluation_key': manifest['evaluation_key'],
            'prediction_rows': len(seen), 'verified': True}


def run(dataset_dir: Path, baseline_dir: Path, output_dir: Path,
        spec: AdvancedSpec = AdvancedSpec()) -> dict:
    dataset = ValidationDatasetReader().read(
        dataset_dir / 'evaluation_dataset.csv', dataset_dir / 'manifest.json')
    baseline, baseline_manifest, baseline_digest = _baseline_rows(
        baseline_dir, dataset, spec)
    by_window: dict[str, set[tuple]] = {}
    for example in dataset.examples:
        by_window.setdefault(example.source_window_key, set()).add(example.source_features)
    if any(len(values) != 1 for values in by_window.values()):
        raise ValueError('source-window features differ between target days')
    identity = {'version': VERSION, 'dataset_sha256': dataset.dataset_sha256,
                'baseline_sha256': baseline_digest, 'spec': asdict(spec),
                'sklearn_version': sklearn.__version__, 'features': FEATURES,
                'model_versions': MODEL_VERSIONS,
                'model_config': MODEL_CONFIG,
                'calibration': {'method': 'sigmoid_on_prior_oof_logits', 'C': 0.1,
                                'lookback_years': 2}}
    key = VERSION + ':' + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
    rows: list[dict] = []
    raw_brier: dict[str, list[float]] = {model: [] for model in MODELS}
    for year in range(spec.first_evaluation_year, spec.last_evaluation_year + 1):
        windows = sorted((window for window in dataset.windows.values()
                          if window.season_year == year),
                         key=lambda window: window.start_local)
        if {window.season_type for window in windows} != {'aadi', 'margazhi'}:
            raise ValueError(f'evaluation year {year} lacks both seasons')
        for window in windows:
            examples = tuple(row for row in dataset.examples
                             if row.source_window_key == window.source_window_key)
            train = eligible_training(dataset, window.source_window_key, spec)
            if not train:
                raise ValueError('no cutoff-eligible training data')
            assert all(date.fromisoformat(row.target_date_local) < window.start_local.date()
                       for row in train)
            for model in MODELS:
                classifier, regressor = _fit(train, model, spec)
                calibrator, calibration_count, calibration_windows = _calibrator(
                    dataset, window.source_window_key, model, spec)
                for example in examples:
                    result = {'evaluation_version': VERSION, 'evaluation_key': key,
                        'dataset_key': dataset.source_manifest['dataset_key'],
                        'dataset_sha256': dataset.dataset_sha256,
                        'baseline_validation_key': baseline_manifest['validation_key'],
                        'approach': model, 'model_version': MODEL_VERSIONS[model],
                        'season_type': example.season_type,
                        'season_year': example.season_year,
                        'source_window_key': example.source_window_key,
                        'as_of_cutoff_local': window.start_local.isoformat(),
                        'target_day_number': example.target_day_number,
                        'target_date_local': example.target_date_local,
                        'target_quality_flag': example.target_quality_flag,
                        'observed_precipitation_mm': example.observed_precipitation_mm,
                        'observed_wet_day': (None if example.observed_precipitation_mm is None
                            else int(example.observed_precipitation_mm >= spec.wet_day_threshold_mm)),
                        'raw_wet_probability_pct': None,
                        'predicted_wet_probability_pct': None,
                        'predicted_precipitation_mm': None,
                        'status': 'unavailable', 'reason_code': 'source_features_unavailable',
                        'training_rows': len(train),
                        'training_windows': len({row.source_window_key for row in train}),
                        'calibration_rows': calibration_count,
                        'calibration_windows': calibration_windows,
                        'latest_training_outcome': max(row.target_date_local for row in train)}
                    if example.complete_source:
                        features = np.asarray([_feature(example)], dtype=float)
                        raw = float(classifier.predict_proba(features)[0, 1])
                        calibrated = float(calibrator.predict_proba(
                            np.asarray([[_logit(raw)]]))[0, 1])
                        amount = max(0.0, math.expm1(float(regressor.predict(features)[0])))
                        result.update(raw_wet_probability_pct=round(raw * 100, 6),
                            predicted_wet_probability_pct=round(calibrated * 100, 6),
                            predicted_precipitation_mm=round(amount, 6),
                            status='available', reason_code='')
                        if example.complete_outcome:
                            outcome = float(example.observed_precipitation_mm >= spec.wet_day_threshold_mm)
                            raw_brier[model].append((raw - outcome) ** 2)
                    rows.append(result)
    all_eval = [_eval_prediction(row, key, dataset, spec.wet_day_threshold_mm)
                for row in rows]
    for identity_key, prior in sorted(baseline.items()):
        example = next(row for row in dataset.examples
                       if (row.season_type, row.season_year, row.target_day_number) == identity_key)
        all_eval.append(_eval_prediction({
            'approach': 'seasonal_climatology', 'model_version': prior['model_version'],
            'season_type': example.season_type, 'season_year': example.season_year,
            'source_window_key': example.source_window_key,
            'target_day_number': example.target_day_number,
            'target_date_local': example.target_date_local,
            'target_quality_flag': example.target_quality_flag,
            'observed_precipitation_mm': example.observed_precipitation_mm,
            'predicted_precipitation_mm': float(prior['predicted_precipitation_mm']),
            'predicted_wet_probability_pct': float(prior['predicted_wet_probability_pct']),
            'status': prior['status']}, key, dataset, spec.wet_day_threshold_mm))
    metrics_engine = EvaluationMetricsEngine(
        approaches=('seasonal_climatology', *MODELS))
    metrics, reliability = metrics_engine.evaluate(all_eval)
    overall = {row.approach: asdict(row) for row in metrics
               if row.dimension == 'overall'}
    comparisons = {model: _paired([row for row in rows if row['approach'] == model],
                                   baseline, spec) for model in MODELS}
    for model in MODELS:
        comparison = comparisons[model]
        bins = [row for row in reliability if row.approach == model and
                row.dimension == 'overall' and row.sample_count]
        comparison.update(raw_brier_score=round(fmean(raw_brier[model]), 6),
            calibrated_brier_score=overall[model]['brier_score'],
            expected_calibration_error=overall[model]['expected_calibration_error'],
            populated_reliability_bins=len(bins),
            matched_coverage=(comparison['paired_rows'] == len(baseline)),
            candidate_calibration_diagnostic_passed=(overall[model]['brier_score'] < overall['seasonal_climatology']['brier_score']
                and overall[model]['expected_calibration_error'] <= 0.1
                and len(bins) >= 3),
            incremental_value_supported=(comparison['paired_rows'] == len(baseline)
                and comparison['brier_ci_95'][1] < 0 and
                comparison['mae_ci_95_mm'][1] < 0))
    output_dir.mkdir(parents=True, exist_ok=True)
    prediction_path = output_dir / 'advanced_predictions.csv'
    metric_path = output_dir / 'advanced_metrics.csv'
    reliability_path = output_dir / 'advanced_reliability.csv'
    summary_path = output_dir / 'advanced_summary.json'
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=PREDICTION_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    prediction_bytes = buffer.getvalue().encode()
    def csv_bytes(records):
        stream = io.StringIO(newline='')
        fields = tuple(records[0].__dataclass_fields__)
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(row) for row in records)
        return stream.getvalue().encode()
    metric_bytes = csv_bytes(metrics)
    reliability_bytes = csv_bytes(reliability)
    summary = {'evaluation_version': VERSION, 'evaluation_key': key,
        'dataset_key': dataset.source_manifest['dataset_key'],
        'dataset_sha256': dataset.dataset_sha256,
        'baseline_validation_key': baseline_manifest['validation_key'],
        'baseline_predictions_sha256': baseline_digest,
        'location': dataset.source_manifest['location'],
        'weather_source': dataset.source_manifest['weather_source'],
        'model_versions': MODEL_VERSIONS, 'model_config': MODEL_CONFIG,
        'feature_names': FEATURES,
        'dataset_versions': {'dataset': dataset.dataset_version,
            'calendar_rule': dataset.calendar_rule_version,
            'timeline': dataset.timeline_model_version,
            'measurement': dataset.measurement_contract_version},
        'spec': asdict(spec), 'sklearn_version': sklearn.__version__,
        'prediction_rows': len(rows), 'evaluation_rows_per_model': len(baseline),
        'overall_metrics': overall, 'comparisons': comparisons,
        'publication_state': {'probability_output_enabled': False,
            'reason': 'research_only; existing calibration and combined-validation gates remain withheld'}}
    summary_bytes = (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    files = {prediction_path: prediction_bytes, metric_path: metric_bytes,
             reliability_path: reliability_bytes, summary_path: summary_bytes}
    for path, content in files.items():
        _atomic(path, content)
    manifest = {**identity, 'evaluation_key': key,
        'built_at_utc': datetime.now(timezone.utc).isoformat(),
        'source_dataset_key': dataset.source_manifest['dataset_key'],
        'baseline_validation_key': baseline_manifest['validation_key'],
        'files': {path.name: {'sha256': hashlib.sha256(content).hexdigest(),
                'bytes': len(content)} for path, content in files.items()},
        'publication_state': summary['publication_state']}
    _atomic(output_dir / 'advanced_manifest.json',
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode())
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path,
        default=PROJECT_ROOT / 'data/exports/evaluation-2015-2024')
    parser.add_argument('--baseline', type=Path,
        default=PROJECT_ROOT / 'data/exports/rolling-validation-2015-2024')
    parser.add_argument('--output', type=Path,
        default=PROJECT_ROOT / 'data/exports/advanced-ml-2015-2024')
    parser.add_argument('--verify', action='store_true',
                        help='verify existing artifact and source checksums')
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.dataset, args.baseline, args.output), indent=2))
        return
    result = run(args.dataset, args.baseline, args.output)
    print(json.dumps({'evaluation_key': result['evaluation_key'],
        'comparisons': result['comparisons'],
        'publication_state': result['publication_state']}, indent=2))


if __name__ == '__main__':
    main()
