from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app import app
from karuvottam.data_access import DataAccess, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.observation_inspection import ObservationInspectionService


IST = ZoneInfo('Asia/Kolkata')


def _service(data_access: DataAccess) -> ObservationInspectionService:
    return ObservationInspectionService(
        data_access,
        location_name='சோதனை இடம்',
        latitude=9.9,
        longitude=77.8,
        timezone_name='Asia/Kolkata',
    )


def test_inspection_builds_series_and_distinguishes_interpolated_data(tmp_path):
    database_path = tmp_path / 'observations.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='சோதனை இடம்',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        for index, utc_hour in enumerate((19, 20, 22, 23)):
            observed_utc = datetime(2025, 12, 31, utc_hour, tzinfo=timezone.utc)
            work.weather_observations.add(
                WeatherObservation(
                    location_id=location.id,
                    observed_at_utc=observed_utc,
                    observed_at_local=observed_utc.astimezone(IST),
                    temperature_c=25 + index,
                    relative_humidity_pct=80 - index,
                    precipitation_mm=float(index),
                    cloud_cover_pct=None if index == 1 else 60 + index,
                    wind_speed_kmh=10 + index,
                    source='test-source',
                    quality_flag='interpolated' if index == 2 else 'valid',
                    is_interpolated=index == 2,
                )
            )

    result = _service(data_access).build(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 1),
        source='test-source',
    )

    assert result.location_record == location
    assert result.expected_hours == 24
    assert result.received_hours == 4
    assert result.coverage_pct == 16.67
    assert result.raw_count == 3
    assert result.interpolated_count == 1
    assert result.quality_counts == (('interpolated', 1), ('valid', 3))
    assert result.available_sources == ('test-source',)
    assert len(result.gaps) == 2
    assert sum(gap.missing_hours for gap in result.gaps) == 20
    temperature = result.series[0]
    cloud = result.series[2]
    assert len(temperature.points) == 4
    assert [len(segment) for segment in temperature.segments] == [2, 2]
    assert temperature.points[2].is_interpolated is True
    assert cloud.missing_value_count == 1

    html = app.jinja_env.get_template('observations.html').render(
        inspection=result,
        input_error=None,
    )
    assert '<svg class="time-series-chart"' in html
    assert 'class="series-point raw"' in html
    assert 'class="series-point interpolated"' in html
    assert '1 மணி' in html


def test_inspection_defaults_to_latest_source_and_local_week(tmp_path):
    database_path = tmp_path / 'observations.sqlite3'
    migrate_database(database_path)
    data_access = DataAccess(database_path)
    with data_access.transaction() as work:
        location = work.locations.add(
            name='சோதனை இடம்',
            latitude=9.9,
            longitude=77.8,
            elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        observed_utc = datetime(2026, 1, 5, 18, tzinfo=timezone.utc)
        work.weather_observations.add(
            WeatherObservation(
                location_id=location.id,
                observed_at_utc=observed_utc,
                observed_at_local=observed_utc.astimezone(IST),
                source='latest-source',
                quality_flag='valid',
            )
        )

    result = _service(data_access).build()

    assert result.selected_source == 'latest-source'
    assert result.end_date == date(2026, 1, 5)
    assert result.start_date == date(2025, 12, 30)


def test_inspection_handles_unmigrated_database(tmp_path):
    result = _service(DataAccess(tmp_path / 'unmigrated.sqlite3')).build(
        now=datetime(2026, 1, 7, tzinfo=IST)
    )

    assert result.database_available is False
    assert result.records == ()
    assert result.coverage_pct == 0
    assert any('migration' in warning for warning in result.warnings)
