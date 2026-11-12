"""Verified, read-only research evidence for the integrated event dashboard."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


APPROACH_LABELS = (
    ('seasonal_climatology', 'நவீன வானிலை மட்டும் — பருவச் சராசரி'),
    ('karuvottam_only', 'கருவோட்டம் மட்டும் — ஆய்வு மாதிரி'),
    ('combined', 'கருவோட்டம் + வானிலை — ஆய்வு மாதிரி'),
)


@dataclass(frozen=True)
class ComparisonRow:
    approach: str
    label: str
    mae_mm: float
    rmse_mm: float
    brier_score: float


@dataclass(frozen=True)
class ResearchComparison:
    available: bool
    rows: tuple[ComparisonRow, ...]
    first_year: int | None
    last_year: int | None
    matched_days: int | None
    findings_key: str | None
    incremental_value_supported: bool | None


@dataclass(frozen=True)
class HistoricalEventSummary:
    available: bool
    event_count: int | None
    complete_count: int | None
    first_year: int | None
    last_year: int | None
    split_year: int | None
    test_events: int | None
    baseline_mae: float | None
    distance_mae: float | None
    weather_sources: tuple[str, ...]


@dataclass(frozen=True)
class CombinedDecision:
    available: bool
    status: str
    reasons: tuple[str, ...]
    brier_ci_upper: float | None
    mae_ci_upper_mm: float | None
    public_probability_enabled: bool


class EventDashboardEvidenceService:
    def __init__(
        self, findings_dir: Path, validation_dir: Path, dataset_dir: Path,
        event_rainfall_dir: Path,
        *, latitude: float, longitude: float,
        combined_validation_dir: Path | None = None,
        calibration_dir: Path | None = None,
    ) -> None:
        self.findings_dir = Path(findings_dir)
        self.validation_dir = Path(validation_dir)
        self.dataset_dir = Path(dataset_dir)
        self.event_rainfall_dir = Path(event_rainfall_dir)
        self.combined_validation_dir = (
            Path(combined_validation_dir) if combined_validation_dir else None
        )
        self.calibration_dir = Path(calibration_dir) if calibration_dir else None
        self.latitude = latitude
        self.longitude = longitude

    @staticmethod
    def _read_json(path: Path) -> dict:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('artifact must be an object')
        return value

    @staticmethod
    def _matches(path: Path, digest: str) -> bool:
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest

    def comparison(self) -> ResearchComparison:
        unavailable = ResearchComparison(False, (), None, None, None, None, None)
        try:
            manifest = self._read_json(self.findings_dir / 'findings_manifest.json')
            findings_path = self.findings_dir / 'research_findings.json'
            if not self._matches(findings_path, manifest['files']['research_findings.json']['sha256']):
                return unavailable
            findings = self._read_json(findings_path)
            validation = self._read_json(self.validation_dir / 'validation_manifest.json')
            dataset = self._read_json(self.dataset_dir / 'manifest.json')
            if (findings['findings_key'] != manifest['findings_key']
                    or findings['findings_version'] != 'research-findings-1.0'
                    or findings['conclusion']['incremental_value_supported']
                    != manifest['conclusion']['incremental_value_supported']
                    or findings['conclusion']['probability_publication_enabled']
                    != manifest['conclusion']['probability_publication_enabled']
                    or validation['validation_key'] != manifest['inputs']['rolling_validation_key']
                    or dataset['dataset_key'] != validation['source_dataset']['dataset_key']
                    or dataset['weather_source'] != 'open-meteo:era5'
                    or abs(dataset['location']['latitude'] - self.latitude) > 0.000001
                    or abs(dataset['location']['longitude'] - self.longitude) > 0.000001
                    or dataset['files']['evaluation_dataset.csv']['sha256']
                    != validation['source_dataset']['dataset_sha256']
                    or not self._matches(
                        self.dataset_dir / 'evaluation_dataset.csv',
                        dataset['files']['evaluation_dataset.csv']['sha256'],
                    )
                    or validation['files']['rolling_metrics.csv']['sha256']
                    != manifest['inputs']['rolling_metrics_sha256']
                    or not self._matches(
                        self.validation_dir / 'rolling_metrics.csv',
                        validation['files']['rolling_metrics.csv']['sha256'],
                    )):
                return unavailable
            matched = validation['counts']['evaluated_predictions'] // len(APPROACH_LABELS)
            if (matched < 1 or validation['counts']['evaluated_predictions']
                    != matched * len(APPROACH_LABELS)):
                return unavailable
            paired = findings['paired_comparisons']
            if (len(paired) != 2 or any(item['paired_rows'] != matched for item in paired)
                    or {item['candidate_approach'] for item in paired}
                    != {'karuvottam_only', 'combined'}):
                return unavailable
            metrics = findings['rolling_pooled_metrics']
            rows = tuple(
                ComparisonRow(key, label, float(metrics[key]['mae_mm']),
                              float(metrics[key]['rmse_mm']),
                              float(metrics[key]['brier_score']))
                for key, label in APPROACH_LABELS
            )
            spec = validation['spec']
            return ResearchComparison(
                True, rows, int(spec['first_evaluation_year']),
                int(spec['last_evaluation_year']), matched,
                findings['findings_key'],
                bool(findings['conclusion']['incremental_value_supported']),
            )
        except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
            return unavailable

    def event_rainfall(self) -> HistoricalEventSummary:
        unavailable = HistoricalEventSummary(False, None, None, None, None,
                                             None, None, None, None, ())
        try:
            summary = self._read_json(self.event_rainfall_dir / 'summary.json')
            if (summary['version'] != 'event-rainfall-1.0'
                    or abs(summary['location']['latitude'] - self.latitude) > 0.000001
                    or abs(summary['location']['longitude'] - self.longitude) > 0.000001
                    or not self._matches(self.event_rainfall_dir / 'event_rainfall.csv',
                                         summary['csv_sha256'])):
                return unavailable
            holdout = summary['holdout']
            return HistoricalEventSummary(
                True, int(summary['event_count']), int(summary['complete_event_count']),
                int(summary['years'][0]), int(summary['years'][1]),
                int(holdout['split_year']) if holdout.get('split_year') else None,
                int(holdout['test_events']) if holdout.get('test_events') else None,
                float(holdout['baseline_mae_mm_per_24h'])
                if holdout['status'] == 'evaluated' else None,
                float(holdout['band_model_mae_mm_per_24h'])
                if holdout['status'] == 'evaluated' else None,
                tuple(summary['weather_sources']),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return unavailable

    def combined_decision(
        self, comparison: ResearchComparison | None = None,
    ) -> CombinedDecision:
        unavailable = CombinedDecision(False, 'unavailable', (), None, None, False)
        if self.combined_validation_dir is None:
            return unavailable
        comparison = comparison or self.comparison()
        if not comparison.available:
            return unavailable
        try:
            manifest = self._read_json(
                self.combined_validation_dir / 'combined_validation_manifest.json'
            )
            report_path = self.combined_validation_dir / 'combined_validation.json'
            if not self._matches(report_path, manifest['report_sha256']):
                return unavailable
            report = self._read_json(report_path)
            validation = self._read_json(self.validation_dir / 'validation_manifest.json')
            dataset = self._read_json(self.dataset_dir / 'manifest.json')
            if (report['version'] != 'combined-validation-1.0'
                    or manifest['version'] != report['version']
                    or manifest['findings_key'] != report['findings_key']
                    or manifest['dataset_key'] != report['dataset_key']
                    or report['findings_key'] != comparison.findings_key
                    or report['dataset_key'] != dataset['dataset_key']
                    or report['validation_key'] != validation['validation_key']
                    or report['matched_daily_rows_per_approach'] != comparison.matched_days
                    or report['matched_rolling_years']
                    != [comparison.first_year, comparison.last_year]
                    or abs(report['location']['latitude'] - self.latitude) > 0.000001
                    or abs(report['location']['longitude'] - self.longitude) > 0.000001
                    or report['public_combined_probability_enabled']
                    or report['public_combined_amount_enabled']):
                return unavailable
            if report['score_calibration_report_sha256']:
                if (self.calibration_dir is None
                        or not self._matches(
                            self.calibration_dir / 'calibration_report.json',
                            report['score_calibration_report_sha256'],
                        )):
                    return unavailable
            return CombinedDecision(
                True, report['status'], tuple(report['reason_codes']),
                report['combined_paired_brier_ci_upper'],
                report['combined_paired_mae_ci_upper_mm'], False,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return unavailable
