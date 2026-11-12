import hashlib
import json

from karuvottam.baseline_comparison import DatasetExample
from karuvottam.calibration_validation import export, select_samples


def _example(key, year, target_date):
    return DatasetExample(
        dataset_key='dataset-1', season_type='aadi', season_year=year,
        source_window_key=key, target_day_number=1,
        target_date_local=target_date, target_month=12,
        source_quality_flag='complete', target_quality_flag='complete',
        observed_precipitation_mm=1.0, source_features=(1.0,),
    )


def test_calibration_embargo_excludes_training_outcomes_crossing_test_start():
    windows = [
        {'source_window_key': 'aadi:2020', 'season_year': 2020,
         'start_local': '2020-07-01T00:00:00+05:30',
         'end_local': '2020-07-19T00:00:00+05:30'},
        {'source_window_key': 'margazhi:2021', 'season_year': 2021,
         'start_local': '2021-12-15T00:00:00+05:30',
         'end_local': '2021-12-26T00:00:00+05:30'},
        {'source_window_key': 'aadi:2022', 'season_year': 2022,
         'start_local': '2022-07-01T00:00:00+05:30',
         'end_local': '2022-07-19T00:00:00+05:30'},
    ]
    examples = (
        _example('aadi:2020', 2020, '2021-01-01'),
        _example('margazhi:2021', 2021, '2022-07-02'),
        _example('aadi:2022', 2022, '2022-12-01'),
    )
    samples, embargoed, training_windows = select_samples(
        examples, windows, {key['source_window_key']: 50 for key in windows},
        evaluation_start_year=2022, evaluation_end_year=2022,
        timezone_name='Asia/Kolkata', wet_threshold_mm=.1,
    )
    assert embargoed == ('margazhi:2021',)
    assert training_windows == 1
    assert {sample.source_window_key for sample in samples} == {
        'aadi:2020', 'aadi:2022',
    }
    assert all(sample.observed_rain for sample in samples)


def test_calibration_report_export_has_matching_checksum(tmp_path):
    path = export({'dataset_key': 'dataset-1', 'calibration_status': 'withheld'},
                  tmp_path)
    manifest = json.loads((tmp_path / 'calibration_manifest.json').read_text())
    assert manifest['calibration_report_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
