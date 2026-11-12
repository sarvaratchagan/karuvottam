import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from karuvottam.baseline_comparison import APPROACHES, OUTPUT_COLUMNS
from karuvottam.evaluation_metrics import (
    BaselinePredictionReader,
    EvaluationMetricSpec,
    EvaluationMetricsEngine,
    EvaluationMetricsService,
)


MODEL_VERSIONS = {
    'seasonal_climatology': 'seasonal-test-1.0',
    'karuvottam_only': 'karuvottam-test-1.0',
    'combined': 'combined-test-1.0',
}


def _prediction_rows():
    examples = (
        ('aadi', 1, '2022-01-01', 0.0, 0),
        ('aadi', 31, '2022-02-01', 2.0, 1),
        ('margazhi', 1, '2022-01-02', 0.0, 0),
        ('margazhi', 31, '2022-02-02', 4.0, 1),
    )
    predictions = {
        'seasonal_climatology': (
            (0.0, 10.0),
            (2.0, 90.0),
            (0.0, 20.0),
            (4.0, 80.0),
        ),
        'karuvottam_only': (
            (1.0, 50.0),
            (1.0, 50.0),
            (1.0, 50.0),
            (1.0, 50.0),
        ),
        'combined': (
            (2.0, 90.0),
            (0.0, 10.0),
            (3.0, 80.0),
            (0.0, 20.0),
        ),
    }
    rows = []
    for approach in APPROACHES:
        for index, (season, day, target_date, rainfall, wet) in enumerate(examples):
            predicted_amount, probability = predictions[approach][index]
            row = {column: '' for column in OUTPUT_COLUMNS}
            row.update(
                {
                    'comparison_version': 'baseline-comparison-test-1.0',
                    'comparison_key': 'baseline-comparison:test-key',
                    'dataset_key': 'evaluation-dataset:test-key',
                    'dataset_sha256': 'a' * 64,
                    'approach': approach,
                    'model_version': MODEL_VERSIONS[approach],
                    'training_start_year': 2018,
                    'training_end_year': 2021,
                    'evaluation_start_year': 2022,
                    'evaluation_end_year': 2022,
                    'wet_day_threshold_mm': 0.1,
                    'season_type': season,
                    'season_year': 2022,
                    'source_window_key': f'{season}:2022:test',
                    'target_day_number': day,
                    'target_date_local': target_date,
                    'source_quality_flag': 'complete',
                    'target_quality_flag': 'complete',
                    'observed_precipitation_mm': rainfall,
                    'observed_wet_day': wet,
                    'predicted_precipitation_mm': predicted_amount,
                    'predicted_wet_probability_pct': probability,
                    'status': 'available',
                    'training_candidate_count': 100,
                    'neighbor_count': 3,
                }
            )
            rows.append(row)
    return rows


def _write_predictions(tmp_path, rows=None):
    predictions_path = tmp_path / 'baseline_predictions.csv'
    with predictions_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(
            stream, fieldnames=OUTPUT_COLUMNS, lineterminator='\n'
        )
        writer.writeheader()
        writer.writerows(rows or _prediction_rows())
    digest = hashlib.sha256(predictions_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / 'baseline_manifest.json'
    manifest_path.write_text(
        json.dumps(
            {
                'comparison_version': 'baseline-comparison-test-1.0',
                'comparison_key': 'baseline-comparison:test-key',
                'files': {
                    predictions_path.name: {
                        'sha256': digest,
                        'rows': len(rows or _prediction_rows()),
                    }
                },
            }
        ),
        encoding='utf-8',
    )
    return predictions_path, manifest_path


def _overall(metrics, approach):
    return next(
        row
        for row in metrics
        if row.approach == approach and row.dimension == 'overall'
    )


def test_engine_reports_classification_probability_and_amount_metrics(tmp_path):
    predictions_path, manifest_path = _write_predictions(tmp_path)
    predictions, _, _ = BaselinePredictionReader().read(
        predictions_path, manifest_path
    )

    metrics, reliability = EvaluationMetricsEngine().evaluate(predictions)

    seasonal = _overall(metrics, 'seasonal_climatology')
    assert seasonal.evaluated_rows == 4
    assert seasonal.precision == 1.0
    assert seasonal.recall == 1.0
    assert seasonal.f1 == 1.0
    assert seasonal.roc_auc == 1.0
    assert seasonal.brier_score == 0.025
    assert seasonal.expected_calibration_error == 0.15
    assert seasonal.mae_mm == 0.0
    assert seasonal.rmse_mm == 0.0
    assert seasonal.bias_mm == 0.0
    assert seasonal.correlation == 1.0

    karuvottam = _overall(metrics, 'karuvottam_only')
    assert karuvottam.precision == 0.5
    assert karuvottam.recall == 1.0
    assert karuvottam.f1 == pytest.approx(0.666667)
    assert karuvottam.roc_auc == 0.5
    assert karuvottam.brier_score == 0.25
    assert karuvottam.correlation is None

    combined = _overall(metrics, 'combined')
    assert combined.precision == 0.0
    assert combined.recall == 0.0
    assert combined.f1 == 0.0
    assert combined.roc_auc == 0.0
    assert len(reliability) == len(metrics) * 10


def test_engine_splits_by_season_month_and_horizon(tmp_path):
    predictions_path, manifest_path = _write_predictions(tmp_path)
    predictions, _, _ = BaselinePredictionReader().read(
        predictions_path, manifest_path
    )

    metrics, _ = EvaluationMetricsEngine().evaluate(predictions)
    seasonal_rows = [
        row for row in metrics if row.approach == APPROACHES[0]
    ]

    assert {(row.dimension, row.group_value) for row in seasonal_rows} == {
        ('overall', 'all'),
        ('season', 'aadi'),
        ('season', 'margazhi'),
        ('month', '01'),
        ('month', '02'),
        ('horizon', '001-030'),
        ('horizon', '031-060'),
    }
    january = next(
        row
        for row in seasonal_rows
        if row.dimension == 'month' and row.group_value == '01'
    )
    assert january.dry_days == 2
    assert january.wet_days == 0
    assert january.roc_auc is None


def test_service_writes_traceable_reproducible_reports(tmp_path):
    predictions_path, manifest_path = _write_predictions(tmp_path)
    service = EvaluationMetricsService()

    first = service.build(
        predictions_path,
        manifest_path,
        tmp_path / 'first',
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = service.build(
        predictions_path,
        manifest_path,
        tmp_path / 'second',
        built_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert first.evaluation_key == second.evaluation_key
    assert first.evaluated_predictions == 12
    assert first.metric_rows == 21
    assert first.reliability_rows == 210
    assert first.metrics_path.read_bytes() == second.metrics_path.read_bytes()
    assert first.reliability_path.read_bytes() == second.reliability_path.read_bytes()
    assert first.summary_path.read_bytes() == second.summary_path.read_bytes()
    summary = first.summary_path.read_text(encoding='utf-8')
    assert 'seasonal_climatology' in summary
    assert 'T6.4 must add rolling temporal validation' in summary
    manifest = json.loads(first.manifest_path.read_text(encoding='utf-8'))
    assert manifest['source_comparison']['comparison_key'] == (
        'baseline-comparison:test-key'
    )
    assert manifest['counts']['metric_rows'] == 21
    assert manifest['files']['evaluation_metrics.csv']['rows'] == 21


def test_unavailable_prediction_is_counted_but_not_scored(tmp_path):
    rows = _prediction_rows()
    target = next(
        row
        for row in rows
        if row['approach'] == 'combined' and row['target_day_number'] == 31
    )
    target.update(
        {
            'status': 'unavailable',
            'predicted_precipitation_mm': '',
            'predicted_wet_probability_pct': '',
            'reason_code': 'source_features_unavailable',
        }
    )
    predictions_path, manifest_path = _write_predictions(tmp_path, rows)
    predictions, _, _ = BaselinePredictionReader().read(
        predictions_path, manifest_path
    )

    metrics, _ = EvaluationMetricsEngine().evaluate(predictions)
    combined = _overall(metrics, 'combined')

    assert combined.total_rows == 4
    assert combined.available_rows == 3
    assert combined.evaluated_rows == 3


def test_reader_rejects_checksum_mismatch(tmp_path):
    predictions_path, manifest_path = _write_predictions(tmp_path)
    predictions_path.write_text('changed\n', encoding='utf-8')

    with pytest.raises(ValueError, match='checksum'):
        BaselinePredictionReader().read(predictions_path, manifest_path)


def test_reader_rejects_unmatched_approach_identities(tmp_path):
    rows = _prediction_rows()
    rows.pop()
    predictions_path, manifest_path = _write_predictions(tmp_path, rows)

    with pytest.raises(ValueError, match='matched identities'):
        BaselinePredictionReader().read(predictions_path, manifest_path)


def test_reader_rejects_unmatched_outcomes(tmp_path):
    rows = _prediction_rows()
    target = next(
        row
        for row in rows
        if row['approach'] == 'combined'
        and row['season_type'] == 'margazhi'
        and row['target_day_number'] == 31
    )
    target['target_date_local'] = '2022-02-03'
    predictions_path, manifest_path = _write_predictions(tmp_path, rows)

    with pytest.raises(ValueError, match='matched outcomes'):
        BaselinePredictionReader().read(predictions_path, manifest_path)


@pytest.mark.parametrize(
    'values, message',
    [
        ((-1, 10, 30), 'between 0 and 100'),
        ((50, 3, 30), 'divide 100'),
        ((50, 10, 0), 'positive'),
    ],
)
def test_metric_spec_rejects_invalid_values(values, message):
    with pytest.raises(ValueError, match=message):
        EvaluationMetricSpec(*values)
