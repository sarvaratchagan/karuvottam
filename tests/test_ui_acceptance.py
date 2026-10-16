from html.parser import HTMLParser
import importlib
import re

import pytest

from app import app
from karuvottam.calendar_view import CalendarViewService
from karuvottam.data_access import DataAccess
from karuvottam.observation_inspection import ObservationInspectionService
from karuvottam.status_dashboard import StatusDashboardService


app_module = importlib.import_module('app')


TAMIL_TEXT = re.compile(r'[\u0B80-\u0BFF]')
KEY_PAGES = (
    '/',
    '/calendar?year=2026',
    '/prediction?year=2026&mode=aadi&view=day',
    '/prediction?year=2026&mode=aadi&view=week',
    '/prediction?year=2026&mode=margazhi&view=month',
    '/observations',
)


class AccessibilityAuditParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.html_lang = None
        self.ids: list[str] = []
        self.main_ids: list[str | None] = []
        self.skip_targets: list[str] = []
        self.h1_count = 0
        self.title_count = 0
        self.table_count = 0
        self.caption_count = 0
        self.th_without_scope = 0
        self.in_label = 0
        self.label_for: set[str] = set()
        self.unlabelled_controls: list[str] = []
        self.in_button = 0
        self.button_text: list[str] = []
        self.in_title = 0
        self.in_head = 0
        self.title_text: list[str] = []
        self.in_h1 = 0
        self.h1_text: list[str] = []
        self.inaccessible_svgs = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get('id')
        if element_id:
            self.ids.append(element_id)
        if tag == 'html':
            self.html_lang = attributes.get('lang')
        elif tag == 'head':
            self.in_head += 1
        elif tag == 'main':
            self.main_ids.append(element_id)
        elif tag == 'a' and 'skip-link' in attributes.get('class', '').split():
            self.skip_targets.append(attributes.get('href', ''))
        elif tag == 'h1':
            self.h1_count += 1
            self.in_h1 += 1
        elif tag == 'title' and self.in_head:
            self.title_count += 1
            self.in_title += 1
        elif tag == 'label':
            self.in_label += 1
            if attributes.get('for'):
                self.label_for.add(attributes['for'])
        elif tag in {'input', 'select'}:
            if attributes.get('type') == 'hidden':
                return
            labelled = (
                self.in_label > 0
                or bool(attributes.get('aria-label'))
                or bool(attributes.get('aria-labelledby'))
                or (element_id is not None and element_id in self.label_for)
            )
            if not labelled:
                self.unlabelled_controls.append(attributes.get('name', tag))
        elif tag == 'button':
            self.in_button += 1
            self.button_text.append('')
        elif tag == 'table':
            self.table_count += 1
        elif tag == 'caption':
            self.caption_count += 1
        elif tag == 'th' and attributes.get('scope') not in {'col', 'row'}:
            self.th_without_scope += 1
        elif tag == 'svg':
            if attributes.get('role') != 'img' or not (
                attributes.get('aria-label') or attributes.get('aria-labelledby')
            ):
                self.inaccessible_svgs += 1

    def handle_endtag(self, tag):
        if tag == 'head':
            self.in_head -= 1
        elif tag == 'label':
            self.in_label -= 1
        elif tag == 'button':
            self.in_button -= 1
        elif tag == 'title' and self.in_title:
            self.in_title -= 1
        elif tag == 'h1':
            self.in_h1 -= 1

    def handle_data(self, data):
        if self.in_button and self.button_text:
            self.button_text[-1] += data
        if self.in_title:
            self.title_text.append(data)
        if self.in_h1:
            self.h1_text.append(data)


@pytest.fixture()
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def no_data_client(tmp_path, monkeypatch):
    data_access = DataAccess(tmp_path / 'unmigrated.sqlite3')
    monkeypatch.setattr(
        app_module,
        'STATUS_DASHBOARD_SERVICE',
        StatusDashboardService(
            data_access,
            app_module.WINDOW_ENGINE,
            location_name=app_module.settings.location_name,
            latitude=app_module.settings.latitude,
            longitude=app_module.settings.longitude,
            timezone_name=app_module.settings.timezone_name,
        ),
    )
    monkeypatch.setattr(
        app_module,
        'CALENDAR_VIEW_SERVICE',
        CalendarViewService(data_access, app_module.WINDOW_ENGINE),
    )
    monkeypatch.setattr(
        app_module,
        'OBSERVATION_INSPECTION_SERVICE',
        ObservationInspectionService(
            data_access,
            location_name=app_module.settings.location_name,
            latitude=app_module.settings.latitude,
            longitude=app_module.settings.longitude,
            timezone_name=app_module.settings.timezone_name,
        ),
    )
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


@pytest.mark.parametrize('path', KEY_PAGES)
def test_key_pages_have_accessible_tamil_document_structure(client, path):
    response = client.get(path)
    html = response.get_data(as_text=True)
    parser = AccessibilityAuditParser()
    parser.feed(html)

    assert response.status_code == 200
    assert response.content_type == 'text/html; charset=utf-8'
    assert html.lstrip().lower().startswith('<!doctype html>')
    assert '\ufffd' not in html
    assert TAMIL_TEXT.search(html)
    assert parser.html_lang == 'ta'
    assert parser.title_count == 1
    assert ''.join(parser.title_text).strip()
    assert parser.h1_count == 1
    assert ''.join(parser.h1_text).strip()
    assert parser.main_ids == ['main-content']
    assert parser.skip_targets == ['#main-content']
    assert len(parser.ids) == len(set(parser.ids))
    assert parser.unlabelled_controls == []
    assert all(text.strip() for text in parser.button_text)
    assert parser.caption_count == parser.table_count
    assert parser.th_without_scope == 0
    assert parser.inaccessible_svgs == 0
    assert 'name="viewport"' in html


@pytest.mark.parametrize(
    ('path', 'expected_text'),
    [
        ('/?year=-1', 'ஆண்டு 2020–2100 வரம்பில் இருக்க வேண்டும்'),
        ('/calendar?year=999999', 'ஆண்டு 2020–2100 வரம்பில் இருக்க வேண்டும்'),
        (
            '/prediction?year=0&mode=unknown&view=unknown',
            'கருவோட்ட வகை செல்லாது; ஆடி தேர்ந்தெடுக்கப்பட்டது',
        ),
        (
            '/observations?start=bad&end=2026-01-01',
            'YYYY-MM-DD வடிவில் செல்லுபடியாக',
        ),
        (
            '/observations?start=2026-02-01&end=2026-01-01',
            'தேதி வரம்பு செல்லாது',
        ),
        (
            '/observations?start=2020-01-01&end=2022-01-01',
            '366 நாட்களை மீறுகிறது',
        ),
    ],
)
def test_invalid_ui_inputs_return_understandable_pages(client, path, expected_text):
    response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ('path', 'expected_text'),
    [
        ('/', 'தரவுத்தளம் தயாராக இல்லை'),
        ('/calendar?year=2026', 'கணக்கிடப்பட்டது; இன்னும் சேமிக்கப்படவில்லை'),
        ('/prediction?year=2026&mode=aadi', 'கற்பனை மதிப்புகள் காட்டப்படாது'),
        ('/observations', 'தரவுத்தளம் தயாராக இல்லை'),
    ],
)
def test_no_data_states_are_explained_in_tamil(no_data_client, path, expected_text):
    response = no_data_client.get(path)

    assert response.status_code == 200
    assert expected_text in response.get_data(as_text=True)


def test_stylesheet_contains_keyboard_mobile_and_contrast_support(client):
    css = client.get('/static/style.css').get_data(as_text=True)

    assert ':focus-visible' in css
    assert '.skip-link:focus' in css
    assert 'min-height: 44px' in css
    assert '@media(max-width:760px)' in css
    assert '.forecast-table td::before' in css
    assert '.observation-table td::before' in css
    assert '@media (prefers-reduced-motion: reduce)' in css
    assert '@media (forced-colors: active)' in css
