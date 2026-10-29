import csv
import hashlib
import json
from datetime import datetime, timezone

import pytest

from karuvottam.baseline_comparison import REQUIRED_COLUMNS
from karuvottam.time_series_validation import (
    RollingValidationSpec,
    TimeSeriesValidationService,
    ValidationDatasetReader,
)


EXTRA_COLUMNS = (
    'source_window_start_local',
    'source_window_end_local',
    'calendar_rule_version',
    'timeline_model_version',
    'measurement_contract_version',
)


def _dataset_rows():
    rows = []
    for year in range(2018, 2022):
        for season in ('aadi', 'margazhi'):
            if season == 'aadi':
                start = f'{year}-06-21T00:00:00+05:30'
                end = f'{year}-07-09T00:00:00+05:30'
                targets = (
                    f'{year}-12-27',
                    f'{year}-12-28',
                )
            else:
                start = f'{year}-12-15T00:00:00+05:30'
                end = f'{year}-12-26T00:00:00+05:30'
                targets = (
                    f'{year + 1}-07-10',
                    f'{year + 1}-07-11',
                )
            for day, target in enumerate(targets, start=1):
                row = {column: '' for column in REQUIRED_COLUMNS}
                row.update(
                    {
                        'dataset_version': 'evaluation-dataset-test-1.0',
                        'dataset_key': 'evaluation-dataset:test-key',
                        'season_type': season,
                        'season_year': year,
                        'source_window_key': f'{season}:{year}:test-rule',
                        'source_window_start_local': start,
                        'source_window_end_local': end,
                        'target_day_number': day,
                        'target_date_local': target,
                        'source_quality_flag': 'complete',
                        'target_quality_flag': 'complete',
                        'observed_precipitation_mm': (
                            0.0 if day == 1 else 1.0 + year % 3
                        ),
                        'source_precipitation_mm': 10 + year % 5,
                        'source_mean_temperature_c': 25 + year % 3,
                        'source_mean_relative_humidity_pct': 70 + year % 4,
                        'source_mean_cloud_cover_pct': 50 + year % 6,
                        'source_mean_wind_speed_kmh': 5 + year % 2,
                        'calendar_rule_version': 'calendar-test-1.0',
                        'timeline_model_version': 'timeline-test-1.0',
                        'measurement_contract_version': 'measurement-test-1.0',
                    }
                )
                rows.append(row)
    return rows


def _write_dataset(tmp_path, rows=None):
    data_rows = rows or _dataset_rows()
    columns = sorted(set(REQUIRED_COLUMNS) | set(EXTRA_COLUMNS))
    dataset_path = tmp_path / 'evaluation_dataset.csv'
    with dataset_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(
            stream, fieldnames=columns, lineterminator='\n'
        )
        writer.writeheader()
        writer.writerows(data_rows)
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(
        json.dumps(
            {
                'dataset_version': 'evaluation-dataset-test-1.0',
                'dataset_key': 'evaluation-dataset:test-key',
                'files': {
                    dataset_path.name: {
                        'sha256': digest,
                        'rows': len(data_rows),
                    }
                },
            }
        ),
        encoding='utf-8',
    )
    return dataset_path, manifest_path


def _read_csv(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def test_service_builds_expanding_as_of_folds_and_pooled_metrics(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path)
    artifact = TimeSeriesValidationService().build(
        dataset_path,
        manifest_path,
        tmp_path / 'output',
        RollingValidationSpec(2018, 2020, 2021),
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert artifact.fold_count == 2
    assert artifact.prediction_rows == 24
    assert artifact.evaluated_predictions == 24
    assert artifact.leakage_checks == 4
    predictions = _read_csv(artifact.predictions_path)
    assert {row['evaluation_year'] for row in predictions} == {'2020', '2021'}
    assert {
        (row['evaluation_year'], row['training_end_year'])
        for row in predictions
    } == {('2020', '2019'), ('2021', '2020')}
    assert all(
        int(row['training_end_year']) < int(row['evaluation_year'])
        for row in predictions
    )
    assert {row['approach'] for row in predictions} == {
        'seasonal_climatology',
        'karuvottam_only',
        'combined',
    }

    folds = _read_csv(artifact.folds_path)
    assert len(folds) == 4
    assert all(row['leakage_check'] == 'passed' for row in folds)
    assert all(
        not row['latest_eligible_training_outcome']
        or row['latest_eligible_training_outcome']
        < row['as_of_cutoff_local'][:10]
        for row in folds
    )
    aadi_2020 = next(
        row
        for row in folds
        if row['evaluation_year'] == '2020' and row['season_type'] == 'aadi'
    )
    assert int(aadi_2020['excluded_not_yet_observed_outcomes']) == 2

    metrics = _read_csv(artifact.metrics_path)
    assert {row['scope'] for row in metrics} == {'fold', 'pooled'}
    assert len(metrics) == 54
    pooled = [
        row
        for row in metrics
        if row['scope'] == 'pooled' and row['dimension'] == 'overall'
    ]
    assert len(pooled) == 3
    assert all(row['evaluated_rows'] == '8' for row in pooled)


def test_reports_are_reproducible_across_build_timestamps(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path)
    service = TimeSeriesValidationService()
    spec = RollingValidationSpec(2018, 2020, 2021)

    first = service.build(
        dataset_path,
        manifest_path,
        tmp_path / 'first',
        spec,
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = service.build(
        dataset_path,
        manifest_path,
        tmp_path / 'second',
        spec,
        built_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert first.validation_key == second.validation_key
    for name in (
        'predictions_path',
        'folds_path',
        'metrics_path',
        'reliability_path',
        'summary_path',
    ):
        assert getattr(first, name).read_bytes() == getattr(second, name).read_bytes()
    first_manifest = json.loads(first.manifest_path.read_text(encoding='utf-8'))
    second_manifest = json.loads(second.manifest_path.read_text(encoding='utf-8'))
    first_manifest.pop('built_at_utc')
    second_manifest.pop('built_at_utc')
    assert first_manifest == second_manifest


def test_manifest_records_all_versions_and_file_hashes(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path)
    artifact = TimeSeriesValidationService().build(
        dataset_path,
        manifest_path,
        tmp_path / 'output',
        RollingValidationSpec(2018, 2020, 2021),
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    manifest = json.loads(artifact.manifest_path.read_text(encoding='utf-8'))
    assert manifest['versions']['calendar_rule'] == 'calendar-test-1.0'
    assert manifest['versions']['timeline_model'] == 'timeline-test-1.0'
    assert manifest['versions']['measurement_contract'] == 'measurement-test-1.0'
    assert set(manifest['versions']['models']) == {
        'seasonal_climatology',
        'karuvottam_only',
        'combined',
    }
    assert manifest['publication_state']['probability_output_enabled'] is False
    for filename, details in manifest['files'].items():
        path = artifact.manifest_path.parent / filename
        assert hashlib.sha256(path.read_bytes()).hexdigest() == details['sha256']


def test_reader_rejects_mixed_rule_versions(tmp_path):
    rows = _dataset_rows()
    for row in rows:
        if row['source_window_key'] == 'margazhi:2021:test-rule':
            row['calendar_rule_version'] = 'calendar-test-2.0'
    dataset_path, manifest_path = _write_dataset(tmp_path, rows)

    with pytest.raises(ValueError, match='calendar_rule_version'):
        ValidationDatasetReader().read(dataset_path, manifest_path)


def test_service_rejects_missing_requested_year(tmp_path):
    rows = [row for row in _dataset_rows() if int(row['season_year']) != 2019]
    dataset_path, manifest_path = _write_dataset(tmp_path, rows)

    with pytest.raises(ValueError, match='missing requested season years'):
        TimeSeriesValidationService().build(
            dataset_path,
            manifest_path,
            tmp_path / 'output',
            RollingValidationSpec(2018, 2020, 2021),
        )


@pytest.mark.parametrize(
    'values, message',
    [
        ((2020, 2020, 2021), 'must follow'),
        ((2018, 2021, 2020), 'range is invalid'),
    ],
)
def test_spec_rejects_invalid_temporal_ranges(values, message):
    with pytest.raises(ValueError, match=message):
        RollingValidationSpec(*values)
