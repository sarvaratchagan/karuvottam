from datetime import datetime, timezone
from pathlib import Path
from shutil import copyfile
import os
import subprocess
import sys

import app as application
from karuvottam.data_access import DataAccess
from karuvottam.database import connect_database, migrate_database
from karuvottam.forecast_timeline import ForecastTimelineEngine, unavailable_research_score


def test_locations_isolate_rules_windows_and_saved_forecasts(tmp_path):
    database = tmp_path / 'multi.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    with access.transaction() as work:
        first = work.locations.add(
            name='முதல் இடம்', latitude=9.9, longitude=77.8,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        second = work.locations.add(
            name='இரண்டாம் இடம்', latitude=10.8, longitude=78.5,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        work.locations.set_rules(
            second.id, chithirai_reference='03-22', rule_version='local-2.0',
            margazhi_anchor_year=2026, margazhi_anchor_phase='full_moon',
        )
        assert work.locations.rules(first.id) is None
        assert work.locations.rules(second.id).rule_version == 'local-2.0'
        window = application.WINDOW_ENGINE.generate('aadi', 2026)
        event = work.lunar_events.add(window.trigger_event)
        first_window = work.karuvottam_windows.add(
            window, trigger_event_id=event.id, location_id=first.id,
        )
        second_window = work.karuvottam_windows.add(
            window, trigger_event_id=event.id, location_id=second.id,
        )
        timeline = ForecastTimelineEngine(application.LOCATION_TIMEZONE).generate(
            window,
            mapping_basis_end_local=application.WINDOW_ENGINE.generate('margazhi', 2026).end_datetime_local,
            research_score=unavailable_research_score('test_no_data'),
            generated_at=datetime(2026, 12, 31, tzinfo=timezone.utc),
        )
        first_run = work.forecasts.add_timeline(timeline, input_window_id=first_window.id)
        second_run = work.forecasts.add_timeline(timeline, input_window_id=second_window.id)
        assert work.karuvottam_windows.find('aadi', 2026, window.rule_version,
                                            location_id=first.id) == first_window
        assert work.karuvottam_windows.find('aadi', 2026, window.rule_version,
                                            location_id=second.id) == second_window
        assert work.forecasts.latest_run(first.id) == first_run
        assert work.forecasts.latest_run(second.id) == second_run
        assert first_run.location_id != second_run.location_id
    with connect_database(database) as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_selected_location_changes_ui_and_does_not_use_other_weather(tmp_path, monkeypatch):
    database = tmp_path / 'multi-ui.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    with access.transaction() as work:
        first = work.locations.add(
            name=application.settings.location_name,
            latitude=application.settings.latitude,
            longitude=application.settings.longitude,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        second = work.locations.add(
            name='இரண்டாம் இடம்', latitude=10.8, longitude=78.5,
            elevation_m=None, timezone_name='Asia/Kolkata',
        )
        work.locations.set_rules(
            second.id, chithirai_reference='03-22', rule_version='local-2.0',
            margazhi_anchor_year=2026, margazhi_anchor_phase='full_moon',
        )
    monkeypatch.setitem(application.app.extensions, 'data_access', access)
    with application.app.test_client() as client:
        home = client.get(f'/?year=2026&location={second.id}').get_data(as_text=True)
        calendar = client.get(f'/calendar?year=2026&location={second.id}').get_data(as_text=True)
        prediction = client.get(f'/prediction?year=2026&location={second.id}').get_data(as_text=True)
        exported = client.get(f'/prediction.csv?year=2026&location={second.id}')
        events = client.get(f'/events?year=2026&location={second.id}').get_data(as_text=True)
    assert 'இரண்டாம் இடம்' in home
    assert f'location={second.id}' in home
    assert 'local-2.0' in calendar
    assert 'இரண்டாம் இடம்' in prediction
    assert 'source_window_observations_not_found' in exported.get_data(as_text=True)
    assert f'location-{second.id}' in exported.headers['Content-Disposition']
    assert 'இரண்டாம் இடம்' in events
    assert 'சரிபார்க்கப்பட்ட மாதிரி ஒப்பீடு கிடைக்கவில்லை' in events
    assert first.id != second.id


def test_migration_assigns_single_existing_location_to_legacy_runs(tmp_path):
    source = Path(__file__).parents[1] / 'karuvottam' / 'migrations'
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    for version in ('001', '002', '003', '004', '005'):
        path = next(source.glob(f'{version}_*.sql'))
        copyfile(path, legacy / path.name)
    database = tmp_path / 'legacy.sqlite3'
    migrate_database(database, legacy)
    with connect_database(database) as connection:
        location_id = connection.execute('''
            INSERT INTO locations (name, latitude, longitude, timezone)
            VALUES ('Legacy place', 9.9, 77.8, 'Asia/Kolkata')
        ''').lastrowid
        window_id = connection.execute('''
            INSERT INTO karuvottam_windows (
                season_type, season_year, start_datetime_local,
                end_datetime_local, duration_hours, rule_version, status
            ) VALUES ('aadi', 2026, '2026-07-01T00:00:00+05:30',
                      '2026-07-19T00:00:00+05:30', 432, '2.0', 'calculated')
        ''').lastrowid
        run_id = connection.execute('''
            INSERT INTO prediction_runs (
                season_type, season_year, prediction_start, prediction_end,
                input_window_id, rule_version, model_version, status
            ) VALUES ('aadi', 2026, '2027-01-01', '2027-06-29', ?,
                      '2.0', 'daily-timeline-1.0', 'research')
        ''', (window_id,)).lastrowid
        connection.execute('''
            INSERT INTO predictions (
                prediction_run_id, target_datetime_local, prediction_method,
                model_version, generated_at
            ) VALUES (?, '2027-01-01T00:00:00+05:30', 'research',
                      'daily-timeline-1.0', '2026-12-31T00:00:00Z')
        ''', (run_id,))
    migrate_database(database)
    with connect_database(database) as connection:
        assert connection.execute(
            'SELECT location_id FROM karuvottam_windows WHERE id = ?', (window_id,),
        ).fetchone()['location_id'] == location_id
        assert connection.execute(
            'SELECT location_id FROM prediction_runs WHERE id = ?', (run_id,),
        ).fetchone()['location_id'] == location_id
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


def test_operator_can_add_location_and_override_rules(tmp_path):
    database = tmp_path / 'operator.sqlite3'
    migrate_database(database)
    env = {**os.environ, 'KARUVOTTAM_DATABASE_PATH': str(database)}
    added = subprocess.run([
        sys.executable, '-m', 'karuvottam.audit', 'add-location',
        '--name', 'Second site', '--latitude', '10.8', '--longitude', '78.5',
        '--actor', 'operator', '--reason', 'New site',
    ], env=env, capture_output=True, text=True, check=True)
    assert 'Second site' in added.stdout
    changed = subprocess.run([
        sys.executable, '-m', 'karuvottam.audit', 'set-location-rules',
        '--location-id', '1', '--chithirai-reference', '03-22',
        '--rule-version', 'local-2.0', '--margazhi-anchor-year', '2026',
        '--margazhi-anchor-phase', 'full_moon', '--actor', 'operator',
        '--reason', 'Local rule',
    ], env=env, capture_output=True, text=True, check=True)
    assert 'local-2.0' in changed.stdout
    with DataAccess(database).transaction() as work:
        assert work.locations.rules(1).chithirai_reference == '03-22'
        assert [entry.action for entry in work.audit.list_recent()] == [
            'location_rules_updated', 'location_added',
        ]
