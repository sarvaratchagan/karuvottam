from datetime import date

from app import app
from karuvottam.sidhariyal_calendar import SidhariyalCalendar


def test_public_page_month_boundaries_and_karthigai_date():
    calendar = SidhariyalCalendar()
    assert calendar.from_gregorian(date(2026, 11, 14)).month_name == 'கார்த்திகை'
    assert calendar.from_gregorian(date(2026, 11, 14)).day == 23
    assert calendar.from_gregorian(date(2026, 10, 22)).month_name == 'ஐப்பசி'
    assert calendar.from_gregorian(date(2026, 10, 23)).day == 1
    assert calendar.from_gregorian(date(2027, 1, 19)).month_name == 'தை'
    assert calendar.from_gregorian(date(2027, 1, 20)).month_name == 'மாசி'
    assert calendar.from_gregorian(date(2027, 3, 20)).month_name == 'பங்குனி'
    assert calendar.from_gregorian(date(2027, 3, 21)).day == 1


def test_month_grid_spans_week_and_year_boundaries():
    calendar = SidhariyalCalendar()
    month = calendar.build(2026, 8)
    assert month.start == date(2026, 10, 23)
    assert month.end_exclusive == date(2026, 11, 22)
    assert month.weeks[0][5].day == 1  # Friday, with Sunday in column zero.
    assert month.weeks[-1][-1].day == 30
    assert calendar.build(2026, 12).next_year == 2027
    assert calendar.build(2027, 1).previous_year == 2026
    assert calendar.build(2030, 8).verified is False
    assert (calendar.build(2026, 4).end_exclusive - calendar.build(2026, 4).start).days == 32


def test_month_page_shows_source_and_projection_notice():
    app.config.update(TESTING=True)
    with app.test_client() as client:
        page = client.get('/sidhariyal-calendar?year=2026&month=8').get_data(as_text=True)
        assert 'கார்த்திகை 2026' in page
        assert '23-10-2026' in page
        assert '21-11-2026' in page
        assert 'https://sidhariyal.org/sidhariyalmonthycalendar' in page
        projected = client.get('/sidhariyal-calendar?year=2030&month=8').get_data(as_text=True)
        assert 'துல்லிய ஒற்றுமை உறுதி செய்யப்படவில்லை' in projected
