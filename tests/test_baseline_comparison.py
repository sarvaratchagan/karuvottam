import csv
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from karuvottam.baseline_comparison import (
    APPROACHES,
    BaselineComparisonEngine,
    BaselineComparisonService,
    BaselineComparisonSpec,
    DatasetExample,
    EvaluationDatasetReader,
    REQUIRED_COLUMNS,
)


def _write_dataset(tmp_path, rows):
    dataset_path = tmp_path / 'evaluation_dataset.csv'
    columns = sorted(REQUIRED_COLUMNS)
    with dataset_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / 'manifest.json'
    manifest_path.write_text(
        json.dumps(
            {
                'dataset_version': 'test-dataset-1.0',
                'dataset_key': 'test-dataset:key',
                'files': {dataset_path.name: {'sha256': digest}},
            }
        ),
        encoding='utf-8',
    )
    return dataset_path, manifest_path


def _row(year, season, day, rainfall, *, source_quality='complete',
         target_quality='complete', missing_feature=False):
    month = 1 if season == 'aadi' else 8
    return {
        'dataset_version': 'test-dataset-1.0',
        'dataset_key': 'test-dataset:key',
        'season_type': season,
        'season_year': year,
        'source_window_key': f'{season}:{year}:test-rule',
        'target_day_number': day,
        'target_date_local': f'{year + 1:04d}-{month:02d}-{day:02d}',
        'source_quality_flag': source_quality,
        'target_quality_flag': target_quality,
        'observed_precipitation_mm': rainfall,
        'source_precipitation_mm': '' if missing_feature else 10 + year % 5,
        'source_mean_temperature_c': 25 + year % 3,
        'source_mean_relative_humidity_pct': 70 + year % 4,
        'source_mean_cloud_cover_pct': 50 + year % 6,
        'source_mean_wind_speed_kmh': 5 + year % 2,
    }


def _dataset_rows():
    return [
        _row(year, season, day, rainfall=(year % 4) + day / 10)
        for year in range(2018, 2022)
        for season in ('aadi', 'margazhi')
        for day in (1, 2)
    ]


def _read_predictions(path):
    with path.open(encoding='utf-8', newline='') as stream:
        return list(csv.DictReader(stream))


def test_service_emits_three_approaches_for_identical_holdout_rows(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path, _dataset_rows())
    spec = BaselineComparisonSpec(2018, 2020, 2021, 2021)

    artifact = BaselineComparisonService().build(
        dataset_path,
        manifest_path,
        tmp_path / 'output',
        spec,
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    predictions = _read_predictions(artifact.predictions_path)

    assert artifact.evaluation_rows == 4
    assert artifact.prediction_rows == 12
    assert artifact.available_predictions == 12
    assert {row['approach'] for row in predictions} == set(APPROACHES)
    identities = {
        approach: {
            (row['season_type'], row['season_year'], row['target_day_number'])
            for row in predictions
            if row['approach'] == approach
        }
        for approach in APPROACHES
    }
    assert len(set(map(frozenset, identities.values()))) == 1
    assert all(row['training_end_year'] == '2020' for row in predictions)
    assert all(row['season_year'] == '2021' for row in predictions)
    assert all(row['predicted_precipitation_mm'] for row in predictions)
    assert all(row['predicted_wet_probability_pct'] for row in predictions)

    manifest = json.loads(artifact.manifest_path.read_text(encoding='utf-8'))
    assert manifest['counts']['evaluation_rows'] == 4
    assert manifest['counts']['prediction_rows'] == 12
    assert set(manifest['models']) == set(APPROACHES)
    assert manifest['source_dataset']['dataset_key'] == 'test-dataset:key'


def _example(year, rainfall, *, features=(10.0, 25.0, 70.0, 50.0, 5.0)):
    return DatasetExample(
        dataset_key='dataset:key',
        season_type='aadi',
        season_year=year,
        source_window_key=f'aadi:{year}:rule',
        target_day_number=1,
        target_date_local=f'{year + 1}-01-01',
        target_month=1,
        source_quality_flag='complete',
        target_quality_flag='complete',
        observed_precipitation_mm=rainfall,
        source_features=features,
    )


def test_evaluation_outcome_is_not_used_to_generate_predictions():
    training = (_example(2018, 0.0), _example(2019, 4.0), _example(2020, 8.0))
    evaluation = _example(2021, 1.0)
    spec = BaselineComparisonSpec(2018, 2020, 2021, 2021)

    first = BaselineComparisonEngine(spec).run((*training, evaluation))
    second = BaselineComparisonEngine(spec).run(
        (*training, replace(evaluation, observed_precipitation_mm=999.0))
    )

    assert [item.predicted_precipitation_mm for item in first] == [
        item.predicted_precipitation_mm for item in second
    ]
    assert [item.predicted_wet_probability_pct for item in first] == [
        item.predicted_wet_probability_pct for item in second
    ]


def test_missing_source_features_leave_only_seasonal_model_available():
    training = (_example(2018, 0.0), _example(2019, 4.0), _example(2020, 8.0))
    evaluation = _example(
        2021,
        1.0,
        features=(None, 25.0, 70.0, 50.0, 5.0),
    )

    predictions = BaselineComparisonEngine(
        BaselineComparisonSpec(2018, 2020, 2021, 2021)
    ).run((*training, evaluation))

    by_approach = {item.approach: item for item in predictions}
    assert by_approach['seasonal_climatology'].status == 'available'
    assert by_approach['karuvottam_only'].status == 'unavailable'
    assert by_approach['combined'].status == 'unavailable'
    assert by_approach['combined'].reason_code == 'source_features_unavailable'


def test_only_complete_training_outcomes_are_used():
    complete = _example(2018, 2.0)
    incomplete = replace(
        _example(2019, 200.0), target_quality_flag='warning'
    )
    evaluation = _example(2021, 5.0)

    predictions = BaselineComparisonEngine(
        BaselineComparisonSpec(2018, 2020, 2021, 2021)
    ).run((complete, incomplete, evaluation))

    assert all(
        item.predicted_precipitation_mm == 2.0
        for item in predictions
        if item.status == 'available'
    )


def test_reader_rejects_checksum_mismatch(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path, _dataset_rows())
    dataset_path.write_text('changed\n', encoding='utf-8')

    with pytest.raises(ValueError, match='checksum'):
        EvaluationDatasetReader().read(dataset_path, manifest_path)


def test_prediction_artifact_is_reproducible_across_build_times(tmp_path):
    dataset_path, manifest_path = _write_dataset(tmp_path, _dataset_rows())
    spec = BaselineComparisonSpec(2018, 2020, 2021, 2021)
    service = BaselineComparisonService()

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

    assert first.comparison_key == second.comparison_key
    assert first.predictions_sha256 == second.predictions_sha256
    assert first.predictions_path.read_bytes() == second.predictions_path.read_bytes()


@pytest.mark.parametrize(
    'values, message',
    [
        ((2020, 2019, 2021, 2022), 'training year range'),
        ((2018, 2020, 2020, 2022), 'begin after training'),
        ((2018, 2020, 2022, 2021), 'evaluation year range'),
    ],
)
def test_spec_rejects_overlapping_or_invalid_temporal_splits(values, message):
    with pytest.raises(ValueError, match=message):
        BaselineComparisonSpec(*values)
