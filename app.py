from datetime import date, datetime, timedelta, timezone
from dataclasses import dataclass
from functools import wraps
from os import environ
from pathlib import Path

import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from flask import Flask, Response, abort, g, has_request_context, make_response, render_template, request
from werkzeug.exceptions import HTTPException

from config import PROJECT_ROOT, settings
from karuvottam.calendar_engine import CalendarRule
from karuvottam.calendar_view import CalendarViewService
from karuvottam.climate_context import ClimateContextService
from karuvottam.data_access import DataAccess, DataAccessError, LocationRecord, LocationRulesRecord
from karuvottam.error_handling import configure_application_logging
from karuvottam.event_tracks import EventTrackService
from karuvottam.event_impact import EventImpactService
from karuvottam.event_dashboard import EventDashboardEvidenceService
from karuvottam.event_monitor import DEFAULT_STATE, MonitorStore
from karuvottam.forecast_calendar import ForecastCalendarService, VIEW_MODES
from karuvottam.forecast_inputs import StoredForecastInputService
from karuvottam.forecast_timeline import (
    ForecastTimelineEngine,
)
from karuvottam.health import database_is_ready
from karuvottam.lunar_events import LunarEventEngine
from karuvottam.observation_inspection import ObservationInspectionService
from karuvottam.probability_calibration import ProbabilityCalibrationEngine
from karuvottam.rain_categories import RainCategoryEngine
from karuvottam.research_scoring import ResearchScoringEngine
from karuvottam.security import AdminAuthenticator, query_parameters_are_safe
from karuvottam.status_dashboard import StatusDashboardService
from karuvottam.weather_client import (
    OpenMeteoHistoricalClient,
    RawWeatherPayloadStore,
    WeatherIngestionService,
    WeatherClientError,
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
configure_application_logging(
    app.logger,
    log_path=settings.log_path,
    level=settings.log_level,
    secrets=(settings.weather_api_key or '', settings.admin_password or ''),
)
app.config.from_mapping(
    DEBUG=False,
    MAX_CONTENT_LENGTH=settings.max_request_bytes,
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
ADMIN_AUTHENTICATOR = AdminAuthenticator(
    settings.admin_username,
    settings.admin_password,
)
DATA_ACCESS = DataAccess(settings.database_path)
WEATHER_QUALITY_VALIDATOR = WeatherQualityValidator()
RESEARCH_SCORING_ENGINE = ResearchScoringEngine()
RAIN_CATEGORY_ENGINE = RainCategoryEngine()
FORECAST_TIMELINE_ENGINE = ForecastTimelineEngine(settings.timezone)
PROBABILITY_CALIBRATION_ENGINE = ProbabilityCalibrationEngine()
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
FORECAST_INPUT_SERVICE = StoredForecastInputService(
    DATA_ACCESS,
    RESEARCH_SCORING_ENGINE,
    WEATHER_QUALITY_VALIDATOR,
    location_name=settings.location_name,
    latitude=settings.latitude,
    longitude=settings.longitude,
    timezone_name=settings.timezone_name,
    source=f'{WEATHER_PROVIDER_SPEC.key}:{WEATHER_PROVIDER_SPEC.model}',
)
app.extensions['data_access'] = DATA_ACCESS
app.extensions['weather_provider_spec'] = WEATHER_PROVIDER_SPEC
app.extensions['weather_client'] = WEATHER_CLIENT
app.extensions['weather_quality_validator'] = WEATHER_QUALITY_VALIDATOR
app.extensions['research_scoring_engine'] = RESEARCH_SCORING_ENGINE
app.extensions['rain_category_engine'] = RAIN_CATEGORY_ENGINE
app.extensions['forecast_timeline_engine'] = FORECAST_TIMELINE_ENGINE
app.extensions['probability_calibration_engine'] = PROBABILITY_CALIBRATION_ENGINE
app.extensions['weather_csv_service'] = WEATHER_CSV_SERVICE
app.extensions['weather_ingestion_service'] = WEATHER_INGESTION_SERVICE
app.extensions['forecast_input_service'] = FORECAST_INPUT_SERVICE
app.extensions['admin_authenticator'] = ADMIN_AUTHENTICATOR

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
STATUS_DASHBOARD_SERVICE = StatusDashboardService(
    DATA_ACCESS,
    WINDOW_ENGINE,
    location_name=settings.location_name,
    latitude=settings.latitude,
    longitude=settings.longitude,
    timezone_name=settings.timezone_name,
)
CALENDAR_VIEW_SERVICE = CalendarViewService(DATA_ACCESS, WINDOW_ENGINE)
FORECAST_CALENDAR_SERVICE = ForecastCalendarService(CALENDAR_RULE)
OBSERVATION_INSPECTION_SERVICE = ObservationInspectionService(
    DATA_ACCESS,
    location_name=settings.location_name,
    latitude=settings.latitude,
    longitude=settings.longitude,
    timezone_name=settings.timezone_name,
)
EVENT_TRACK_SERVICE = EventTrackService(
    DATA_ACCESS,
    target_latitude=settings.latitude,
    target_longitude=settings.longitude,
)
EVENT_IMPACT_SERVICE = EventImpactService(
    DATA_ACCESS,
    location_name=settings.location_name,
    target_latitude=settings.latitude,
    target_longitude=settings.longitude,
    timezone_name=settings.timezone_name,
)
CLIMATE_CONTEXT_SERVICE = ClimateContextService(DATA_ACCESS)
EVENT_DASHBOARD_EVIDENCE_SERVICE = EventDashboardEvidenceService(
    Path(environ.get('KARUVOTTAM_RESEARCH_FINDINGS_DIR',
                     PROJECT_ROOT / 'data/exports/research-findings-2015-2024')),
    Path(environ.get('KARUVOTTAM_ROLLING_VALIDATION_DIR',
                     PROJECT_ROOT / 'data/exports/rolling-validation-2015-2024')),
    Path(environ.get('KARUVOTTAM_EVALUATION_DATASET_DIR',
                     PROJECT_ROOT / 'data/exports/evaluation-2015-2024')),
    Path(environ.get('KARUVOTTAM_EVENT_RAINFALL_DIR',
                     PROJECT_ROOT / 'data/exports/event-rainfall-2015-2024')),
    latitude=settings.latitude,
    longitude=settings.longitude,
    combined_validation_dir=Path(environ.get(
        'KARUVOTTAM_COMBINED_VALIDATION_DIR',
        PROJECT_ROOT / 'data/exports/combined-validation-2015-2024',
    )),
    calibration_dir=Path(environ.get(
        'KARUVOTTAM_SCORE_CALIBRATION_DIR',
        PROJECT_ROOT / 'data/exports/score-calibration-2015-2024',
    )),
)
SOURCE_MONITOR_STORE = MonitorStore(Path(environ.get(
    'KARUVOTTAM_SOURCE_MONITOR_STATE', DEFAULT_STATE,
)))
app.extensions['status_dashboard_service'] = STATUS_DASHBOARD_SERVICE
app.extensions['calendar_view_service'] = CALENDAR_VIEW_SERVICE
app.extensions['forecast_calendar_service'] = FORECAST_CALENDAR_SERVICE
app.extensions['observation_inspection_service'] = OBSERVATION_INSPECTION_SERVICE
app.extensions['event_track_service'] = EVENT_TRACK_SERVICE
app.extensions['event_impact_service'] = EVENT_IMPACT_SERVICE
app.extensions['climate_context_service'] = CLIMATE_CONTEXT_SERVICE
app.extensions['event_dashboard_evidence_service'] = EVENT_DASHBOARD_EVIDENCE_SERVICE
app.extensions['source_monitor_store'] = SOURCE_MONITOR_STORE

MIN_UI_YEAR = 2015
MAX_UI_YEAR = 2100
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


@dataclass(frozen=True)
class LocationProfile:
    location: LocationRecord | None
    name: str
    latitude: float
    longitude: float
    timezone_name: str
    calendar_rule: CalendarRule
    window_engine: KaruvottamWindowEngine

    @property
    def query(self) -> str:
        return f'&location={self.location.id}' if self.location else ''


def is_default_profile(profile: LocationProfile) -> bool:
    return (profile.name == settings.location_name
            and abs(profile.latitude - settings.latitude) < 0.000001
            and abs(profile.longitude - settings.longitude) < 0.000001
            and profile.timezone_name == settings.timezone_name
            and profile.calendar_rule.version == settings.calendar_rule_version
            and profile.calendar_rule.reference_label == CALENDAR_RULE.reference_label
            and profile.window_engine.margazhi_anchor_year
            == settings.margazhi_alternation_anchor_year
            and profile.window_engine.margazhi_anchor_phase
            == settings.margazhi_alternation_anchor_phase)


def profile_from_location(
    selected: LocationRecord | None,
    rules: LocationRulesRecord | None = None,
) -> LocationProfile:
    if selected is None:
        name, latitude, longitude, zone = (
            settings.location_name, settings.latitude, settings.longitude,
            settings.timezone_name,
        )
    else:
        name, latitude, longitude, zone = (
            selected.name, selected.latitude, selected.longitude,
            selected.timezone_name,
        )
    reference = rules.chithirai_reference if rules else settings.chithirai_reference
    month, day = (int(part) for part in reference.split('-', 1))
    rule = CalendarRule(
        reference_month=month, reference_day=day,
        version=rules.rule_version if rules else settings.calendar_rule_version,
    )
    engine = KaruvottamWindowEngine(
        rule, LunarEventEngine(ZoneInfo(zone)),
        margazhi_anchor_year=(rules.margazhi_anchor_year if rules else
                              settings.margazhi_alternation_anchor_year),
        margazhi_anchor_phase=(rules.margazhi_anchor_phase if rules else
                               settings.margazhi_alternation_anchor_phase),
    )
    return LocationProfile(selected, name, latitude, longitude, zone, rule, engine)


def selected_location_profile() -> LocationProfile:
    cached = getattr(g, 'location_profile', None)
    if cached is not None:
        return cached
    locations: tuple[LocationRecord, ...] = ()
    rules = None
    selected = None
    try:
        with app.extensions['data_access'].transaction() as work:
            locations = work.locations.list_active()
            raw_id = request.args.get('location', '')
            if raw_id:
                selected = next(
                    (item for item in locations if str(item.id) == raw_id), None
                )
                if selected is None:
                    add_ui_notice('இடம் செல்லாது; இயல்புநிலை இடம் காட்டப்படுகிறது.')
            if selected is None:
                selected = next((item for item in locations
                                 if item.name == settings.location_name
                                 and abs(item.latitude - settings.latitude) < 0.000001
                                 and abs(item.longitude - settings.longitude) < 0.000001),
                                locations[0] if locations else None)
            if selected is not None:
                rules = work.locations.rules(selected.id)
    except DataAccessError:
        pass
    profile = profile_from_location(selected, rules)
    g.location_profile = profile
    g.locations = locations
    return profile


@app.before_request
def assign_request_id() -> None:
    supplied = request.headers.get('X-Request-ID', '')
    g.request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid4().hex


@app.before_request
def validate_query_parameters() -> None:
    if not query_parameters_are_safe(
        request.query_string,
        list(request.args.lists()),
    ):
        abort(400)


@app.after_request
def include_request_id(response: Response) -> Response:
    response.headers['X-Request-ID'] = getattr(g, 'request_id', uuid4().hex)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; object-src 'none'; base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    if request.path.startswith('/admin'):
        response.headers['Cache-Control'] = 'no-store'
    return response


def add_ui_notice(message: str) -> None:
    existing = getattr(g, 'ui_notice', None)
    g.ui_notice = f'{existing} {message}' if existing else message


@app.context_processor
def inject_ui_notice():
    profile = selected_location_profile()
    return {
        'ui_notice': getattr(g, 'ui_notice', None),
        'request_id': getattr(g, 'request_id', None),
        'selected_location': profile,
        'active_locations': getattr(g, 'locations', ()),
    }


def _render_error(status_code: int, title: str, message: str):
    return make_response(
        render_template(
            'error.html',
            status_code=status_code,
            error_title=title,
            error_message=message,
        ),
        status_code,
    )


def require_admin(view):
    """Protect an administration view without cookie or session state."""
    @wraps(view)
    def protected_view(*args, **kwargs):
        authenticator = app.extensions['admin_authenticator']
        if not authenticator.enabled:
            app.logger.warning(
                'Disabled admin route requested request_id=%s path=%s',
                g.request_id,
                request.path,
            )
            return _render_error(
                503,
                'நிர்வாக அணுகல் அமைக்கப்படவில்லை',
                'நிர்வாகச் சான்றுகளை சூழல் மாறிகளில் அமைக்கவும்.',
            )
        if not authenticator.authenticate(request.headers.get('Authorization')):
            app.logger.warning(
                'Admin authentication rejected request_id=%s path=%s',
                g.request_id,
                request.path,
            )
            response = _render_error(
                401,
                'நிர்வாக அங்கீகாரம் தேவை',
                'செல்லுபடியாகும் நிர்வாகச் சான்றுகளை வழங்கவும்.',
            )
            response.headers['WWW-Authenticate'] = (
                'Basic realm="Karuvottam administration", charset="UTF-8"'
            )
            return response
        g.admin_username = authenticator.username
        return view(*args, **kwargs)

    return protected_view


@app.errorhandler(DataAccessError)
def handle_database_error(error: DataAccessError):
    app.logger.exception(
        'Database request failed request_id=%s method=%s path=%s error_type=%s',
        g.request_id,
        request.method,
        request.path,
        type(error).__name__,
    )
    return _render_error(
        503,
        'தரவுச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை',
        'சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.',
    )


@app.errorhandler(WeatherClientError)
def handle_weather_error(error: WeatherClientError):
    app.logger.exception(
        'Weather provider request failed request_id=%s method=%s path=%s error_type=%s',
        g.request_id,
        request.method,
        request.path,
        type(error).__name__,
    )
    return _render_error(
        503,
        'வானிலைச் சேவை தற்காலிகமாகக் கிடைக்கவில்லை',
        'சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும்.',
    )


@app.errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    titles = {
        404: 'கோரிய பக்கம் கிடைக்கவில்லை',
        405: 'இந்தச் செயல் அனுமதிக்கப்படவில்லை',
    }
    title = titles.get(error.code or 500, 'கோரிக்கையை நிறைவேற்ற முடியவில்லை')
    return _render_error(
        error.code or 500,
        title,
        'முகப்புப் பக்கத்திற்குத் திரும்பி மீண்டும் முயற்சிக்கவும்.',
    )


@app.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    app.logger.exception(
        'Unexpected request failure request_id=%s method=%s path=%s error_type=%s',
        g.request_id,
        request.method,
        request.path,
        type(error).__name__,
    )
    return _render_error(
        500,
        'எதிர்பாராத பிழை ஏற்பட்டது',
        'இந்தக் குறிப்பு எண்ணுடன் நிர்வாகியைத் தொடர்புகொள்ளவும்.',
    )

def karuvottam_window(year: int, kind: str):
    window = WINDOW_ENGINE.generate(kind, year)
    return window.start_datetime_local, window.end_datetime_local


def requested_year(default: int = 2026) -> int:
    raw_year = request.args.get('year', str(default))
    try:
        year = int(raw_year)
    except ValueError:
        app.logger.warning('Invalid year parameter %r; using %s', raw_year, default)
        add_ui_notice(
            f'ஆண்டு செல்லாது; இயல்புநிலை {default} ஆண்டு காட்டப்படுகிறது.'
        )
        return default
    if not MIN_UI_YEAR <= year <= MAX_UI_YEAR:
        app.logger.warning(
            'Invalid year parameter %r; supported range is %s-%s; using %s',
            raw_year,
            MIN_UI_YEAR,
            MAX_UI_YEAR,
            default,
        )
        add_ui_notice(
            f'ஆண்டு {MIN_UI_YEAR}–{MAX_UI_YEAR} வரம்பில் இருக்க வேண்டும்; '
            f'{default} ஆண்டு காட்டப்படுகிறது.'
        )
        return default
    return year


def forecast_period_after_window(window_end: datetime, total_days: int,
                                 timezone_name: str = settings.timezone_name):
    """Return the inclusive local-date forecast period after an observation window."""
    if window_end.tzinfo is None or window_end.utcoffset() is None:
        raise ValueError('window_end must be timezone-aware')
    if total_days < 1:
        raise ValueError('total_days must be at least 1')

    local_end_date = window_end.astimezone(ZoneInfo(timezone_name)).date()
    start = local_end_date + timedelta(days=1)
    end = start + timedelta(days=total_days - 1)
    return start, end


def build_cycle(year: int, profile: LocationProfile | None = None):
    engine = profile.window_engine if profile else WINDOW_ENGINE
    zone = profile.timezone_name if profile else settings.timezone_name
    aadi_window = engine.generate('aadi', year)
    margazhi_window = engine.generate('margazhi', year)
    next_aadi_window = engine.generate('aadi', year + 1)
    a_start = aadi_window.start_datetime_local
    a_end = aadi_window.end_datetime_local
    m_start = margazhi_window.start_datetime_local
    m_end = margazhi_window.end_datetime_local
    aadi_prediction_start, aadi_prediction_end = forecast_period_after_window(m_end, 180, zone)
    margazhi_prediction_start, margazhi_prediction_end = forecast_period_after_window(
        next_aadi_window.end_datetime_local,
        140, zone,
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


@app.template_filter('dashboard_datetime')
def dashboard_datetime(value):
    if not value:
        return 'தரவு இல்லை'
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    zone = (selected_location_profile().timezone_name if has_request_context()
            else settings.timezone_name)
    return parsed.astimezone(ZoneInfo(zone)).strftime('%d-%m-%Y %H:%M')


@app.template_filter('quality_tamil')
def quality_tamil(value):
    labels = {
        'valid': 'செல்லுபடியாகும்',
        'verified': 'சரிபார்க்கப்பட்டது',
        'calculated': 'கணக்கிடப்பட்டது',
        'warning': 'எச்சரிக்கை',
        'invalid': 'செல்லாதது',
        'unavailable': 'தரவு இல்லை',
        'unvalidated_reanalysis': 'சரிபார்க்காத மறுபகுப்பாய்வு',
        'missing': 'மதிப்புகள் விடுபட்டவை',
        'out_of_range': 'வரம்பிற்கு வெளியே',
        'duplicate': 'நகல் பதிவு',
        'interpolated': 'இடைமதிப்பீடு',
        'outside_window': 'கால வரம்பிற்கு வெளியே',
    }
    if not value:
        return 'தரவு இல்லை'
    return ' + '.join(labels.get(part, part) for part in value.split('+'))


@app.get('/health/live')
def health_live():
    return {'status': 'ok'}


@app.get('/health/ready')
def health_ready():
    if database_is_ready(app.config['DATABASE_PATH']):
        return {'status': 'ready'}
    return {'status': 'unavailable'}, 503

@app.route('/')
def index():
    year = requested_year()
    profile = selected_location_profile()
    cycle = build_cycle(year, profile)
    dashboard_service = (STATUS_DASHBOARD_SERVICE if is_default_profile(profile) else StatusDashboardService(
        app.extensions['data_access'], profile.window_engine,
        location_name=profile.name, latitude=profile.latitude,
        longitude=profile.longitude, timezone_name=profile.timezone_name,
    ))
    dashboard = dashboard_service.build()
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
        calendar_rule=profile.calendar_rule,
        lunar_events=lunar_events,
        lunar_error=None,
        dashboard=dashboard,
    )


@app.route('/admin')
@require_admin
def admin_dashboard():
    dashboard = STATUS_DASHBOARD_SERVICE.build()
    return render_template(
        'admin.html',
        dashboard=dashboard,
        admin_username=g.admin_username,
        provider_key=WEATHER_PROVIDER_SPEC.key,
        provider_model=WEATHER_PROVIDER_SPEC.model,
        api_key_configured=settings.weather_api_key is not None,
    )

@app.route('/prediction')
def prediction():
    year = requested_year()
    mode = requested_prediction_mode()
    view_mode = request.args.get('view', 'day')
    if view_mode not in VIEW_MODES:
        app.logger.warning(
            'Invalid forecast view %r; using day',
            view_mode,
        )
        add_ui_notice('காட்சி வகை செல்லாது; நாள் காட்சி காட்டப்படுகிறது.')
        view_mode = 'day'
    profile = selected_location_profile()
    timeline, forecast_input = build_prediction_context(year, mode, profile)
    forecast_calendar = ForecastCalendarService(profile.calendar_rule).build(timeline, view_mode)
    return render_template(
        'prediction.html',
        mode=mode,
        year=year,
        days=timeline.total_days,
        start=fmt(timeline.prediction_start),
        calendar_rule=profile.calendar_rule,
        timeline=timeline,
        forecast_calendar=forecast_calendar,
        forecast_input=forecast_input,
    )


def requested_prediction_mode() -> str:
    mode = request.args.get('mode', 'aadi')
    if mode in {'aadi', 'margazhi'}:
        return mode
    add_ui_notice('கருவோட்ட வகை செல்லாது; ஆடி தேர்ந்தெடுக்கப்பட்டது.')
    return 'aadi'


def build_prediction_timeline(year: int, mode: str, profile: LocationProfile | None = None):
    timeline, _ = build_prediction_context(year, mode, profile)
    return timeline


def build_prediction_context(year: int, mode: str, profile: LocationProfile | None = None):
    cycle = build_cycle(year, profile)
    source_window = cycle[f'{mode}_window']
    mapping_basis_end = (
        cycle['margazhi_window'].end_datetime_local
        if mode == 'aadi'
        else cycle['next_aadi_window'].end_datetime_local
    )
    inputs = (StoredForecastInputService(
        app.extensions['data_access'], RESEARCH_SCORING_ENGINE,
        WEATHER_QUALITY_VALIDATOR, location_name=profile.name,
        latitude=profile.latitude, longitude=profile.longitude,
        timezone_name=profile.timezone_name,
        source=f'{WEATHER_PROVIDER_SPEC.key}:{WEATHER_PROVIDER_SPEC.model}',
    ) if profile and not is_default_profile(profile) else FORECAST_INPUT_SERVICE)
    forecast_input = inputs.score(source_window)
    timeline_engine = (ForecastTimelineEngine(ZoneInfo(profile.timezone_name))
                       if profile else FORECAST_TIMELINE_ENGINE)
    timeline = timeline_engine.generate(
        source_window,
        mapping_basis_end_local=mapping_basis_end,
        research_score=forecast_input.research_score,
        generated_at=datetime.now(timezone.utc),
    )
    return timeline, forecast_input


@app.route('/prediction.csv')
def prediction_csv():
    year = requested_year()
    mode = requested_prediction_mode()
    profile = selected_location_profile()
    timeline = build_prediction_timeline(year, mode, profile)
    csv_data = ForecastCalendarService(profile.calendar_rule).export_csv(timeline)
    suffix = (f'-location-{profile.location.id}'
              if profile.location and not is_default_profile(profile) else '')
    filename = f'karuvottam-{mode}-{year}{suffix}-forecast.csv'
    return Response(
        csv_data,
        content_type='text/csv; charset=utf-8',
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
    )


@app.route('/calendar')
def calendar_view():
    year = requested_year()
    profile = selected_location_profile()
    calendar_service = (CALENDAR_VIEW_SERVICE if is_default_profile(profile) else CalendarViewService(
        app.extensions['data_access'], profile.window_engine,
        location_id=profile.location.id if profile.location else None,
    ))
    calendar = calendar_service.build(year)
    return render_template(
        'calendar.html',
        calendar=calendar,
        selected_year=year,
    )


@app.route('/observations')
def observations():
    profile = selected_location_profile()
    raw_start = request.args.get('start', '').strip()
    raw_end = request.args.get('end', '').strip()
    source = request.args.get('source', '').strip() or None
    start_date = end_date = None
    input_error = None
    if raw_start or raw_end:
        try:
            if not raw_start or not raw_end:
                raise ValueError
            start_date = date.fromisoformat(raw_start)
            end_date = date.fromisoformat(raw_end)
        except ValueError:
            input_error = (
                'தொடக்கமும் முடிவும் YYYY-MM-DD வடிவில் செல்லுபடியாக உள்ளிடப்பட வேண்டும்.'
            )
            start_date = end_date = None
    try:
        inspection_service = (OBSERVATION_INSPECTION_SERVICE if is_default_profile(profile) else ObservationInspectionService(
            app.extensions['data_access'], location_name=profile.name,
            latitude=profile.latitude, longitude=profile.longitude,
            timezone_name=profile.timezone_name,
        ))
        inspection = inspection_service.build(
            start_date=start_date,
            end_date=end_date,
            source=source,
        )
    except ValueError as exc:
        app.logger.warning('Invalid observation range: %s', exc)
        input_error = 'தேதி வரம்பு செல்லாது அல்லது 366 நாட்களை மீறுகிறது.'
        inspection = inspection_service.build(source=source)
    return render_template(
        'observations.html',
        inspection=inspection,
        input_error=input_error,
    )


@app.get('/events')
def events():
    profile = selected_location_profile()
    is_default = (profile.name == settings.location_name
                  and abs(profile.latitude - settings.latitude) < 0.000001
                  and abs(profile.longitude - settings.longitude) < 0.000001
                  and profile.timezone_name == settings.timezone_name)
    service = (app.extensions['event_track_service'] if is_default else
               EventTrackService(app.extensions['data_access'],
                                 target_latitude=profile.latitude,
                                 target_longitude=profile.longitude))
    try:
        default_year = service.latest_year() or datetime.now(ZoneInfo(profile.timezone_name)).year
    except DataAccessError:
        default_year = datetime.now(ZoneInfo(profile.timezone_name)).year
    year = requested_year(default=default_year)
    event_key = request.args.get('event') or None
    try:
        track = service.build(year, event_key)
        impact_service = (app.extensions['event_impact_service'] if is_default else
                          EventImpactService(
                              app.extensions['data_access'], location_name=profile.name,
                              target_latitude=profile.latitude,
                              target_longitude=profile.longitude,
                              timezone_name=profile.timezone_name))
        impact = impact_service.build(track) if track.selected else None
        warning = None
    except DataAccessError:
        track = None
        impact = None
        warning = 'நிகழ்வு தரவுத்தளம் தற்போது கிடைக்கவில்லை.'
    try:
        climate_context = app.extensions['climate_context_service'].build()
        climate_warning = None
    except DataAccessError:
        climate_context = ()
        climate_warning = 'பருவநிலைச் சுட்டித் தரவுத்தளம் தற்போது கிடைக்கவில்லை.'
    default_evidence = app.extensions['event_dashboard_evidence_service']
    evidence = (default_evidence if is_default else EventDashboardEvidenceService(
        default_evidence.findings_dir, default_evidence.validation_dir,
        default_evidence.dataset_dir, default_evidence.event_rainfall_dir,
        latitude=profile.latitude, longitude=profile.longitude,
        combined_validation_dir=default_evidence.combined_validation_dir,
        calibration_dir=default_evidence.calibration_dir,
    ))
    comparison = evidence.comparison()
    return render_template(
        'events.html', track=track, impact=impact, year=year, warning=warning,
        target_name=profile.name, climate_context=climate_context,
        climate_warning=climate_warning,
        comparison=comparison, event_rainfall=evidence.event_rainfall(),
        combined_decision=evidence.combined_decision(comparison),
        source_statuses=app.extensions['source_monitor_store'].statuses(),
    )


@app.get('/climate')
def climate():
    try:
        context = app.extensions['climate_context_service'].build()
        warning = None
    except DataAccessError:
        context = ()
        warning = 'காலநிலைச் சுட்டித் தரவுத்தளம் தற்போது கிடைக்கவில்லை.'
    return render_template(
        'climate.html', context=context, warning=warning,
        source_statuses=tuple(
            item for item in app.extensions['source_monitor_store'].statuses()
            if item.source in ('dmi', 'oni')
        ),
    )

if __name__ == '__main__':
    app.run(
        host='127.0.0.1',
        port=settings.port,
        debug=False,
        use_reloader=False,
    )
