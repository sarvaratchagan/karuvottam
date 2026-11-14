from datetime import datetime
import hashlib

import pytest

pytest.importorskip('sklearn')

from karuvottam.advanced_ml_evaluation import (
    AdvancedSpec, _feature, _paired, eligible_training,
    verify_file_checksums,
)
from karuvottam.baseline_comparison import DatasetExample
from karuvottam.time_series_validation import (
    SourceWindowMetadata, ValidationDataset,
)


def example(year, day, target, window, *, rain=1.0):
    return DatasetExample('dataset', 'aadi', year, window, day, target,
        int(target[5:7]), 'complete', 'complete', rain,
        (10.0, 30.0, 60.0, 50.0, 8.0))


def window(year, start):
    return SourceWindowMetadata('v1', 'dataset', 'aadi', year,
        f'aadi:{year}', datetime.fromisoformat(start),
        datetime.fromisoformat(start), 'rule', 'timeline', 'measure')


def test_training_excludes_same_year_and_outcomes_after_cutoff():
    windows = {'aadi:2019': window(2019, '2019-06-01T00:00:00+05:30'),
               'aadi:2020': window(2020, '2020-06-21T00:00:00+05:30')}
    rows = (example(2019, 1, '2020-06-20', 'aadi:2019'),
            example(2019, 2, '2020-06-21', 'aadi:2019'),
            example(2020, 1, '2020-12-01', 'aadi:2020'))
    dataset = ValidationDataset(rows, {}, 'sha', windows, 'v1', 'rule',
                                'timeline', 'measure')
    eligible = eligible_training(dataset, 'aadi:2020', AdvancedSpec())
    assert eligible == rows[:1]


def test_features_use_only_source_and_known_calendar_values():
    dry = example(2019, 1, '2020-06-20', 'aadi:2019', rain=0.0)
    wet = example(2019, 1, '2020-06-20', 'aadi:2019', rain=100.0)
    assert _feature(dry) == _feature(wet)
    assert len(_feature(dry)) == 9


def test_paired_comparison_rejects_mismatched_outcomes():
    result = {'season_type': 'aadi', 'season_year': 2020,
        'target_day_number': 1, 'source_window_key': 'aadi:2020',
        'target_date_local': '2020-12-01', 'status': 'available',
        'observed_precipitation_mm': 1.0,
        'predicted_wet_probability_pct': 60.0,
        'predicted_precipitation_mm': 1.2}
    baseline = {('aadi', 2020, 1): {
        'source_window_key': 'aadi:2020', 'target_date_local': '2020-12-01',
        'status': 'available', 'observed_precipitation_mm': '0.0',
        'observed_wet_day': '0', 'predicted_wet_probability_pct': '40.0',
        'predicted_precipitation_mm': '0.5'}}
    with pytest.raises(ValueError, match='not paired'):
        _paired([result], baseline, AdvancedSpec())


def test_artifact_verification_rejects_changed_bytes(tmp_path):
    path = tmp_path / 'advanced_predictions.csv'
    path.write_bytes(b'original')
    manifest = {'files': {path.name: {'bytes': 8,
        'sha256': hashlib.sha256(b'original').hexdigest()}}}
    verify_file_checksums(tmp_path, manifest)
    path.write_bytes(b'changed!')
    with pytest.raises(ValueError, match='checksum mismatch'):
        verify_file_checksums(tmp_path, manifest)
