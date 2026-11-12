"""Evidence gate for publishing a combined Karuvottam/weather model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from config import PROJECT_ROOT, settings
from karuvottam.event_dashboard import EventDashboardEvidenceService


VERSION = 'combined-validation-1.0'


def _read_verified(path: Path, digest: str) -> dict:
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'checksum mismatch: {path.name}')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('report must be an object')
    return value


def build(
    *, findings_dir: Path, validation_dir: Path, dataset_dir: Path,
    event_rainfall_dir: Path, calibration_dir: Path,
    latitude: float, longitude: float,
) -> dict:
    evidence = EventDashboardEvidenceService(
        findings_dir, validation_dir, dataset_dir, event_rainfall_dir,
        latitude=latitude, longitude=longitude,
    )
    comparison = evidence.comparison()
    event_rainfall = evidence.event_rainfall()
    reasons = []
    pair = None
    findings_key = None
    validation_key = None
    dataset_key = None
    if comparison.available:
        findings_manifest = json.loads((Path(findings_dir) / 'findings_manifest.json').read_text())
        findings = _read_verified(
            Path(findings_dir) / 'research_findings.json',
            findings_manifest['files']['research_findings.json']['sha256'],
        )
        pair = next((item for item in findings['paired_comparisons']
                     if item['candidate_approach'] == 'combined'), None)
        findings_key = comparison.findings_key
        validation_key = findings_manifest['inputs']['rolling_validation_key']
        dataset_key = json.loads((Path(dataset_dir) / 'manifest.json').read_text())['dataset_key']
        if (pair is None or not comparison.incremental_value_supported
                or not pair['incremental_value_supported']
                or pair['brier_ci_upper'] >= 0 or pair['mae_ci_upper_mm'] >= 0):
            reasons.append('combined_no_incremental_value')
    else:
        reasons.append('matched_comparison_unavailable')

    calibration = None
    calibration_digest = None
    try:
        calibration_manifest = json.loads(
            (Path(calibration_dir) / 'calibration_manifest.json').read_text()
        )
        calibration_digest = calibration_manifest['calibration_report_sha256']
        calibration = _read_verified(
            Path(calibration_dir) / 'calibration_report.json', calibration_digest,
        )
        if (calibration['version'] != 'real-score-calibration-1.0'
                or calibration['dataset_key'] != dataset_key
                or abs(calibration['location']['latitude'] - latitude) > 0.000001
                or abs(calibration['location']['longitude'] - longitude) > 0.000001):
            calibration = None
            reasons.append('calibration_input_mismatch')
        elif not calibration['calibration_gate_passed']:
            reasons.append('score_calibration_gate_failed')
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        calibration = None
        reasons.append('calibration_evidence_unavailable')

    if not event_rainfall.available:
        reasons.append('event_rainfall_evidence_unavailable')
    elif (event_rainfall.distance_mae is None or event_rainfall.baseline_mae is None
          or event_rainfall.distance_mae >= event_rainfall.baseline_mae):
        reasons.append('event_distance_no_incremental_value')
    # No event/IOD/ENSO features are present in combined-knn-1.0. They cannot
    # inherit the T6 paired test or the score-only calibration result.
    reasons.append('event_climate_candidate_not_evaluated')
    combined_supported = comparison.available and 'combined_no_incremental_value' not in reasons
    return {
        'version': VERSION,
        'status': 'historical_candidate_supported' if combined_supported else 'withheld',
        'reason_codes': reasons,
        'candidate_model': 'combined-knn-1.0',
        'candidate_feature_scope': 'karuvottam_source_window_weather_without_event_or_climate_indices',
        'matched_rolling_years': [comparison.first_year, comparison.last_year]
        if comparison.available else None,
        'matched_daily_rows_per_approach': comparison.matched_days,
        'location': {'latitude': latitude, 'longitude': longitude},
        'dataset_key': dataset_key,
        'validation_key': validation_key,
        'findings_key': findings_key,
        'combined_paired_brier_delta': pair['brier_delta'] if pair else None,
        'combined_paired_brier_ci_upper': pair['brier_ci_upper'] if pair else None,
        'combined_paired_mae_delta_mm': pair['mae_delta_mm'] if pair else None,
        'combined_paired_mae_ci_upper_mm': pair['mae_ci_upper_mm'] if pair else None,
        'score_calibration_report_sha256': calibration_digest if calibration else None,
        'score_calibration_gate_passed': calibration['calibration_gate_passed'] if calibration else False,
        'event_rainfall_years': [event_rainfall.first_year, event_rainfall.last_year]
        if event_rainfall.available else None,
        'event_distance_baseline_mae_mm_per_24h': event_rainfall.baseline_mae,
        'event_distance_model_mae_mm_per_24h': event_rainfall.distance_mae,
        'public_combined_amount_enabled': False,
        'public_combined_probability_enabled': False,
        'publication_note': 'Research comparisons only; no event-aware combined candidate or calibrated combined-model probabilities.',
    }


def export(report: dict, output: Path) -> Path:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'combined_validation.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    (output / 'combined_validation_manifest.json').write_text(
        json.dumps({
            'version': VERSION,
            'report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'findings_key': report['findings_key'],
            'dataset_key': report['dataset_key'],
        }, ensure_ascii=False, indent=2) + '\n'
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    root = PROJECT_ROOT / 'data/exports'
    parser.add_argument('--findings', type=Path, default=root / 'research-findings-2015-2024')
    parser.add_argument('--validation', type=Path, default=root / 'rolling-validation-2015-2024')
    parser.add_argument('--dataset', type=Path, default=root / 'evaluation-2015-2024')
    parser.add_argument('--event-rainfall', type=Path, default=root / 'event-rainfall-2015-2024')
    parser.add_argument('--calibration', type=Path, default=root / 'score-calibration-2015-2024')
    parser.add_argument('--output', type=Path, default=root / 'combined-validation-2015-2024')
    args = parser.parse_args()
    report = build(
        findings_dir=args.findings, validation_dir=args.validation,
        dataset_dir=args.dataset, event_rainfall_dir=args.event_rainfall,
        calibration_dir=args.calibration,
        latitude=settings.latitude, longitude=settings.longitude,
    )
    path = export(report, args.output)
    print(json.dumps({'report': str(path), 'status': report['status'],
                      'reason_codes': report['reason_codes']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
