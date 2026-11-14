from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copyfile

import pytest

from karuvottam.data_access import DataAccess, DuplicateRecordError
from karuvottam.database import connect_database, migrate_database
from karuvottam.event_model import EventAdvisory, EventTrackPoint


ISSUED = datetime(2026, 11, 1, 6, tzinfo=timezone.utc)


@pytest.fixture
def access(tmp_path):
    path = tmp_path / 'events.sqlite3'
    migrate_database(path)
    return DataAccess(path)


def _advisory(**changes):
    original = EventAdvisory(
        source='official-archive', event_key='bay-event-2026-07',
        event_type='lpa', provider_classification='Low Pressure Area',
        issued_at=ISSUED, retrieved_at=ISSUED + timedelta(minutes=5),
        quality_flag='source_verified', source_reference='bulletin-001',
        source_url='https://example.org/bulletin-001',
        center_latitude=12.5, center_longitude=84.25,
    )
    return replace(original, **changes)


def test_advisory_history_keeps_provider_labels_and_intensity_changes(access):
    first = _advisory()
    second = _advisory(
        issued_at=ISSUED + timedelta(hours=6),
        retrieved_at=ISSUED + timedelta(hours=6, minutes=4),
        event_type='depression', provider_classification='Depression',
        intensity='D', source_reference='bulletin-002',
        source_url='https://example.org/bulletin-002',
    )
    third = replace(
        second, issued_at=ISSUED + timedelta(hours=12),
        retrieved_at=ISSUED + timedelta(hours=12, minutes=4),
        event_type='lpa', provider_classification='Low Pressure Area',
        intensity='weakened', source_reference='bulletin-003',
        source_url='https://example.org/bulletin-003',
    )
    with access.transaction() as work:
        a, created = work.weather_events.record_advisory(first)
        b, _ = work.weather_events.record_advisory(second)
        c, _ = work.weather_events.record_advisory(third)
        retry, retry_created = work.weather_events.record_advisory(
            replace(
                first, retrieved_at=ISSUED + timedelta(days=1),
                source_url='https://example.org/other-official-csv',
            )
        )
    assert created and not retry_created and retry == a
    with access.transaction() as work:
        history = work.weather_events.history('official-archive', 'bay-event-2026-07')
    assert [item.id for item in history] == [a.id, b.id, c.id]
    assert [item.event_type for item in history] == ['lpa', 'depression', 'lpa']
    assert [item.provider_classification for item in history] == [
        'Low Pressure Area', 'Depression', 'Low Pressure Area'
    ]
    assert history[0].classification_basis == 'provider_category'
    assert history[0].retrieved_at == '2026-11-01T06:05:00Z'


def test_same_issue_conflict_is_rejected_without_overwriting(access):
    with access.transaction() as work:
        stored, _ = work.weather_events.record_advisory(_advisory())
    with pytest.raises(DuplicateRecordError, match='conflicts'):
        with access.transaction() as work:
            work.weather_events.record_advisory(_advisory(event_type='cyclone'))
    with access.transaction() as work:
        assert work.weather_events.get(stored.id).event_type == 'lpa'
        assert len(work.weather_events.history(stored.source, stored.event_key)) == 1


def test_observed_official_and_model_points_remain_distinct(access):
    with access.transaction() as work:
        advisory, _ = work.weather_events.record_advisory(_advisory())
        observed = EventTrackPoint(
            valid_at=ISSUED, latitude=12.5, longitude=84.25,
            point_type='observed', source='official-archive',
            quality_flag='source_verified',
        )
        official = replace(
            observed, valid_at=ISSUED + timedelta(hours=12),
            latitude=13, longitude=83, point_type='official_forecast',
            issued_at=ISSUED,
        )
        model = replace(
            official, latitude=14, point_type='model_guidance',
            source='model-a',
        )
        for point in (observed, official, model):
            _, created = work.weather_events.record_point(advisory.id, point)
            assert created
        _, created = work.weather_events.record_point(advisory.id, official)
        assert not created
    with access.transaction() as work:
        points = work.weather_events.points(advisory.id)
    assert {point.point_type for point in points} == {
        'observed', 'official_forecast', 'model_guidance'
    }
    assert len(points) == 3
    with pytest.raises(DuplicateRecordError, match='conflicts'):
        with access.transaction() as work:
            work.weather_events.record_point(
                advisory.id, replace(official, latitude=15)
            )


@pytest.mark.parametrize('change', [
    {'event_type': 'unknown'},
    {'source_reference': None, 'source_url': None},
    {'center_latitude': 12.0, 'center_longitude': None},
    {'classification_basis': 'analyst_interpretation'},
    {'retrieved_at': ISSUED - timedelta(minutes=1)},
])
def test_invalid_advisory_is_rejected(change):
    with pytest.raises(ValueError):
        _advisory(**change).validate()


def test_analyst_classification_is_explicit_and_versioned():
    advisory = _advisory(
        event_type='uacc', classification_basis='analyst_interpretation',
        classification_rule_version='analyst-rules-1',
    )
    advisory.validate()
    assert advisory.provider_classification == 'Low Pressure Area'


def test_forecast_point_requires_issue_time_and_aware_timestamps():
    with pytest.raises(ValueError, match='issued_at'):
        EventTrackPoint(
            valid_at=ISSUED, latitude=12, longitude=82,
            point_type='official_forecast', source='official',
            quality_flag='valid',
        ).validate()
    with pytest.raises(ValueError, match='timezone-aware'):
        replace(_advisory(), issued_at=datetime(2026, 11, 1)).validate()


def test_event_migration_preserves_legacy_bulletins(tmp_path):
    source = Path(__file__).parents[1] / 'karuvottam' / 'migrations'
    legacy = tmp_path / 'legacy_migrations'
    legacy.mkdir()
    for version in ('001', '002', '003'):
        path = next(source.glob(f'{version}_*.sql'))
        copyfile(path, legacy / path.name)
    database = tmp_path / 'legacy.sqlite3'
    migrate_database(database, legacy)
    with connect_database(database) as connection:
        connection.execute(
            '''INSERT INTO weather_events (
                event_key, event_type, provider_classification, source,
                issued_at, retrieved_at, quality_flag
            ) VALUES (?, ?, ?, ?, ?, ?, ?)''',
            ('old-key', 'lpa', 'LPA', 'legacy-source',
             '2025-01-01T00:00:00Z', '2025-01-01T01:00:00Z', 'unknown'),
        )
    result = migrate_database(database)
    assert result.applied_versions == (4, 5, 6, 7, 8, 9)
    with DataAccess(database).transaction() as work:
        history = work.weather_events.history('legacy-source', 'old-key')
    assert len(history) == 1
    assert history[0].provider_classification == 'LPA'
    assert history[0].classification_basis == 'legacy_unspecified'
