import csv
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import app as app_module
from karuvottam.data_access import DataAccess, DuplicateRecordError, WeatherObservation
from karuvottam.database import migrate_database
from karuvottam.event_ingestion import DATASETS, SOURCE, import_ibtracs_csv
from karuvottam.event_model import EventTrackPoint
from karuvottam.event_tracks import EventTrackService, bearing_deg, great_circle_km
from karuvottam.event_impact import EventImpactService


@pytest.fixture
def access(tmp_path):
    path = tmp_path / 'events.sqlite3'
    migrate_database(path)
    return DataAccess(path)


def _csv(rows):
    stream = io.StringIO(newline='')
    fields = ['SID', 'BASIN', 'ISO_TIME', 'LAT', 'LON', 'TRACK_TYPE',
              'NEWDELHI_GRADE', 'NEWDELHI_WIND', 'NEWDELHI_PRES',
              'USA_STATUS', 'USA_WIND', 'USA_PRES']
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({})  # Official CSV's units row.
    writer.writerows(rows)
    return stream.getvalue().encode()


def _row(hour, grade, lat, lon, **other):
    return {
        'SID': '2026001N12084', 'BASIN': 'NI',
        'ISO_TIME': f'2026-01-01 {hour:02d}:00:00',
        'LAT': str(lat), 'LON': str(lon),
        'TRACK_TYPE': 'MAIN', 'NEWDELHI_GRADE': grade,
        'NEWDELHI_WIND': '30', 'NEWDELHI_PRES': '992',
        **other,
    }


def _import(access, payload, *, dataset='ni'):
    return import_ibtracs_csv(
        payload, access, dataset=dataset, source_url=DATASETS[dataset],
        retrieved_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )


def test_ibtracs_historical_import_is_idempotent_and_tracks_strengthening(access):
    payload = _csv([
        _row(0, 'D', 12, 84),
        _row(6, 'DD', 13, 83),
        _row(12, 'CS', 14, 82),
        _row(18, 'UNKNOWN', 15, 81),
        {**_row(21, 'D', 16, 80), 'BASIN': 'WP'},
    ])
    first = _import(access, payload)
    second = _import(access, payload)
    assert (first.rows_seen, first.rows_imported, first.rows_skipped) == (6, 3, 3)
    assert (second.rows_imported, second.rows_existing) == (0, 3)
    with access.transaction() as work:
        history = work.weather_events.history(SOURCE, '2026001N12084')
    assert [row.event_type for row in history] == [
        'depression', 'deep_depression', 'cyclone'
    ]
    assert [row.provider_classification for row in history] == ['D', 'DD', 'CS']
    assert history[0].maximum_wind_kmh == pytest.approx(55.56)
    assert history[0].source_url == DATASETS['ni']


def test_conflicting_revision_rolls_back_import(access):
    original = _csv([_row(0, 'D', 12, 84)])
    _import(access, original)
    with pytest.raises(DuplicateRecordError):
        _import(access, _csv([_row(0, 'DD', 13, 84)]))
    with access.transaction() as work:
        history = work.weather_events.history(SOURCE, '2026001N12084')
    assert len(history) == 1
    assert history[0].provider_classification == 'D'


def test_geometry_map_paths_and_revision_shift(access):
    _import(access, _csv([_row(0, 'D', 12, 84), _row(6, 'DD', 13, 83)]))
    issue_one = datetime(2026, 1, 1, tzinfo=timezone.utc)
    issue_two = issue_one + timedelta(hours=6)
    valid = issue_one + timedelta(hours=12)
    with access.transaction() as work:
        history = work.weather_events.history(SOURCE, '2026001N12084')
        for advisory, latitude, longitude, issue in (
            (history[0], 14, 82, issue_one),
            (history[1], 15, 81, issue_two),
        ):
            work.weather_events.record_point(
                advisory.id,
                EventTrackPoint(
                    valid_at=valid, latitude=latitude, longitude=longitude,
                    point_type='official_forecast', source='official',
                    quality_flag='source_verified', issued_at=issue,
                ),
            )
        work.weather_events.record_point(
            history[1].id,
            EventTrackPoint(
                valid_at=valid, latitude=16, longitude=80,
                point_type='model_guidance', source='model-a',
                quality_flag='guidance', issued_at=issue_two,
            ),
        )
    view = EventTrackService(
        access, target_latitude=9.9, target_longitude=77.9,
    ).build(2026, now=datetime(2026, 1, 5, tzinfo=timezone.utc))
    assert len(view.events) == 1
    assert [path.point_type for path in view.paths] == [
        'observed', 'official_forecast', 'official_forecast', 'model_guidance'
    ]
    assert view.motion.distance_km > 0
    assert view.motion.speed_kmh > 0
    assert view.forecast_shift_km > 0
    assert view.stale is True
    assert {shape.name for shape in view.countries} >= {'India', 'Sri Lanka'}
    assert {shape.name for shape in view.states} >= {'Tamil Nadu', 'Kerala'}
    assert any(label.name == 'வங்காள விரிகுடா' for label in view.map_labels)
    assert 40 < view.target.x < 860
    assert 40 < view.target.y < 460
    assert great_circle_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.1)
    assert bearing_deg(0, 0, 0, 1) == pytest.approx(90)
    impact = EventImpactService(
        access, location_name='சோதனை இடம்', target_latitude=9.9,
        target_longitude=77.9, timezone_name='Asia/Kolkata',
    ).build(view)
    assert impact.model_disagreement_km is not None
    assert impact.model_disagreement_km > 0


def test_active_usa_status_is_provisional_and_not_a_forecast(access):
    payload = _csv([{
        **_row(0, '', 12, 84, USA_STATUS='TD', USA_WIND='25'),
        'TRACK_TYPE': 'PROVISIONAL',
    }])
    report = _import(access, payload, dataset='active')
    assert report.rows_imported == 1
    view = EventTrackService(access, target_latitude=10, target_longitude=78).build(
        2026, now=datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    )
    assert view.selected.quality_flag == 'provisional'
    assert {path.point_type for path in view.paths} == {'observed'}
    assert view.stale is False


def test_impact_uses_complete_local_evidence_but_withholds_forecast(access):
    _import(access, _csv([_row(0, 'D', 12, 84), _row(6, 'DD', 13, 83)]))
    with access.transaction() as work:
        location = work.locations.add(
            name='சோதனை இடம்', latitude=9.9, longitude=77.9,
            elevation_m=0, timezone_name='Asia/Kolkata',
        )
        end = datetime(2026, 1, 1, 6, tzinfo=timezone.utc)
        for index in range(24):
            at = end - timedelta(hours=23-index)
            work.weather_observations.add(WeatherObservation(
                location_id=location.id, observed_at_utc=at,
                observed_at_local=at.astimezone(), source='test-gauge',
                quality_flag='valid', precipitation_mm=1,
                raw_payload_reference='test-gauge/batch-1.csv',
                relative_humidity_pct=80, cloud_cover_pct=70,
                wind_speed_kmh=12,
                precipitation_interval_start_utc=at-timedelta(hours=1),
                precipitation_interval_end_utc=at,
                precipitation_interval_minutes=60,
            ))
    track = EventTrackService(
        access, target_latitude=9.9, target_longitude=77.9,
    ).build(2026)
    impact = EventImpactService(
        access, location_name='சோதனை இடம்', target_latitude=9.9,
        target_longitude=77.9, timezone_name='Asia/Kolkata',
    ).build(track)
    assert impact.status == 'insufficient_evidence'
    assert impact.rain_mm == 24
    assert impact.observation_hours == impact.rain_hours == 24
    assert impact.humidity_pct == 80
    assert impact.cloud_cover_pct == 70
    assert impact.observation_references == ('test-gauge/batch-1.csv',)
    assert impact.distance_change_km is not None
    assert impact.model_disagreement_km is None
    assert any('எதிர்கால மழை மாதிரி' in gap for gap in impact.gaps)


def test_impact_does_not_sum_partial_or_invalid_rain(access):
    _import(access, _csv([_row(0, 'D', 12, 84)]))
    with access.transaction() as work:
        location = work.locations.add(
            name='சோதனை இடம்', latitude=9.9, longitude=77.9,
            elevation_m=0, timezone_name='Asia/Kolkata',
        )
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        work.weather_observations.add(WeatherObservation(
            location_id=location.id, observed_at_utc=at,
            observed_at_local=at.astimezone(), source='test-gauge',
            quality_flag='interpolated', is_interpolated=True,
            precipitation_mm=50,
            precipitation_interval_start_utc=at-timedelta(hours=1),
            precipitation_interval_end_utc=at,
            precipitation_interval_minutes=60,
        ))
    track = EventTrackService(access, target_latitude=9.9, target_longitude=77.9).build(2026)
    impact = EventImpactService(
        access, location_name='சோதனை இடம்', target_latitude=9.9,
        target_longitude=77.9, timezone_name='Asia/Kolkata',
    ).build(track)
    assert impact.rain_mm is None
    assert impact.rain_hours == 0
    assert impact.observation_source is None


def test_event_page_shows_provenance_and_separate_path_labels(access, monkeypatch):
    _import(access, _csv([_row(0, 'D', 12, 84), _row(6, 'DD', 13, 83)]))
    monkeypatch.setitem(
        app_module.app.extensions, 'event_track_service',
        EventTrackService(access, target_latitude=9.9, target_longitude=77.9),
    )
    monkeypatch.setitem(
        app_module.app.extensions, 'event_impact_service',
        EventImpactService(
            access, location_name='சோதனை இடம்', target_latitude=9.9,
            target_longitude=77.9, timezone_name='Asia/Kolkata',
        ),
    )
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        response = client.get('/events?year=2026')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'வானிலை நிகழ்வுப் பாதைகள்' in html
    assert '2026001N12084' in html
    assert 'NOAA IBTrACS CSV' in html
    assert 'event-path-observed' in html
    assert 'event-map-land' in html
    assert 'event-map-states' in html
    assert 'Natural Earth' in html
    assert 'தாக்க மதிப்பீடு: ஆதாரம் போதவில்லை' in html
    assert 'அதிகாரப்பூர்வ முன்னறிவிப்புப் பாதை இந்தத் தரவுத் தொகுப்பில் இல்லை' in html
    assert 'மாதிரி வழிகாட்டும் பாதை இந்தத் தரவுத் தொகுப்பில் இல்லை' in html
