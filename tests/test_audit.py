import sqlite3

import pytest

import app as application
from karuvottam.audit import generate_forecast_run
from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.forecast_inputs import StoredForecastInputService


@pytest.fixture
def access(tmp_path):
    path = tmp_path / 'audit.sqlite3'
    migrate_database(path)
    return DataAccess(path)


def test_manual_location_edit_and_audit_are_atomic(access):
    with access.transaction() as work:
        location = work.locations.add(
            name='Target', latitude=10, longitude=77, elevation_m=0,
            timezone_name='Asia/Kolkata',
        )
        assert work.locations.set_active(
            location.id, False, actor='operator:alice', reason='Site temporarily closed'
        )
        assert not work.locations.set_active(
            location.id, False, actor='operator:alice', reason='Repeated request'
        )

    with access.transaction() as work:
        events = work.audit.list_recent()
        assert len(events) == 1
        assert (events[0].actor, events[0].action, events[0].record_type) == (
            'operator:alice', 'location_deactivated', 'location'
        )
        assert events[0].record_id == str(location.id)
        assert events[0].reason == 'Site temporarily closed'
        assert events[0].created_at.endswith('Z')

    with pytest.raises(RuntimeError):
        with access.transaction() as work:
            work.locations.set_active(
                location.id, True, actor='operator:alice', reason='Reopen'
            )
            raise RuntimeError('abort')
    with access.transaction() as work:
        assert not work.locations.get(location.id).is_active
        assert len(work.audit.list_recent()) == 1


def test_audit_rejects_blank_actor_and_reason(access):
    with pytest.raises(ValueError, match='actor'):
        with access.transaction() as work:
            work.audit.add(
                actor=' ', action='edit', record_type='location',
                record_id='1', reason='reason',
            )
    with pytest.raises(ValueError, match='reason'):
        with access.transaction() as work:
            work.audit.add(
                actor='operator', action='edit', record_type='location',
                record_id='1', reason='',
            )


def test_explicit_forecast_generation_records_history(access, monkeypatch):
    monkeypatch.setattr(application, 'DATA_ACCESS', access)
    forecast_inputs = StoredForecastInputService(
        access, application.RESEARCH_SCORING_ENGINE,
        application.WEATHER_QUALITY_VALIDATOR,
        location_name=application.settings.location_name,
        latitude=application.settings.latitude,
        longitude=application.settings.longitude,
        timezone_name=application.settings.timezone_name,
        source='open-meteo:era5',
    )
    monkeypatch.setattr(application, 'FORECAST_INPUT_SERVICE', forecast_inputs)
    first = generate_forecast_run(
        2026, 'aadi', actor='operator:alice', reason='Release verification'
    )
    second = generate_forecast_run(
        2026, 'aadi', actor='operator:bob', reason='Second explicit run'
    )
    with access.transaction() as work:
        events = work.audit.list_recent()
        assert [event.record_id for event in events] == [str(second.id), str(first.id)]
        assert [event.action for event in events] == [
            'forecast_generated', 'forecast_generated'
        ]
        assert len(work.forecasts.list_entries(first.id)) == 180
    with sqlite3.connect(access.database_path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM karuvottam_windows').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM lunar_events').fetchone()[0] == 1
