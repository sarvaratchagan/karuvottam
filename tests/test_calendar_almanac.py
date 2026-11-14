from datetime import date, timedelta

from app import app
from karuvottam.calendar_almanac import CalendarAlmanac


def test_tithi_and_principal_phase_use_local_civil_date():
    details = CalendarAlmanac(13.08, 80.27, 6, 'Asia/Kolkata').build(
        date(2026, 11, 8), date(2026, 11, 11))
    new_moon_day = details[date(2026, 11, 9)]
    assert new_moon_day.tithi_name == 'அமாவாசை'
    assert new_moon_day.paksha_name == 'தேய்பிறை'
    assert new_moon_day.tithi_label == '15ம் தேய்பிறை'
    assert [phase.name for phase in new_moon_day.phases] == ['அமாவாசை']
    assert new_moon_day.phases[0].instant.date() == date(2026, 11, 9)
    assert new_moon_day.sunrise.date() == date(2026, 11, 9)
    assert new_moon_day.sunrise < new_moon_day.tithi_end
    assert new_moon_day.tithi_end < new_moon_day.sunrise + timedelta(days=3)
    assert details[date(2026, 11, 10)].paksha_name == 'வளர்பிறை'
    assert details[date(2026, 11, 10)].tithi_label == '1ம் வளர்பிறை'


def test_sunrise_depends_on_location_and_unavailable_polar_rise_is_explicit():
    target = date(2026, 11, 14)
    chennai = CalendarAlmanac(13.08, 80.27, 6, 'Asia/Kolkata').build(
        target, target + timedelta(days=1))[target]
    mumbai = CalendarAlmanac(19.08, 72.88, 14, 'Asia/Kolkata').build(
        target, target + timedelta(days=1))[target]
    assert chennai.sunrise < mumbai.sunrise
    assert chennai.dawn < chennai.sunrise
    assert chennai.sunrise < chennai.sunset
    assert chennai.sunset < chennai.dusk
    polar = CalendarAlmanac(89, 0, 0, 'UTC').build(
        date(2026, 12, 1), date(2026, 12, 2))[date(2026, 12, 1)]
    assert polar.sunrise is None
    assert polar.dawn is None
    assert polar.dusk is None
    assert polar.tithi_name is None
    assert polar.tithi_label is None


def test_month_page_renders_astronomy_details_and_source():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get('/sidhariyal-calendar?year=2026&month=8').get_data(as_text=True)
    assert 'திதி முடிவு:' in page
    assert 'அமாவாசை · 12:32' in page
    assert 'பௌர்ணமி · 09:42' in page
    assert 'உதயம்' in page
    assert 'அஸ்தமனம்' in page
    assert 'புலர்வு' in page
    assert 'சாய்வு' in page
    assert 'Astronomy Engine' in page


def test_phase_day_shows_event_badge_without_duplicate_day_label():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get('/sidhariyal-calendar?year=2026&month=9').get_data(as_text=True)
    assert 'அமாவாசை நாள்' not in page
    assert 'உதயத் திதி:' not in page
    assert 'சூரிய உதயத் திதி:' not in page
    assert '1ம் வளர்பிறை' in page
    assert 'கருவோட்டம் தொடக்கம் · 06:22' in page
    assert 'கருவோட்டம் முடிவு' in page
