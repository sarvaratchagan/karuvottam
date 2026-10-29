from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import (
    app,
    build_cycle,
    build_prediction_context,
    build_prediction_timeline,
    forecast_period_after_window,
    karuvottam_window,
)
from karuvottam.calendar_view import CalendarViewService
from karuvottam.data_access import DataAccess
from karuvottam.forecast_calendar import ForecastCalendarService
from karuvottam.forecast_inputs import StoredForecastInputService
from karuvottam.forecast_timeline import (
    ForecastTimelineEngine,
    unavailable_research_score,
)
from karuvottam.observation_inspection import ObservationInspectionService
from karuvottam.probability_calibration import ProbabilityCalibrationEngine
from karuvottam.rain_categories import RainCategoryEngine
from karuvottam.research_scoring import ResearchScore, ResearchScoringEngine
from karuvottam.status_dashboard import StatusDashboardService
from karuvottam.weather_client import (
    OpenMeteoHistoricalClient,
    WeatherIngestionService,
)
from karuvottam.weather_csv import WeatherCsvService
from karuvottam.weather_provider import OPEN_METEO_ERA5
from karuvottam.weather_quality import WeatherQualityValidator


IST = ZoneInfo('Asia/Kolkata')


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def test_app_imports():
    assert app.name == 'app'
    assert isinstance(app.extensions['data_access'], DataAccess)
    assert app.extensions['weather_provider_spec'] is OPEN_METEO_ERA5
    assert isinstance(app.extensions['weather_client'], OpenMeteoHistoricalClient)
    assert isinstance(
        app.extensions['weather_quality_validator'], WeatherQualityValidator
    )
    assert isinstance(app.extensions['research_scoring_engine'], ResearchScoringEngine)
    assert isinstance(app.extensions['rain_category_engine'], RainCategoryEngine)
    assert isinstance(
        app.extensions['forecast_timeline_engine'], ForecastTimelineEngine
    )
    assert isinstance(
        app.extensions['probability_calibration_engine'],
        ProbabilityCalibrationEngine,
    )
    assert isinstance(app.extensions['weather_csv_service'], WeatherCsvService)
    assert isinstance(
        app.extensions['weather_ingestion_service'], WeatherIngestionService
    )
    assert isinstance(
        app.extensions['forecast_input_service'], StoredForecastInputService
    )
    assert isinstance(
        app.extensions['status_dashboard_service'], StatusDashboardService
    )
    assert isinstance(app.extensions['calendar_view_service'], CalendarViewService)
    assert isinstance(
        app.extensions['forecast_calendar_service'], ForecastCalendarService
    )
    assert isinstance(
        app.extensions['observation_inspection_service'],
        ObservationInspectionService,
    )


def test_home_contains_tamil_status_dashboard(client):
    home = client.get('/?year=2026').get_data(as_text=True)

    assert 'நிலை முகப்புப் பலகை' in home
    assert 'செயலில் உள்ள இடம்' in home
    assert 'கருவோட்டக் காலம்' in home
    assert 'சமீபத்திய வானிலைத் தரவு' in home
    assert 'கடைசி முன்னறிவிப்பு' in home
    assert 'முக்கிய எச்சரிக்கைகள்' in home


def test_calendar_view_displays_traceable_rules_and_lunar_events(client):
    page = client.get('/calendar?year=2026').get_data(as_text=True)

    assert 'ஆடி கருவோட்டம்' in page
    assert 'மார்கழி கருவோட்டம்' in page
    assert 'பௌர்ணமி' in page
    assert 'அமாவாசை' in page
    assert '30-06-2026 05:27:17' in page
    assert '09-12-2026 06:22:31' in page
    assert 'Astronomy Engine 2.1.19' in page
    assert '2026 = அமாவாசை' in page
    assert '[தொடக்கம், முடிவு)' in page
    assert 'கணக்கிடப்பட்டது; இன்னும் சேமிக்கப்படவில்லை' in page


@pytest.mark.parametrize(
    ('path', 'expected_text'),
    [
        ('/', 'தன்னியக்க துல்லிய மழை முன்னறிவிப்பு திட்டம்'),
        ('/calendar?year=2026', 'கருவோட்டக் காலண்டர்'),
        ('/observations', 'வானிலைத் தரவு ஆய்வு'),
        ('/prediction?year=2026&mode=aadi', '180 நாள் முன்னறிவிப்பு'),
        ('/prediction?year=2026&mode=margazhi', '140 நாள் முன்னறிவிப்பு'),
    ],
)
def test_main_pages_return_200(client, path, expected_text):
    response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.get_data(as_text=True)


def test_invalid_year_falls_back_and_is_logged(client, caplog):
    app.logger.addHandler(caplog.handler)
    try:
        with caplog.at_level('WARNING', logger=app.logger.name):
            response = client.get('/?year=not-a-year')
    finally:
        app.logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    assert 'value="2026"' in response.get_data(as_text=True)
    assert 'ஆண்டு செல்லாது; இயல்புநிலை 2026' in response.get_data(as_text=True)
    assert 'Invalid year parameter' in caplog.text


def test_historical_dataset_start_year_is_selectable(client):
    response = client.get('/?year=2015')

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'value="2015"' in html
    assert 'min="2015"' in html
    assert 'ஆண்டு 2015–2100 வரம்பில் இருக்க வேண்டும்' not in html


def test_ui_identifies_custom_calendar_rule(client):
    home = client.get('/').get_data(as_text=True)
    prediction = client.get(
        '/prediction?year=2026&mode=aadi'
    ).get_data(as_text=True)

    assert '03-21 = சித்திரை 1' in home
    assert 'அதிகாரப்பூர்வ தமிழ் நாட்காட்டி அல்ல' in home
    assert 'தனிப்பயன் தமிழ் தேதி' in prediction
    assert 'தை 1 / 2026' in prediction


def test_home_displays_lunar_event_provenance(client):
    home = client.get('/?year=2026').get_data(as_text=True)

    assert 'கருவோட்டத் தூண்டுதல் கணக்கீடுகள்' in home
    assert 'ஆடி:' in home
    assert 'மார்கழி:' in home
    assert 'Astronomy Engine 2.1.19' in home
    assert 'பௌர்ணமி —' in home
    assert '30-06-2026 05:27' in home
    assert 'அமாவாசை —' in home
    assert '09-12-2026 06:22' in home
    assert 'நான்கு நாள் நிலைபெறுதல்' not in home


def test_aadi_window_is_exactly_18_days():
    start, end = karuvottam_window(2026, 'aadi')

    assert start == datetime(2026, 6, 30, 5, 27, 17, 744216, tzinfo=IST)
    assert end - start == timedelta(days=18)


def test_margazhi_window_is_exactly_11_days():
    start, end = karuvottam_window(2026, 'margazhi')

    assert start == datetime(2026, 12, 9, 6, 22, 31, 284217, tzinfo=IST)
    assert end - start == timedelta(days=11)


def test_aadi_forecast_mapping_uses_margazhi_window():
    cycle = build_cycle(2026)

    assert cycle['margazhi_end'] == datetime(
        2026, 12, 20, 6, 22, 31, 284217, tzinfo=IST
    )
    assert cycle['aadi_prediction_start'] == date(2026, 12, 21)
    assert cycle['aadi_prediction_end'] == date(2027, 6, 18)
    assert (cycle['aadi_prediction_end'] - cycle['aadi_prediction_start']).days + 1 == 180


def test_margazhi_forecast_mapping_uses_next_aadi_window():
    cycle = build_cycle(2026)

    assert cycle['margazhi_prediction_start'] == date(2027, 7, 23)
    assert cycle['margazhi_prediction_end'] == date(2027, 12, 9)
    assert (cycle['margazhi_prediction_end'] - cycle['margazhi_prediction_start']).days + 1 == 140


def test_home_displays_precise_calculated_window_boundaries(client):
    home = client.get('/?year=2026').get_data(as_text=True)

    assert '30-06-2026 05:27 → 18-07-2026 05:27' in home
    assert '09-12-2026 06:22 → 20-12-2026 06:22' in home
    assert '432 மணி' in home
    assert '264 மணி' in home


def test_forecast_start_uses_local_date_after_utc_conversion():
    window_end_utc = datetime(2026, 12, 31, 20, tzinfo=timezone.utc)

    start, end = forecast_period_after_window(window_end_utc, 2)

    assert start == date(2027, 1, 2)
    assert end == date(2027, 1, 3)


@pytest.mark.parametrize(
    ('window_end', 'days'),
    [
        (datetime(2026, 12, 31, 8), 180),
        (datetime(2026, 12, 31, 8, tzinfo=IST), 0),
    ],
)
def test_forecast_period_rejects_ambiguous_inputs(window_end, days):
    with pytest.raises(ValueError):
        forecast_period_after_window(window_end, days)


@pytest.mark.parametrize(
    ('mode', 'expected_rows'),
    [('aadi', 180), ('margazhi', 140)],
)
def test_prediction_table_has_expected_number_of_rows(client, mode, expected_rows):
    response = client.get(f'/prediction?year=2026&mode={mode}')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('<tr>') - 1 == expected_rows
    assert 'மழை நிகழ்தகவு' in html
    assert 'வெளியிடப்படவில்லை' in html
    assert 'கற்பனை மதிப்புகள் காட்டப்படாது' in html
    assert 'daily-timeline-1.0' in html


@pytest.mark.parametrize(
    ('view', 'card_count'),
    [('week', 26), ('month', 7)],
)
def test_prediction_calendar_supports_week_and_month_views(
    client, view, card_count
):
    response = client.get(f'/prediction?year=2026&mode=aadi&view={view}')
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.count('class="forecast-period-card"') == card_count
    assert 'மழை வகை' in html
    assert 'மழை நிகழ்தகவு' in html
    assert 'கணிப்பு முறை' in html
    assert 'தரவு இல்லாத நாட்கள்' in html


def test_prediction_csv_exports_traceable_no_data_rows(client, monkeypatch):
    class MissingInputService:
        @staticmethod
        def score(_window):
            return type(
                'InputResult',
                (),
                {
                    'research_score': unavailable_research_score(
                        'source_window_observations_not_found'
                    )
                },
            )()

    monkeypatch.setitem(
        build_prediction_context.__globals__,
        'FORECAST_INPUT_SERVICE',
        MissingInputService(),
    )
    response = client.get('/prediction.csv?year=2026&mode=aadi')
    csv_text = response.get_data(as_text=True)
    lines = csv_text.splitlines()

    assert response.status_code == 200
    assert response.content_type == 'text/csv; charset=utf-8'
    assert 'karuvottam-aadi-2026-forecast.csv' in response.headers[
        'Content-Disposition'
    ]
    assert len(lines) == 181
    assert lines[0].startswith('day_number,target_date,tamil_date,status')
    assert 'source_window_observations_not_found' in lines[1]
    assert 'daily-timeline-1.0' in lines[1]


def test_prediction_route_uses_available_stored_window_score(client, monkeypatch):
    score = ResearchScore(
        status='available',
        score=73.5,
        maximum_score=100,
        model_version='research-index-1.0',
        label='experimental_research_index_not_probability',
        quality_flag='valid',
        reason_codes=(),
        components=(),
    )

    class AvailableInputService:
        @staticmethod
        def score(_window):
            return type(
                'InputResult',
                (),
                {
                    'research_score': score,
                    'source': 'open-meteo:era5',
                    'received_hours': 432,
                    'expected_hours': 432,
                    'coverage_pct': 100.0,
                },
            )()

    monkeypatch.setitem(
        build_prediction_context.__globals__,
        'FORECAST_INPUT_SERVICE',
        AvailableInputService(),
    )

    html = client.get('/prediction?year=2020&mode=aadi').get_data(as_text=True)

    assert '73.5' in html
    assert 'ஆராய்ச்சி நிலை' in html
    assert 'வெளியிடப்படவில்லை' in html
    assert 'status-experimental' in html
    assert 'open-meteo:era5' in html
    assert '432 / 432' in html


def test_observation_page_shows_series_gaps_and_data_kinds(client):
    page = client.get('/observations').get_data(as_text=True)

    assert 'வெப்பநிலை' in page
    assert 'ஈரப்பதம்' in page
    assert 'மேக மூட்டம்' in page
    assert 'மழை' in page
    assert 'காற்றின் வேகம்' in page
    assert 'மூலத் தரவு' in page
    assert 'இடைமதிப்பீட்டுத் தரவு' in page
    assert 'தரவு இடைவெளிகள்' in page


def test_observation_page_handles_invalid_date_input(client):
    response = client.get('/observations?start=bad&end=2026-01-01')

    assert response.status_code == 200
    assert 'YYYY-MM-DD வடிவில் செல்லுபடியாக' in response.get_data(as_text=True)
