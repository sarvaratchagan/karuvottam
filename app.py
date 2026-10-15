from datetime import datetime, timedelta

from flask import Flask, render_template, request

from config import settings
from karuvottam.calendar_engine import CalendarRule
from karuvottam.data_access import DataAccess
from karuvottam.lunar_events import LunarEventEngine
from karuvottam.weather_client import (
    OpenMeteoHistoricalClient,
    RawWeatherPayloadStore,
    WeatherIngestionService,
)
from karuvottam.weather_csv import WeatherCsvService
from karuvottam.weather_provider import selected_historical_provider
from karuvottam.weather_quality import WeatherQualityValidator
from karuvottam.windows import KaruvottamWindowEngine

WEATHER_PROVIDER_SPEC = selected_historical_provider(
    settings.weather_provider,
    settings.weather_model,
    settings.weather_api_base_url,
)

app = Flask(__name__)
app.config.from_mapping(
    LOCATION_NAME=settings.location_name,
    LATITUDE=settings.latitude,
    LONGITUDE=settings.longitude,
    ELEVATION_M=settings.elevation_m,
    TIMEZONE=settings.timezone_name,
    CHITHIRAI_REFERENCE=settings.chithirai_reference,
    CALENDAR_RULE_VERSION=settings.calendar_rule_version,
    MARGAZHI_ALTERNATION_ANCHOR_YEAR=settings.margazhi_alternation_anchor_year,
    MARGAZHI_ALTERNATION_ANCHOR_PHASE=settings.margazhi_alternation_anchor_phase,
    WEATHER_PROVIDER=settings.weather_provider,
    WEATHER_MODEL=settings.weather_model,
    WEATHER_API_BASE_URL=settings.weather_api_base_url,
    DATABASE_PATH=str(settings.database_path),
)
DATA_ACCESS = DataAccess(settings.database_path)
WEATHER_QUALITY_VALIDATOR = WeatherQualityValidator()
WEATHER_CSV_SERVICE = WeatherCsvService(DATA_ACCESS, WEATHER_QUALITY_VALIDATOR)
WEATHER_CLIENT = OpenMeteoHistoricalClient(
    WEATHER_PROVIDER_SPEC,
    api_key=settings.weather_api_key,
    timeout_seconds=settings.weather_timeout_seconds,
    max_attempts=settings.weather_retry_attempts,
    retry_backoff_seconds=settings.weather_retry_backoff_seconds,
)
WEATHER_INGESTION_SERVICE = WeatherIngestionService(
    WEATHER_CLIENT,
    DATA_ACCESS,
    RawWeatherPayloadStore(settings.weather_raw_data_dir),
    WEATHER_QUALITY_VALIDATOR,
)
app.extensions['data_access'] = DATA_ACCESS
app.extensions['weather_provider_spec'] = WEATHER_PROVIDER_SPEC
app.extensions['weather_client'] = WEATHER_CLIENT
app.extensions['weather_quality_validator'] = WEATHER_QUALITY_VALIDATOR
app.extensions['weather_csv_service'] = WEATHER_CSV_SERVICE
app.extensions['weather_ingestion_service'] = WEATHER_INGESTION_SERVICE

LOCATION_TIMEZONE = settings.timezone
REFERENCE_MONTH, REFERENCE_DAY = settings.chithirai_reference_parts
CALENDAR_RULE = CalendarRule(
    reference_month=REFERENCE_MONTH,
    reference_day=REFERENCE_DAY,
    version=settings.calendar_rule_version,
)
LUNAR_EVENT_ENGINE = LunarEventEngine(LOCATION_TIMEZONE)
WINDOW_ENGINE = KaruvottamWindowEngine(
    calendar_rule=CALENDAR_RULE,
    lunar_engine=LUNAR_EVENT_ENGINE,
    margazhi_anchor_year=settings.margazhi_alternation_anchor_year,
    margazhi_anchor_phase=settings.margazhi_alternation_anchor_phase,
)

def karuvottam_window(year: int, kind: str):
    window = WINDOW_ENGINE.generate(kind, year)
    return window.start_datetime_local, window.end_datetime_local


def requested_year(default: int = 2026) -> int:
    raw_year = request.args.get('year', str(default))
    try:
        return int(raw_year)
    except ValueError:
        app.logger.warning('Invalid year parameter %r; using %s', raw_year, default)
        return default


def forecast_period_after_window(window_end: datetime, total_days: int):
    """Return the inclusive local-date forecast period after an observation window."""
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError('window_end must be timezone-aware')
    if total_days < 1:
        raise ValueError('total_days must be at least 1')

    local_end_date = window_end.astimezone(LOCATION_TIMEZONE).date()
    start = local_end_date + timedelta(days=1)
    end = start + timedelta(days=total_days - 1)
    return start, end


def build_cycle(year: int):
    aadi_window = WINDOW_ENGINE.generate('aadi', year)
    margazhi_window = WINDOW_ENGINE.generate('margazhi', year)
    next_aadi_window = WINDOW_ENGINE.generate('aadi', year + 1)
    a_start = aadi_window.start_datetime_local
    a_end = aadi_window.end_datetime_local
    m_start = margazhi_window.start_datetime_local
    m_end = margazhi_window.end_datetime_local
    aadi_prediction_start, aadi_prediction_end = forecast_period_after_window(m_end, 180)
    margazhi_prediction_start, margazhi_prediction_end = forecast_period_after_window(
        next_aadi_window.end_datetime_local,
        140,
    )
    return {
        'year': year,
        'aadi_start': a_start,
        'aadi_end': a_end,
        'aadi_prediction_start': aadi_prediction_start,
        'aadi_prediction_end': aadi_prediction_end,
        'margazhi_start': m_start,
        'margazhi_end': m_end,
        'margazhi_prediction_start': margazhi_prediction_start,
        'margazhi_prediction_end': margazhi_prediction_end,
        'aadi_window': aadi_window,
        'margazhi_window': margazhi_window,
        'next_aadi_window': next_aadi_window,
    }

def fmt(d):
    if hasattr(d, 'strftime'):
        return d.strftime('%d-%m-%Y')
    return str(d)


def fmt_datetime(value):
    return value.strftime('%d-%m-%Y %H:%M')

@app.route('/')
def index():
    year = requested_year()
    cycle = build_cycle(year)
    lunar_events = [
        {
            'month_name': window.season_name_tamil,
            'event': window.trigger_event,
        }
        for window in (cycle['aadi_window'], cycle['margazhi_window'])
    ]
    cycle['aadi_start_f'] = fmt_datetime(cycle['aadi_start']); cycle['aadi_end_f'] = fmt_datetime(cycle['aadi_end'])
    cycle['aadi_prediction_start_f'] = fmt(cycle['aadi_prediction_start']); cycle['aadi_prediction_end_f'] = fmt(cycle['aadi_prediction_end'])
    cycle['margazhi_start_f'] = fmt_datetime(cycle['margazhi_start']); cycle['margazhi_end_f'] = fmt_datetime(cycle['margazhi_end'])
    cycle['margazhi_prediction_start_f'] = fmt(cycle['margazhi_prediction_start']); cycle['margazhi_prediction_end_f'] = fmt(cycle['margazhi_prediction_end'])
    return render_template(
        'index.html',
        cycle=cycle,
        selected_year=year,
        calendar_rule=CALENDAR_RULE,
        lunar_events=lunar_events,
        lunar_error=None,
    )

@app.route('/prediction')
def prediction():
    year = requested_year()
    cycle = build_cycle(year)
    mode = request.args.get('mode', 'aadi')
    start = cycle['aadi_prediction_start'] if mode == 'aadi' else cycle['margazhi_prediction_start']
    days = 180 if mode == 'aadi' else 140
    rows = []
    # MVP placeholder forecast: transparent demo values, not scientific predictions.
    for i in range(days):
        d = start + timedelta(days=i)
        probability = round(35 + 25 * ((i % 14) / 13), 1)
        intensity = 'மழையின்மை' if probability < 45 else ('தூறல்' if probability < 60 else 'மிதமான மழை')
        tamil_date = CALENDAR_RULE.from_gregorian(d)
        rows.append({
            'day': i + 1,
            'date': fmt(d),
            'tamil_date': tamil_date.format_tamil(),
            'probability': probability,
            'intensity': intensity,
        })
    return render_template(
        'prediction.html',
        rows=rows,
        mode=mode,
        year=year,
        days=days,
        start=fmt(start),
        calendar_rule=CALENDAR_RULE,
    )

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=settings.port, debug=False)
