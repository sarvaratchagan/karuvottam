from datetime import date, datetime, timezone

import pytest

import app as application
from karuvottam.climate_context import ClimateContextService
from karuvottam.climate_indices import import_climate_index, parse_dmi, parse_oni
from karuvottam.data_access import DataAccess, DuplicateRecordError
from karuvottam.database import migrate_database


ISSUED = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 11, 7, 15, tzinfo=timezone.utc)
DMI = b'Date, DMI HadISST1.1  missing value -9999 https://psl.noaa.gov/data/timeseries/month/\n2026-06-01, 0.265\n2026-07-01, 0.539\n2026-08-01,-9999.000\n'
ONI = b'<html><h1>ERSSTv6 ONI</h1><table><tr><td>Year</td><td>DJF</td></tr><tr><td><strong>2026</strong></td><td>-0.4</td><td>0.5</td><td>0.7</td></tr></table></html>'


@pytest.fixture
def access(tmp_path):
    path = tmp_path / 'climate.sqlite3'
    migrate_database(path)
    return DataAccess(path)


def _import(access, payload, source, issued=ISSUED):
    return import_climate_index(
        payload, access, source=source, issued_at=issued,
        retrieved_at=RETRIEVED,
        issue_time_basis='http_last_modified' if source == 'dmi' else 'retrieval_proxy',
    )


def test_dmi_parser_skips_missing_sentinel_and_preserves_month_period():
    samples = parse_dmi(DMI)
    assert len(samples) == 2
    assert samples[-1].period_start == date(2026, 7, 1)
    assert samples[-1].period_end == date(2026, 7, 31)
    assert samples[-1].classification == 'positive_dmi'


def test_oni_parser_handles_cross_year_three_month_season_and_estimate():
    samples = parse_oni(ONI)
    assert len(samples) == 3
    assert (samples[0].period_start, samples[0].period_end) == (
        date(2025, 12, 1), date(2026, 2, 28)
    )
    assert (samples[1].period_start, samples[1].period_end) == (
        date(2026, 1, 1), date(2026, 3, 31)
    )
    assert samples[1].classification == 'warm_oni_band'
    assert samples[-1].quality_flag == 'recent_estimate'


def test_import_is_idempotent_and_revisions_keep_source_provenance(access):
    first = _import(access, DMI, 'dmi')
    repeat = _import(access, DMI, 'dmi', issued=ISSUED.replace(day=7))
    assert (first.inserted, repeat.inserted, repeat.existing) == (2, 0, 2)
    revised = DMI.replace(b'0.539', b'0.600')
    revision = _import(access, revised, 'dmi', issued=ISSUED.replace(day=7))
    assert revision.inserted == 2
    with access.transaction() as work:
        latest = work.climate_indices.latest('iod_dmi')
        recent = work.climate_indices.recent('iod_dmi')
    assert latest.index_value == 0.600
    assert latest.period_end == '2026-07-31'
    assert latest.provider == 'NOAA PSL'
    assert latest.data_version == 'hadisst1.1-dmi-monthly'
    assert latest.issue_time_basis == 'http_last_modified'
    assert latest.source_sha256 == revision.sha256
    assert len(recent) == 4


def test_oni_context_page_labels_seasonal_not_daily(access, monkeypatch):
    _import(access, ONI, 'oni')
    service = ClimateContextService(access)
    items = service.build(today=date(2026, 11, 7))
    oni = next(item for item in items if item.index_type == 'enso_oni')
    assert oni.latest.period_end == '2026-04-30'
    assert oni.stale
    monkeypatch.setitem(application.app.extensions, 'climate_context_service', service)
    application.app.config.update(TESTING=True)
    with application.app.test_client() as client:
        response = client.get('/climate')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'பருவநிலைப் பின்னணி' in html
    assert 'தினசரி மழை கணிப்பு அல்லது உறுதி அல்ல' in html
    assert 'RONI' in html
    assert 'retrieval_proxy' in html


def test_malformed_sources_fail_without_writing(access):
    with pytest.raises(ValueError):
        _import(access, b'wrong,header\n2026-01-01,1\n', 'dmi')
    with pytest.raises(ValueError):
        _import(access, b'<html>No index</html>', 'oni')
    with access.transaction() as work:
        assert work.climate_indices.latest('iod_dmi') is None
        assert work.climate_indices.latest('enso_oni') is None
