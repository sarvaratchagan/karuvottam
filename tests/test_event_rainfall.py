import csv
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.event_ingestion import DATASETS, import_ibtracs_csv
from karuvottam.event_rainfall import (
    build_rows, distance_band, export, holdout_evaluation,
)


def _access(tmp_path, *, omit_during=False):
    database = tmp_path / 'events.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    stream = io.StringIO(newline='')
    fields = ['SID', 'BASIN', 'ISO_TIME', 'LAT', 'LON', 'TRACK_TYPE',
              'NEWDELHI_GRADE', 'USA_STATUS']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({})
    for hour, lon in ((0, 80), (6, 79)):
        writer.writerow({'SID': '2026002N12080', 'BASIN': 'NI',
                         'ISO_TIME': f'2026-01-02 {hour:02d}:00:00',
                         'LAT': '12', 'LON': str(lon), 'TRACK_TYPE': 'MAIN',
                         'NEWDELHI_GRADE': 'D'})
    import_ibtracs_csv(stream.getvalue().encode(), access, dataset='ni',
                       source_url=DATASETS['ni'],
                       retrieved_at=datetime(2026, 1, 4, tzinfo=timezone.utc))
    with access.transaction() as work:
        location = work.locations.add(
            name='target', latitude=10, longitude=78, elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        first = datetime(2026, 1, 2, tzinfo=timezone.utc)
        for step in range(-23, 31):
            if omit_during and step == 3:
                continue
            at = first + timedelta(hours=step)
            work.weather_observations.add(WeatherObservation(
                location_id=location.id, observed_at_utc=at,
                observed_at_local=at, source='test-rain', quality_flag='valid',
                precipitation_mm=1, raw_payload_reference='test/batch.csv',
                precipitation_interval_start_utc=at-timedelta(hours=1),
                precipitation_interval_end_utc=at,
                precipitation_interval_minutes=60,
            ))
    return access


@pytest.mark.parametrize('omit_during', [False, True])
def test_historical_event_windows_require_complete_hourly_rain(tmp_path, omit_during):
    access = _access(tmp_path, omit_during=omit_during)
    rows = build_rows(access, start_year=2026, end_year=2026,
                      location_name='target', latitude=10, longitude=78,
                      timezone_name='Asia/Kolkata', weather_source='test-rain')
    assert len(rows) == 1
    row = rows[0]
    assert (row.pre_expected_hours, row.during_expected_hours,
            row.post_expected_hours) == (24, 6, 24)
    assert row.pre_rain_mm == row.post_rain_mm == 24
    assert row.event_source_reference == 'IBTrACS SID 2026002N12080'
    assert row.weather_raw_references == 'test/batch.csv'
    if omit_during:
        assert row.quality == 'incomplete'
        assert row.during_valid_hours == 5
        assert row.during_rain_mm is None
    else:
        assert row.quality == 'complete'
        assert row.during_rain_mm == 6
        assert row.during_rain_mm_per_24h == 24
    summary = export(rows, tmp_path / 'out', start_year=2026, end_year=2026,
                     location_name='target', latitude=10, longitude=78)
    assert summary['complete_event_count'] == (0 if omit_during else 1)
    assert summary['csv_sha256']


def test_distance_bands_and_holdout_use_earlier_event_years_only(tmp_path):
    row = build_rows(_access(tmp_path), start_year=2026, end_year=2026,
                     location_name='target', latitude=10, longitude=78,
                     timezone_name='Asia/Kolkata', weather_source='test-rain')[0]
    assert [distance_band(value) for value in (249.9, 250, 500, 1000)] == [
        '<250', '250-499', '500-999', '1000+',
    ]
    synthetic = tuple(replace(
        row, event_key=str(year), event_year=year,
        first_at_utc=f'{year}-01-02T00:00:00+00:00',
        last_at_utc=f'{year}-01-02T06:00:00+00:00',
        during_rain_mm_per_24h=float(year-2015),
    ) for year in range(2015, 2025))
    result = holdout_evaluation(synthetic)
    assert result['status'] == 'evaluated'
    assert result['split_year'] == 2022
    assert (result['train_events'], result['test_events']) == (7, 3)
    assert result['baseline_mae_mm_per_24h'] == 5
