from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import app, build_cycle, forecast_period_after_window, karuvottam_window
from karuvottam.data_access import DataAccess
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
    assert isinstance(app.extensions['weather_csv_service'], WeatherCsvService)
    assert isinstance(
        app.extensions['weather_ingestion_service'], WeatherIngestionService
    )


@pytest.mark.parametrize(
    ('path', 'expected_text'),
    [
        ('/', 'தன்னியக்க துல்லிய மழை முன்னறிவிப்பு திட்டம்'),
        ('/prediction?year=2026&mode=aadi', '180 நாள் முன்னறிவிப்பு'),
        ('/prediction?year=2026&mode=margazhi', '140 நாள் முன்னறிவிப்பு'),
    ],
)
def test_main_pages_return_200(client, path, expected_text):
    response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.get_data(as_text=True)


def test_invalid_year_falls_back_and_is_logged(client, caplog):
    with caplog.at_level('WARNING', logger=app.logger.name):
        response = client.get('/?year=not-a-year')

    assert response.status_code == 200
    assert 'value="2026"' in response.get_data(as_text=True)
    assert 'Invalid year parameter' in caplog.text


def test_ui_identifies_custom_calendar_rule(client):
    home = client.get('/').get_data(as_text=True)
    prediction = client.get(
        '/prediction?year=2026&mode=aadi'
    ).get_data(as_text=True)

    assert '03-21 = சித்திரை 1' in home
    assert 'அதிகாரப்பூர்வ தமிழ் நாட்காட்டி அல்ல' in home
    assert 'தனிப்பயன் தமிழ் தேதி' in prediction
    assert 'மார்கழி 19 / 2026' in prediction


def test_home_displays_lunar_event_provenance(client):
    home = client.get('/?year=2026').get_data(as_text=True)

    assert 'கருவோட்டத் தூண்டுதல் கணக்கீடுகள்' in home
    assert 'ஆடி:' in home
    assert 'மார்கழி:' in home
    assert 'Astronomy Engine 2.1.19' in home
    assert 'சுக்கில பட்ச சதுர்த்தசி தொடக்கம்' in home
    assert '28-06-2026 00:44' in home
    assert 'நான்கு நாள் நிலைபெறுதலுக்குப் பின் உள்ளூர் சூரிய உதயம்' in home
    assert '02-07-2026 06:01' in home


def test_aadi_window_is_exactly_18_days():
    start, end = karuvottam_window(2026, 'aadi')

    assert start == datetime(2026, 7, 2, 6, 1, 44, 785915, tzinfo=IST)
    assert end - start == timedelta(days=18)


def test_margazhi_window_is_exactly_248_hours():
    start, end = karuvottam_window(2026, 'margazhi')

    assert start == datetime(2026, 11, 28, 6, 18, 10, 900269, tzinfo=IST)
    assert end - start == timedelta(hours=248)


def test_aadi_forecast_mapping_uses_margazhi_window():
    cycle = build_cycle(2026)

    assert cycle['margazhi_end'] == datetime(
        2026, 12, 8, 14, 18, 10, 900269, tzinfo=IST
    )
    assert cycle['aadi_prediction_start'] == date(2026, 12, 9)
    assert cycle['aadi_prediction_end'] == date(2027, 6, 6)
    assert (cycle['aadi_prediction_end'] - cycle['aadi_prediction_start']).days + 1 == 180


def test_margazhi_forecast_mapping_uses_next_aadi_window():
    cycle = build_cycle(2026)

    assert cycle['margazhi_prediction_start'] == date(2027, 7, 25)
    assert cycle['margazhi_prediction_end'] == date(2027, 12, 11)
    assert (cycle['margazhi_prediction_end'] - cycle['margazhi_prediction_start']).days + 1 == 140


def test_home_displays_precise_calculated_window_boundaries(client):
    home = client.get('/?year=2026').get_data(as_text=True)

    assert '02-07-2026 06:01 → 20-07-2026 06:01' in home
    assert '28-11-2026 06:18 → 08-12-2026 14:18' in home
    assert '432 மணி' in home
    assert '248 மணி' in home


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
