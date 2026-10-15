import csv
import io
from datetime import datetime, timezone

import pytest

from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.weather_csv import (
    WEATHER_CSV_COLUMNS,
    WeatherCsvFormatError,
    WeatherCsvService,
)


def _service(tmp_path, database_name='weather.sqlite3'):
    database_path = tmp_path / database_name
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='தமிழ்நாடு இலக்கு',
            latitude=9.9040188,
            longitude=77.8860417,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
    return WeatherCsvService(data_access), data_access, location


def _row(hour=0, **overrides):
    utc_hour = f'{hour:02d}'
    local_hour = f'{hour + 5:02d}'
    values = {
        'observed_at_utc': f'2025-07-01T{utc_hour}:00:00Z',
        'observed_at_local': f'2025-07-01T{local_hour}:30:00+05:30',
        'temperature_c': '27.0',
        'relative_humidity_pct': '72',
        'precipitation_mm': '0.2',
        'cloud_cover_pct': '95',
        'wind_speed_kmh': '3.9',
        'wind_direction_deg': '254',
        'pressure_hpa': '1007.7',
        'source': 'தமிழ்-வானிலை',
        'is_interpolated': 'false',
        'quality_flag': 'valid',
        'raw_payload_reference': 'மூலம்/தரவு.json',
        'precipitation_interval_start_utc': (
            '2025-06-30T23:00:00Z'
            if hour == 0
            else f'2025-07-01T{hour - 1:02d}:00:00Z'
        ),
        'precipitation_interval_end_utc': f'2025-07-01T{utc_hour}:00:00Z',
        'precipitation_interval_minutes': '60',
    }
    values.update(overrides)
    return values


def _csv_text(rows, fieldnames=WEATHER_CSV_COLUMNS):
    output = io.StringIO(newline='')
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        lineterminator='\n',
        extrasaction='ignore',
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def test_preview_reports_bad_rows_and_import_is_idempotent(tmp_path):
    service, data_access, location = _service(tmp_path)
    text = _csv_text(
        [
            _row(0),
            _row(1, temperature_c='not-a-number'),
            _row(2, pressure_hpa='700'),
        ]
    )

    preview = service.preview_import(text, location_id=location.id)

    assert preview.total_rows == 3
    assert preview.accepted_rows == 1
    assert preview.rejected_rows == 2
    assert [row.quality_flag for row in preview.rows] == [
        'valid',
        'invalid_csv',
        'out_of_range',
    ]
    assert preview.rows[1].errors == ('temperature_c must be numeric or blank',)
    assert preview.rows[2].errors == ('out_of_range:pressure_hpa',)

    first = service.import_preview(preview)
    second = service.import_preview(preview)

    assert first.inserted_rows == 1
    assert first.existing_rows == 0
    assert first.rejected_rows == 2
    assert second.inserted_rows == 0
    assert second.existing_rows == 1
    with data_access.transaction() as work:
        records = work.weather_observations.list_between(
            location.id,
            datetime(2025, 7, 1, tzinfo=timezone.utc),
            datetime(2025, 7, 1, 23, tzinfo=timezone.utc),
        )
    assert len(records) == 1


def test_preview_reports_duplicates_and_internal_missing_hours(tmp_path):
    service, _, location = _service(tmp_path)
    first = _row(0)
    preview = service.preview_import(
        _csv_text([first, dict(first), _row(2)]),
        location_id=location.id,
    )

    assert [row.quality_flag for row in preview.rows] == [
        'valid',
        'duplicate',
        'valid',
    ]
    assert preview.accepted_rows == 2
    assert preview.rejected_rows == 1
    assert preview.quality_report is not None
    assert preview.quality_report.duplicate_records == 1
    assert preview.quality_report.missing_hours == (
        datetime(2025, 7, 1, 1, tzinfo=timezone.utc),
    )
    assert preview.quality_report.coverage_pct == 66.67


def test_utf8_tamil_export_import_round_trip(tmp_path):
    source_service, _, source_location = _service(tmp_path, 'source.sqlite3')
    source_preview = source_service.preview_import(
        _csv_text(
            [
                _row(0, source='தமிழ், வானிலை'),
                _row(1, pressure_hpa=''),
            ]
        ),
        location_id=source_location.id,
    )
    source_service.import_preview(source_preview)
    exported = source_service.export(
        location_id=source_location.id,
        start_utc=datetime(2025, 7, 1, tzinfo=timezone.utc),
        end_utc=datetime(2025, 7, 1, 1, tzinfo=timezone.utc),
    )

    assert '"தமிழ், வானிலை"' in exported
    assert 'மூலம்/தரவு.json' in exported
    destination_service, _, destination_location = _service(
        tmp_path, 'destination.sqlite3'
    )
    destination_preview = destination_service.preview_import(
        exported.encode('utf-8'),
        location_id=destination_location.id,
    )
    imported = destination_service.import_preview(destination_preview)
    reexported = destination_service.export(
        location_id=destination_location.id,
        start_utc=datetime(2025, 7, 1, tzinfo=timezone.utc),
        end_utc=datetime(2025, 7, 1, 1, tzinfo=timezone.utc),
    )

    assert imported.inserted_rows == 2
    assert reexported == exported


def test_utf8_bom_is_accepted(tmp_path):
    service, _, location = _service(tmp_path)
    data = b'\xef\xbb\xbf' + _csv_text([_row(0)]).encode('utf-8')

    preview = service.preview_import(data, location_id=location.id)

    assert preview.accepted_rows == 1


def test_non_utf8_bytes_are_rejected(tmp_path):
    service, _, location = _service(tmp_path)

    with pytest.raises(WeatherCsvFormatError, match='UTF-8'):
        service.preview_import(b'\xff\xfeinvalid', location_id=location.id)


def test_missing_required_header_is_rejected(tmp_path):
    service, _, location = _service(tmp_path)
    columns = tuple(column for column in WEATHER_CSV_COLUMNS if column != 'source')

    with pytest.raises(WeatherCsvFormatError, match='source'):
        service.preview_import(
            _csv_text([_row(0)], fieldnames=columns),
            location_id=location.id,
        )


@pytest.mark.parametrize(
    'overrides, message',
    [
        ({'observed_at_utc': '2025-07-01T00:30:00Z'}, 'exact hour'),
        (
            {'observed_at_local': '2025-07-01T00:00:00Z'},
            'location timezone',
        ),
        ({'is_interpolated': 'maybe'}, 'true, false'),
        ({'precipitation_interval_minutes': ''}, 'provided together'),
        (
            {'precipitation_interval_start_utc': '2025-06-30T22:00:00Z'},
            'duration does not match',
        ),
    ],
)
def test_row_format_errors_are_reported_in_preview(tmp_path, overrides, message):
    service, _, location = _service(tmp_path)

    preview = service.preview_import(
        _csv_text([_row(0, **overrides)]),
        location_id=location.id,
    )

    assert preview.accepted_rows == 0
    assert preview.rows[0].quality_flag == 'invalid_csv'
    assert message in preview.rows[0].errors[0]


def test_export_can_filter_source_and_uses_stable_column_order(tmp_path):
    service, _, location = _service(tmp_path)
    preview = service.preview_import(
        _csv_text([_row(0), _row(1, source='other-provider')]),
        location_id=location.id,
    )
    service.import_preview(preview)

    exported = service.export(
        location_id=location.id,
        start_utc=datetime(2025, 7, 1, tzinfo=timezone.utc),
        end_utc=datetime(2025, 7, 1, 1, tzinfo=timezone.utc),
        source='தமிழ்-வானிலை',
    )
    rows = list(csv.DictReader(io.StringIO(exported)))

    assert exported.splitlines()[0].split(',') == list(WEATHER_CSV_COLUMNS)
    assert len(rows) == 1
    assert rows[0]['source'] == 'தமிழ்-வானிலை'
