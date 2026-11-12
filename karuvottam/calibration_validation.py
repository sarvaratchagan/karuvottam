"""Evaluate the real Karuvottam research score with an embargoed holdout."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from config import PROJECT_ROOT, settings
from karuvottam.baseline_comparison import EvaluationDatasetReader
from karuvottam.data_access import DataAccess
from karuvottam.forecast_inputs import StoredForecastInputService
from karuvottam.probability_calibration import (
    CalibrationPolicy, CalibrationSample, ProbabilityCalibrationEngine,
)
from karuvottam.research_scoring import MODEL_VERSION, ResearchScoringEngine
from karuvottam.weather_quality import WeatherQualityValidator


VERSION = 'real-score-calibration-1.0'
HOUR = timedelta(hours=1)


def _window_score(work, window: dict, *, location_id: int, source: str,
                  validator: WeatherQualityValidator,
                  scorer: ResearchScoringEngine) -> float:
    start = datetime.fromisoformat(window['start_local']).astimezone(timezone.utc)
    end = datetime.fromisoformat(window['end_local']).astimezone(timezone.utc)
    first = start.replace(minute=0, second=0, microsecond=0) + HOUR
    last = end.replace(minute=0, second=0, microsecond=0)
    records = work.weather_observations.list_between(
        location_id, first, last, source=source,
    )
    summary = window['source_summary']
    if (len(records) != summary['observed_hours']
            or len(records) != summary['expected_hours']
            or {record.raw_payload_reference for record in records
                if record.raw_payload_reference}
            != set(summary['raw_payload_references'])):
        raise ValueError(f'source window no longer matches dataset: {window["source_window_key"]}')
    observations = tuple(StoredForecastInputService._observation(record)
                         for record in records)
    quality = validator.validate(
        observations, expected_start_utc=first, expected_end_utc=last + HOUR,
    )
    result = scorer.score(observations, quality)
    if (abs(sum(item.precipitation_mm or 0 for item in observations)
            - summary['precipitation_mm']) > .011
            or quality.coverage_pct != summary['coverage_pct']):
        raise ValueError(f'source window values changed: {window["source_window_key"]}')
    if result.score is None or result.status != 'available':
        raise ValueError(f'research score unavailable for {window["source_window_key"]}')
    return result.score


def select_samples(examples, windows: list[dict], score_by_key: dict[str, float], *,
                   evaluation_start_year: int, evaluation_end_year: int,
                   timezone_name: str, wet_threshold_mm: float) -> tuple[tuple[CalibrationSample, ...], tuple[str, ...], int]:
    """Keep earlier complete outcomes; embargo windows crossing the test start."""
    local_tz = ZoneInfo(timezone_name)
    metadata = {window['source_window_key']: window for window in windows}
    evaluation = [window for window in windows
                  if evaluation_start_year <= window['season_year'] <= evaluation_end_year]
    if not evaluation:
        raise ValueError('no evaluation windows')
    cutoff = min(datetime.fromisoformat(window['start_local']) for window in evaluation)
    by_window = {}
    for example in examples:
        by_window.setdefault(example.source_window_key, []).append(example)
    retained = []
    embargoed = []
    for key, rows in by_window.items():
        window = metadata.get(key)
        if window is None:
            raise ValueError(f'window metadata missing for {key}')
        if window['season_year'] > evaluation_end_year:
            continue
        if window['season_year'] < evaluation_start_year:
            last_outcome_end = max(
                datetime.combine(date.fromisoformat(row.target_date_local)
                                 + timedelta(days=1), time.min, tzinfo=local_tz)
                for row in rows
            )
            if last_outcome_end >= cutoff:
                embargoed.append(key)
                continue
        retained.append(key)
    retained_set = set(retained)
    training_keys = {key for key in retained_set
                     if metadata[key]['season_year'] < evaluation_start_year}
    evaluation_keys = retained_set - training_keys
    if not training_keys or not evaluation_keys:
        raise ValueError('training or evaluation windows are missing')
    samples = []
    for example in examples:
        key = example.source_window_key
        if key not in retained_set or not example.complete_outcome:
            continue
        if key not in score_by_key:
            raise ValueError(f'research score missing for {key}')
        end = datetime.fromisoformat(metadata[key]['end_local'])
        target_end = datetime.combine(
            date.fromisoformat(example.target_date_local) + timedelta(days=1),
            time.min, tzinfo=local_tz,
        )
        samples.append(CalibrationSample(
            source_window_key=key, source_window_end=end,
            target_datetime=target_end,
            research_score=score_by_key[key],
            observed_rain=example.observed_precipitation_mm >= wet_threshold_mm,
        ))
    return tuple(samples), tuple(sorted(embargoed)), len(training_keys)


def build(
    access: DataAccess, dataset_dir: Path, validation_dir: Path, *,
    latitude: float, longitude: float, evaluation_start_year: int = 2022,
    evaluation_end_year: int = 2024,
) -> dict:
    dataset_dir = Path(dataset_dir)
    examples, manifest, digest = EvaluationDatasetReader().read(
        dataset_dir / 'evaluation_dataset.csv', dataset_dir / 'manifest.json',
    )
    validation = json.loads((Path(validation_dir) / 'validation_manifest.json').read_text())
    location = manifest['location']
    if (abs(location['latitude'] - latitude) > 0.000001
            or abs(location['longitude'] - longitude) > 0.000001
            or validation['source_dataset']['dataset_key'] != manifest['dataset_key']
            or validation['source_dataset']['dataset_sha256'] != digest):
        raise ValueError('calibration input location or dataset does not match')
    windows = manifest['windows']
    validator = WeatherQualityValidator()
    scorer = ResearchScoringEngine()
    with access.transaction() as work:
        stored_location = work.locations.get(location['id'])
        if (stored_location is None or stored_location.name != location['name']
                or abs(stored_location.latitude-latitude) > 0.000001
                or abs(stored_location.longitude-longitude) > 0.000001):
            raise ValueError('configured location does not match stored observations')
        scores = {
            window['source_window_key']: _window_score(
                work, window, location_id=location['id'],
                source=manifest['weather_source'], validator=validator,
                scorer=scorer,
            )
            for window in windows
        }
    samples, embargoed, training_windows = select_samples(
        examples, windows, scores,
        evaluation_start_year=evaluation_start_year,
        evaluation_end_year=evaluation_end_year,
        timezone_name=location['timezone'],
        wet_threshold_mm=float(validation['spec']['wet_day_threshold_mm']),
    )
    total_windows = len({sample.source_window_key for sample in samples})
    policy = CalibrationPolicy(training_fraction=(training_windows + .5) / total_windows)
    report = ProbabilityCalibrationEngine(policy).fit_evaluate(samples)
    window_year_by_key = {window['source_window_key']: window['season_year']
                          for window in windows}
    expected_training = {
        sample.source_window_key for sample in samples
        if window_year_by_key[sample.source_window_key] < evaluation_start_year
    }
    if set(report.training_window_keys) != expected_training:
        raise ValueError('calibration split does not match embargoed year boundary')
    return {
        'version': VERSION,
        'dataset_key': manifest['dataset_key'],
        'dataset_sha256': digest,
        'validation_key': validation['validation_key'],
        'location': location,
        'weather_source': manifest['weather_source'],
        'score_model_version': MODEL_VERSION,
        'source_window_scores': dict(sorted(scores.items())),
        'raw_payload_references': manifest['raw_payload_references'],
        'calibration_model_version': report.model_version,
        'evaluation_years': [evaluation_start_year, evaluation_end_year],
        'wet_threshold_mm': float(validation['spec']['wet_day_threshold_mm']),
        'embargoed_window_keys': list(embargoed),
        'training_window_keys': list(report.training_window_keys),
        'evaluation_window_keys': list(report.evaluation_window_keys),
        'training_samples': report.training_samples,
        'evaluation_samples': report.evaluation_samples,
        'calibration_gate_passed': report.probability_output_enabled,
        'calibration_status': report.status,
        'calibration_reason_codes': list(report.reason_codes),
        'brier_score': report.brier_score,
        'baseline_brier_score': report.baseline_brier_score,
        'expected_calibration_error': report.expected_calibration_error,
        'calibration_bins': [asdict(item) for item in report.calibration_bins],
        'reliability_bins': [asdict(item) for item in report.reliability_bins],
        'public_probability_enabled': False,
    }


def export(result: dict, output: Path) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'calibration_report.json'
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    manifest = {
        'version': VERSION,
        'dataset_key': result['dataset_key'],
        'calibration_report_sha256': hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }
    (output / 'calibration_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
    )
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path,
                        default=PROJECT_ROOT / 'data/exports/evaluation-2015-2024')
    parser.add_argument('--validation', type=Path,
                        default=PROJECT_ROOT / 'data/exports/rolling-validation-2015-2024')
    parser.add_argument('--database', type=Path, default=settings.database_path)
    parser.add_argument('--output', type=Path,
                        default=PROJECT_ROOT / 'data/exports/score-calibration-2015-2024')
    parser.add_argument('--evaluation-start-year', type=int, default=2022)
    parser.add_argument('--evaluation-end-year', type=int, default=2024)
    args = parser.parse_args()
    result = build(
        DataAccess(args.database), args.dataset, args.validation,
        latitude=settings.latitude, longitude=settings.longitude,
        evaluation_start_year=args.evaluation_start_year,
        evaluation_end_year=args.evaluation_end_year,
    )
    path = export(result, args.output)
    print(json.dumps({'report': str(path), 'status': result['calibration_status'],
                      'reason_codes': result['calibration_reason_codes'],
                      'brier_score': result['brier_score'],
                      'baseline_brier_score': result['baseline_brier_score']},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
