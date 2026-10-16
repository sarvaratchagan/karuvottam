import csv
import json
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from karuvottam.calendar_engine import CalendarRule
from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.evaluation_dataset import (
    DATASET_VERSION,
    EvaluationDatasetBuilder,
    EvaluationDatasetSpec,
    MultiYearWeatherCollector,
)
from karuvottam.lunar_events import LunarEvent
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')
SOURCE = 'open-meteo:era5'


class FixedWindowEngine:
    calendar_rule = CalendarRule(version='test-rule-1.0')

    def generate(self, season_type, year):
        month = 7 if season_type == 'aadi' else 12
        start = datetime(year, month, 1, tzinfo=IST)
        event = LunarEvent(
            event_type='new_moon' if season_type == 'aadi' else 'full_moon',
            event_datetime_utc=start.astimezone(timezone.utc),
            event_datetime_local=start,
            source='fixed-test-provider',
            calculation_version='test-1.0',
        )
        return KaruvottamWindow(
            season_type=season_type,
            season_year=year,
            start_datetime_local=start,
            end_datetime_local=start + timedelta(hours=2),
            duration_hours=2,
            trigger_event=event,
            sunrise=None,
            rule_version=self.calendar_rule.version,
        )


@pytest.fixture()
def dataset_setup(tmp_path):
    database_path = tmp_path / 'karuvottam.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='Test target',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
    spec = EvaluationDatasetSpec(
        location_id=location.id,
        location_name=location.name,
        latitude=location.latitude,
        longitude=location.longitude,
        timezone_name=location.timezone_name,
        weather_source=SOURCE,
        start_year=2020,
        end_year=2020,
    )
    builder = EvaluationDatasetBuilder(data_access, FixedWindowEngine(), IST)
    return data_access, location, spec, builder, tmp_path


def _add_hour(data_access, location_id, interval_end_local, *, precipitation=1.0,
              interval_minutes=60, interpolated=False, raw_reference='raw/a.json'):
    interval_end_utc = interval_end_local.astimezone(timezone.utc)
    interval_start_utc = interval_end_utc - timedelta(minutes=interval_minutes)
    with data_access.transaction() as work:
        work.weather_observations.add(
            WeatherObservation(
                location_id=location_id,
                observed_at_utc=interval_end_utc,
                observed_at_local=interval_end_local,
                source=SOURCE,
                quality_flag='interpolated' if interpolated else 'valid',
                temperature_c=25,
                relative_humidity_pct=80,
                precipitation_mm=precipitation,
                cloud_cover_pct=70,
                wind_speed_kmh=8,
                wind_direction_deg=90,
                pressure_hpa=1005,
                is_interpolated=interpolated,
                raw_payload_reference=raw_reference,
                precipitation_interval_start_utc=interval_start_utc,
                precipitation_interval_end_utc=interval_end_utc,
                precipitation_interval_minutes=interval_minutes,
            )
        )


def _read_rows(path):
    return list(csv.DictReader(StringIO(path.read_text(encoding='utf-8'))))


def test_builder_links_source_window_to_daily_observed_rainfall(dataset_setup):
    data_access, location, spec, builder, tmp_path = dataset_setup
    for hour in (0, 1):
        _add_hour(
            data_access,
            location.id,
            datetime(2020, 7, 1, hour, 30, tzinfo=IST),
            precipitation=0.5,
        )
    # Aadi maps after the same year's Margazhi window, so day 1 is December 2.
    for hour in range(24):
        _add_hour(
            data_access,
            location.id,
            datetime(2020, 12, 2, hour, 30, tzinfo=IST),
            precipitation=1.0,
        )

    artifact = builder.build(
        spec,
        tmp_path / 'export',
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    rows = _read_rows(artifact.dataset_csv_path)
    first_aadi = next(
        row
        for row in rows
        if row['season_type'] == 'aadi' and row['target_day_number'] == '1'
    )

    assert artifact.row_count == 320
    assert first_aadi['source_window_key'] == 'aadi:2020:test-rule-1.0'
    assert first_aadi['source_observed_hours'] == '2'
    assert first_aadi['source_precipitation_mm'] == '1.0'
    assert first_aadi['target_date_local'] == '2020-12-02'
    assert first_aadi['target_observed_hours'] == '24'
    assert first_aadi['observed_precipitation_mm'] == '24.0'
    assert first_aadi['target_quality_flag'] == 'complete'
    assert artifact.complete_row_count == 1
    assert artifact.no_data_row_count == 319

    manifest = json.loads(artifact.manifest_path.read_text(encoding='utf-8'))
    assert manifest['dataset_version'] == DATASET_VERSION
    assert manifest['rows']['total'] == 320
    assert manifest['raw_payload_references'] == ['raw/a.json']
    assert len(manifest['windows']) == 2
    assert manifest['files']['evaluation_dataset.csv']['sha256'] == artifact.dataset_sha256


def test_missing_hours_are_not_zero_filled_and_are_exported_as_gaps(dataset_setup):
    data_access, location, spec, builder, tmp_path = dataset_setup
    _add_hour(
        data_access,
        location.id,
        datetime(2020, 12, 2, 0, 30, tzinfo=IST),
        precipitation=3.5,
    )

    artifact = builder.build(spec, tmp_path / 'export')
    first = next(
        row
        for row in _read_rows(artifact.dataset_csv_path)
        if row['season_type'] == 'aadi' and row['target_day_number'] == '1'
    )
    gaps = _read_rows(artifact.gaps_csv_path)

    assert first['target_observed_hours'] == '1'
    assert first['target_missing_hours'] == '23'
    assert first['observed_precipitation_mm'] == '3.5'
    assert first['target_quality_flag'] == 'warning'
    assert any(
        gap['scope'] == 'target_day'
        and gap['target_date_local'] == '2020-12-02'
        and gap['missing_hours'] == '23'
        for gap in gaps
    )


def test_incompatible_precipitation_interval_is_flagged_and_not_summed(dataset_setup):
    data_access, location, spec, builder, tmp_path = dataset_setup
    _add_hour(
        data_access,
        location.id,
        datetime(2020, 12, 2, 0, 30, tzinfo=IST),
        precipitation=9,
        interval_minutes=30,
    )

    artifact = builder.build(spec, tmp_path / 'export')
    first = next(
        row
        for row in _read_rows(artifact.dataset_csv_path)
        if row['season_type'] == 'aadi' and row['target_day_number'] == '1'
    )

    assert first['target_measurement_issue_hours'] == '1'
    assert first['observed_precipitation_mm'] == ''
    assert first['target_quality_flag'] == 'warning'


def test_dataset_csv_and_key_are_reproducible_across_build_times(dataset_setup):
    _, _, spec, builder, tmp_path = dataset_setup
    first = builder.build(
        spec,
        tmp_path / 'first',
        built_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    second = builder.build(
        spec,
        tmp_path / 'second',
        built_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert first.dataset_key == second.dataset_key
    assert first.dataset_sha256 == second.dataset_sha256
    assert first.gaps_sha256 == second.gaps_sha256
    assert first.dataset_csv_path.read_bytes() == second.dataset_csv_path.read_bytes()


def test_location_metadata_mismatch_is_rejected(dataset_setup):
    _, _, spec, builder, tmp_path = dataset_setup
    mismatched = EvaluationDatasetSpec(
        **{**spec.__dict__, 'location_name': 'Wrong target'}
    )

    with pytest.raises(ValueError, match='does not match'):
        builder.build(mismatched, tmp_path / 'export')


def test_multi_year_collector_uses_bounded_inclusive_chunks(dataset_setup):
    _, _, spec, builder, _ = dataset_setup

    class FakeIngestion:
        def __init__(self):
            self.calls = []

        def ingest(self, **kwargs):
            self.calls.append(kwargs)
            days = (kwargs['end_date'] - kwargs['start_date']).days + 1
            return SimpleNamespace(
                fetched_hours=days * 24,
                inserted_hours=days * 24,
                existing_hours=0,
                rejected_hours=0,
                payload_sha256=f'hash-{len(self.calls)}',
                raw_payload_reference=f'raw/{len(self.calls)}.json',
            )

    ingestion = FakeIngestion()
    collector = MultiYearWeatherCollector(ingestion, builder, chunk_days=100)

    report = collector.collect(spec)

    assert len(report.chunks) > 1
    assert all(
        (chunk.end_date - chunk.start_date).days < 100
        for chunk in report.chunks
    )
    assert all(
        previous.end_date + timedelta(days=1) == current.start_date
        for previous, current in zip(report.chunks, report.chunks[1:])
    )
    assert report.chunks[0].start_date == report.required_start_date
    assert report.chunks[-1].end_date == report.required_end_date
    assert report.inserted_hours == report.fetched_hours


@pytest.mark.parametrize(
    'updates, message',
    [
        ({'location_id': 0}, 'location_id'),
        ({'weather_source': ' '}, 'weather_source'),
        ({'start_year': 2021, 'end_year': 2020}, 'year range'),
    ],
)
def test_dataset_spec_rejects_invalid_identity(updates, message):
    values = {
        'location_id': 1,
        'location_name': 'Target',
        'latitude': 9.9,
        'longitude': 77.8,
        'timezone_name': 'Asia/Kolkata',
        'weather_source': SOURCE,
        'start_year': 2020,
        'end_year': 2020,
    }
    values.update(updates)

    with pytest.raises(ValueError, match=message):
        EvaluationDatasetSpec(**values)
