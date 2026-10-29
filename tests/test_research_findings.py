import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from karuvottam.research_findings import (
    FindingsSpec,
    ResearchEvidenceReader,
    ResearchFindingsService,
)


APPROACHES = ('seasonal_climatology', 'karuvottam_only', 'combined')


def _write_csv(path, fieldnames, rows):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(
            stream, fieldnames=fieldnames, lineterminator='\n'
        )
        writer.writeheader()
        writer.writerows(rows)


def _manifest(path, key_name, key, files, **extra):
    entries = {
        filename: {
            'sha256': hashlib.sha256((path.parent / filename).read_bytes()).hexdigest()
        }
        for filename in files
    }
    path.write_text(
        json.dumps({key_name: key, 'files': entries, **extra}),
        encoding='utf-8',
    )


def _write_evidence(tmp_path, *, candidates_better=False):
    rolling = tmp_path / 'rolling'
    fixed = tmp_path / 'fixed'
    rolling.mkdir()
    fixed.mkdir()
    prediction_fields = (
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
    )
    examples = (
        ('aadi', 2020, 1, '2020-12-01', 0.0, 0),
        ('aadi', 2020, 2, '2020-12-02', 2.0, 1),
        ('margazhi', 2020, 1, '2021-07-01', 0.0, 0),
        ('margazhi', 2020, 2, '2021-07-02', 4.0, 1),
    )
    rows = []
    for approach in APPROACHES:
        for season, year, day, target_date, observed, wet in examples:
            if candidates_better:
                good = approach != 'seasonal_climatology'
            else:
                good = approach == 'seasonal_climatology'
            predicted = observed if good else (2.0 if wet == 0 else 0.0)
            probability = (90.0 if wet else 10.0) if good else (10.0 if wet else 90.0)
            rows.append(
                {
                    'validation_key': 'rolling:test-key',
                    'approach': approach,
                    'model_version': f'{approach}-test-1.0',
                    'season_type': season,
                    'season_year': year,
                    'source_window_key': f'{season}:{year}:test',
                    'target_day_number': day,
                    'target_date_local': target_date,
                    'observed_precipitation_mm': observed,
                    'observed_wet_day': wet,
                    'predicted_precipitation_mm': predicted,
                    'predicted_wet_probability_pct': probability,
                    'status': 'available',
                }
            )
    _write_csv(rolling / 'rolling_predictions.csv', prediction_fields, rows)

    metric_fields = (
        'scope',
        'fold_key',
        'approach',
        'dimension',
        'group_value',
        'f1',
        'roc_auc',
        'brier_score',
        'mae_mm',
        'rmse_mm',
    )
    rolling_metrics = []
    fixed_metrics = []
    for approach in APPROACHES:
        if candidates_better:
            good = approach != 'seasonal_climatology'
        else:
            good = approach == 'seasonal_climatology'
        metric = {
            'approach': approach,
            'dimension': 'overall',
            'group_value': 'all',
            'f1': 1.0 if good else 0.0,
            'roc_auc': 1.0 if good else 0.0,
            'brier_score': 0.01 if good else 0.81,
            'mae_mm': 0.0 if good else 2.0,
            'rmse_mm': 0.0 if good else 2.0,
        }
        rolling_metrics.append(
            {'scope': 'pooled', 'fold_key': 'all-folds', **metric}
        )
        rolling_metrics.append(
            {'scope': 'fold', 'fold_key': 'fold-2020', **metric}
        )
        fixed_metrics.append(metric)
    _write_csv(rolling / 'rolling_metrics.csv', metric_fields, rolling_metrics)
    fixed_fields = tuple(
        field for field in metric_fields if field not in {'scope', 'fold_key'}
    )
    _write_csv(fixed / 'evaluation_metrics.csv', fixed_fields, fixed_metrics)
    _manifest(
        rolling / 'validation_manifest.json',
        'validation_key',
        'rolling:test-key',
        ('rolling_predictions.csv', 'rolling_metrics.csv'),
        source_dataset={'dataset_key': 'dataset:test-key'},
    )
    _manifest(
        fixed / 'evaluation_manifest.json',
        'evaluation_key',
        'fixed:test-key',
        ('evaluation_metrics.csv',),
        source_comparison={'comparison_key': 'comparison:test-key'},
    )
    return rolling, fixed


def test_service_publishes_conservative_findings_with_uncertainty(tmp_path):
    rolling, fixed = _write_evidence(tmp_path)
    artifact = ResearchFindingsService().build(
        rolling,
        fixed,
        tmp_path / 'output',
        FindingsSpec(bootstrap_iterations=200, random_seed=7),
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert artifact.incremental_value_supported is False
    assert artifact.paired_rows_per_candidate == 4
    comparisons = list(
        csv.DictReader(artifact.comparison_path.open(encoding='utf-8'))
    )
    assert len(comparisons) == 2
    assert all(row['incremental_value_supported'] == 'False' for row in comparisons)
    assert all(float(row['brier_ci_lower']) > 0 for row in comparisons)
    assert all(float(row['mae_ci_lower_mm']) > 0 for row in comparisons)
    summary = artifact.summary_path.read_text(encoding='utf-8')
    assert 'கூடுதல் predictive value தருகிறது என்ற ஆதாரம் கிடைக்கவில்லை' in summary
    assert 'பொதுவான மறுப்பு அல்ல' in summary
    assert 'UI probability தொடர்ந்து disabled' in summary


def test_decision_rule_can_support_consistent_paired_improvement(tmp_path):
    rolling, fixed = _write_evidence(tmp_path, candidates_better=True)
    artifact = ResearchFindingsService().build(
        rolling,
        fixed,
        tmp_path / 'output',
        FindingsSpec(bootstrap_iterations=200, random_seed=7),
    )

    assert artifact.incremental_value_supported is True
    comparisons = list(
        csv.DictReader(artifact.comparison_path.open(encoding='utf-8'))
    )
    assert all(float(row['brier_ci_upper']) < 0 for row in comparisons)
    assert all(float(row['mae_ci_upper_mm']) < 0 for row in comparisons)
    summary = artifact.summary_path.read_text(encoding='utf-8')
    assert 'முன் வரையறுக்கப்பட்ட paired decision rule-ஐ கடந்த' in summary
    assert 'ஆதாரம் கிடைக்கவில்லை' not in summary


def test_outputs_are_reproducible_across_build_timestamps(tmp_path):
    rolling, fixed = _write_evidence(tmp_path)
    service = ResearchFindingsService()
    spec = FindingsSpec(bootstrap_iterations=200, random_seed=42)
    first = service.build(
        rolling,
        fixed,
        tmp_path / 'first',
        spec,
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = service.build(
        rolling,
        fixed,
        tmp_path / 'second',
        spec,
        built_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert first.findings_key == second.findings_key
    for name in ('comparison_path', 'findings_path', 'summary_path'):
        assert getattr(first, name).read_bytes() == getattr(second, name).read_bytes()


def test_reader_rejects_checksum_mismatch(tmp_path):
    rolling, fixed = _write_evidence(tmp_path)
    (rolling / 'rolling_predictions.csv').write_text('changed\n', encoding='utf-8')

    with pytest.raises(ValueError, match='checksum'):
        ResearchEvidenceReader().read(rolling, fixed)


def test_reader_rejects_unmatched_outcomes(tmp_path):
    rolling, fixed = _write_evidence(tmp_path)
    path = rolling / 'rolling_predictions.csv'
    rows = list(csv.DictReader(path.open(encoding='utf-8')))
    fields = tuple(rows[0])
    target = next(row for row in rows if row['approach'] == 'combined')
    target['observed_precipitation_mm'] = '99'
    _write_csv(path, fields, rows)
    manifest = json.loads(
        (rolling / 'validation_manifest.json').read_text(encoding='utf-8')
    )
    manifest['files']['rolling_predictions.csv']['sha256'] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (rolling / 'validation_manifest.json').write_text(
        json.dumps(manifest), encoding='utf-8'
    )

    with pytest.raises(ValueError, match='matched outcomes'):
        ResearchEvidenceReader().read(rolling, fixed)


@pytest.mark.parametrize(
    'values, message',
    [
        ((199, 0.95, 1), 'at least 200'),
        ((200, 0.5, 1), 'between 0.5 and 1'),
        ((200, 0.95, -1), 'must not be negative'),
    ],
)
def test_spec_rejects_invalid_values(values, message):
    with pytest.raises(ValueError, match=message):
        FindingsSpec(*values)
