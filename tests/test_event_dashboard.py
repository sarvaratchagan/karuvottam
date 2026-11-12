import hashlib
import json

import app as app_module
from karuvottam.climate_context import ClimateContextService
from karuvottam.data_access import DataAccess
from karuvottam.database import migrate_database
from karuvottam.event_dashboard import EventDashboardEvidenceService
from karuvottam.combined_validation import build as build_combined, export as export_combined
from karuvottam.event_impact import EventImpactService
from karuvottam.event_tracks import EventTrackService


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _json(path, value):
    return _write(path, (json.dumps(value) + '\n').encode())


def _service(tmp_path):
    findings_dir = tmp_path / 'findings'
    validation_dir = tmp_path / 'validation'
    dataset_dir = tmp_path / 'dataset'
    rainfall_dir = tmp_path / 'rainfall'
    calibration_dir = tmp_path / 'calibration'
    combined_dir = tmp_path / 'combined'
    dataset_sha = _write(dataset_dir / 'evaluation_dataset.csv', b'dataset\n')
    _json(dataset_dir / 'manifest.json', {
        'dataset_key': 'dataset-1', 'weather_source': 'open-meteo:era5',
        'location': {'latitude': 10, 'longitude': 78},
        'files': {'evaluation_dataset.csv': {'sha256': dataset_sha}},
    })
    metrics_sha = _write(validation_dir / 'rolling_metrics.csv', b'metrics\n')
    _json(validation_dir / 'validation_manifest.json', {
        'validation_key': 'rolling-1',
        'source_dataset': {'dataset_key': 'dataset-1', 'dataset_sha256': dataset_sha},
        'files': {'rolling_metrics.csv': {'sha256': metrics_sha}},
        'counts': {'evaluated_predictions': 6},
        'spec': {'first_evaluation_year': 2020, 'last_evaluation_year': 2024},
    })
    findings = {
        'findings_version': 'research-findings-1.0', 'findings_key': 'findings-1',
        'rolling_pooled_metrics': {
            key: {'mae_mm': mae, 'rmse_mm': mae + 1, 'brier_score': .2}
            for key, mae in (('seasonal_climatology', 2),
                             ('karuvottam_only', 3), ('combined', 2.5))
        },
        'paired_comparisons': [
            {'candidate_approach': key, 'paired_rows': 2,
             'incremental_value_supported': False,
             'brier_delta': .03, 'brier_ci_upper': .05,
             'mae_delta_mm': .4, 'mae_ci_upper_mm': .7}
            for key in ('karuvottam_only', 'combined')
        ],
        'conclusion': {'incremental_value_supported': False,
                       'probability_publication_enabled': False},
    }
    findings_sha = _json(findings_dir / 'research_findings.json', findings)
    _json(findings_dir / 'findings_manifest.json', {
        'findings_key': 'findings-1',
        'inputs': {'rolling_validation_key': 'rolling-1',
                   'rolling_metrics_sha256': metrics_sha},
        'files': {'research_findings.json': {'sha256': findings_sha}},
        'conclusion': findings['conclusion'],
    })
    rainfall_sha = _write(rainfall_dir / 'event_rainfall.csv', b'event-rain\n')
    _json(rainfall_dir / 'summary.json', {
        'version': 'event-rainfall-1.0',
        'location': {'latitude': 10, 'longitude': 78},
        'csv_sha256': rainfall_sha, 'event_count': 8,
        'complete_event_count': 7, 'years': [2015, 2024],
        'weather_sources': ['open-meteo:era5'],
        'holdout': {'status': 'evaluated', 'split_year': 2022,
                    'test_events': 3, 'baseline_mae_mm_per_24h': 3.1,
                    'band_model_mae_mm_per_24h': 3.2},
    })
    calibration = {
        'version': 'real-score-calibration-1.0', 'dataset_key': 'dataset-1',
        'location': {'latitude': 10, 'longitude': 78},
        'calibration_gate_passed': False,
    }
    calibration_sha = _json(calibration_dir / 'calibration_report.json', calibration)
    _json(calibration_dir / 'calibration_manifest.json', {
        'calibration_report_sha256': calibration_sha,
    })
    decision = build_combined(
        findings_dir=findings_dir, validation_dir=validation_dir,
        dataset_dir=dataset_dir, event_rainfall_dir=rainfall_dir,
        calibration_dir=calibration_dir, latitude=10, longitude=78,
    )
    export_combined(decision, combined_dir)
    return EventDashboardEvidenceService(
        findings_dir, validation_dir, dataset_dir, rainfall_dir,
        latitude=10, longitude=78,
        combined_validation_dir=combined_dir,
        calibration_dir=calibration_dir,
    )


def test_dashboard_accepts_matched_verified_research_artifacts(tmp_path):
    service = _service(tmp_path)
    comparison = service.comparison()
    rainfall = service.event_rainfall()
    assert comparison.available
    assert comparison.matched_days == 2
    assert comparison.first_year == 2020
    assert [row.approach for row in comparison.rows] == [
        'seasonal_climatology', 'karuvottam_only', 'combined',
    ]
    assert rainfall.available
    assert rainfall.complete_count == 7
    decision = service.combined_decision(comparison)
    assert decision.available
    assert decision.status == 'withheld'
    assert not decision.public_probability_enabled
    assert 'combined_no_incremental_value' in decision.reasons


def test_dashboard_withholds_tampered_or_wrong_location_artifacts(tmp_path):
    service = _service(tmp_path)
    (service.validation_dir / 'rolling_metrics.csv').write_text('tampered')
    assert not service.comparison().available
    (service.event_rainfall_dir / 'event_rainfall.csv').write_text('tampered')
    assert not service.event_rainfall().available
    wrong_location = EventDashboardEvidenceService(
        service.findings_dir, service.validation_dir, service.dataset_dir,
        service.event_rainfall_dir, latitude=11, longitude=78,
    )
    assert not wrong_location.comparison().available
    (service.combined_validation_dir / 'combined_validation.json').write_text('tampered')
    assert not service.combined_decision().available


def test_dashboard_rejects_mismatched_combined_manifest(tmp_path):
    service = _service(tmp_path)
    path = service.combined_validation_dir / 'combined_validation_manifest.json'
    manifest = json.loads(path.read_text())
    manifest['dataset_key'] = 'other-dataset'
    path.write_text(json.dumps(manifest))
    assert not service.combined_decision().available


def test_events_page_shows_dashboard_sections_without_event_rows(tmp_path, monkeypatch):
    database = tmp_path / 'empty.sqlite3'
    migrate_database(database)
    access = DataAccess(database)
    monkeypatch.setitem(app_module.app.extensions, 'event_track_service',
                        EventTrackService(access, target_latitude=10,
                                          target_longitude=78))
    monkeypatch.setitem(app_module.app.extensions, 'event_impact_service',
                        EventImpactService(access, location_name='target',
                                           target_latitude=10, target_longitude=78,
                                           timezone_name='Asia/Kolkata'))
    monkeypatch.setitem(app_module.app.extensions, 'climate_context_service',
                        ClimateContextService(access))
    monkeypatch.setitem(app_module.app.extensions,
                        'event_dashboard_evidence_service', _service(tmp_path))
    app_module.app.config.update(TESTING=True)
    with app_module.app.test_client() as client:
        response = client.get('/events?year=2026')
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'நிகழ்வுத் தரவு இல்லை' in html
    assert 'IOD / ENSO பருவநிலைப் பின்னணி' in html
    assert 'வரலாற்று நிகழ்வு–மழை ஆய்வு' in html
    assert 'கருவோட்டம் + வானிலை' in html
    assert 'T8.8 சரிபார்ப்பு' in html
    assert '1600' not in html
