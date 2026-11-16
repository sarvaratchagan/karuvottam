from datetime import date

from app import WINDOW_ENGINE, app
from karuvottam.calendar_almanac import CalendarAlmanac
from karuvottam.calendar_markers import markers_for_month


def test_aadi_and_margazhi_window_boundaries_land_on_calendar_days():
    aadi = markers_for_month(WINDOW_ENGINE, date(2026, 6, 21), date(2026, 7, 23))
    assert aadi.unavailable == ()
    start = aadi.by_date[date(2026, 6, 30)][0]
    end = aadi.by_date[date(2026, 7, 18)][0]
    assert (start.label, start.boundary, start.instant.strftime('%H:%M')) == (
        'கருவோட்டம் தொடக்கம்', 'start', '05:27')
    assert (end.label, end.boundary, end.instant.strftime('%H:%M')) == (
        'கருவோட்டம் முடிவு', 'end', '05:27')

    margazhi = markers_for_month(WINDOW_ENGINE, date(2026, 11, 22), date(2026, 12, 22))
    assert margazhi.by_date[date(2026, 12, 9)][0].label == 'கருவோட்டம் தொடக்கம்'
    assert margazhi.by_date[date(2026, 12, 20)][0].label == 'கருவோட்டம் முடிவு'

    next_year = markers_for_month(WINDOW_ENGINE, date(2027, 11, 22), date(2027, 12, 22))
    full_moon_day = date(2027, 12, 13)
    assert next_year.by_date[full_moon_day][0].label == 'கருவோட்டம் தொடக்கம்'
    almanac = CalendarAlmanac(9.9, 77.9, 0, 'Asia/Kolkata').build(
        full_moon_day, date(2027, 12, 14))
    assert [phase.name for phase in almanac[full_moon_day].phases] == ['பௌர்ணமி']


def test_calendar_cards_have_flip_controls_and_visible_event_markers():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        aadi = client.get('/sidhariyal-calendar?year=2026&month=4').get_data(as_text=True)
        karthigai = client.get('/sidhariyal-calendar?year=2026&month=8').get_data(as_text=True)
    assert 'கருவோட்டம் தொடக்கம் · 05:27' in aadi
    assert 'கருவோட்டம் முடிவு · 05:27' in aadi
    assert 'முடிவு சேர்க்கப்படாது' in aadi
    assert 'data-sid-open aria-expanded="false"' in aadi
    assert 'data-sid-back hidden' in aadi
    assert '/static/sidhariyal-calendar.js' in aadi
    assert '🌑' in karthigai
    assert '🌕' in karthigai
    assert 'அமாவாசை · 12:32' in karthigai
    assert 'பௌர்ணமி · 09:42' in karthigai
