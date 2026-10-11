from datetime import date

import pytest

from karuvottam.calendar_engine import CalendarRule, TAMIL_MONTHS


@pytest.fixture()
def rule():
    return CalendarRule(reference_month=3, reference_day=21, version='1.0')


@pytest.mark.parametrize(
    ('gregorian', 'expected_year', 'expected_month', 'expected_day', 'expected_name'),
    [
        (date(2026, 3, 20), 2025, 12, 28, 'பங்குனி'),
        (date(2026, 3, 21), 2026, 1, 1, 'சித்திரை'),
        (date(2026, 4, 20), 2026, 1, 31, 'சித்திரை'),
        (date(2026, 4, 21), 2026, 2, 1, 'வைகாசி'),
        (date(2026, 6, 21), 2026, 4, 1, 'ஆடி'),
        (date(2026, 11, 21), 2026, 9, 1, 'மார்கழி'),
        (date(2027, 3, 20), 2026, 12, 28, 'பங்குனி'),
    ],
)
def test_gregorian_to_modified_tamil_boundaries(
    rule,
    gregorian,
    expected_year,
    expected_month,
    expected_day,
    expected_name,
):
    result = rule.from_gregorian(gregorian)

    assert result.year == expected_year
    assert result.month == expected_month
    assert result.day == expected_day
    assert result.month_name == expected_name
    assert result.rule_version == '1.0'


@pytest.mark.parametrize(
    ('tamil_year', 'month', 'day', 'expected'),
    [
        (2026, 1, 1, date(2026, 3, 21)),
        (2026, 1, 31, date(2026, 4, 20)),
        (2026, 4, 1, date(2026, 6, 21)),
        (2026, 9, 1, date(2026, 11, 21)),
        (2026, 12, 28, date(2027, 3, 20)),
        (2027, 12, 29, date(2028, 3, 20)),
    ],
)
def test_modified_tamil_to_gregorian(rule, tamil_year, month, day, expected):
    assert rule.to_gregorian(tamil_year, month, day) == expected


def test_every_date_round_trips(rule):
    current = date(2025, 1, 1)
    end = date(2029, 1, 1)

    while current < end:
        tamil_date = rule.from_gregorian(current)
        converted = rule.to_gregorian(
            tamil_date.year,
            tamil_date.month,
            tamil_date.day,
        )
        assert converted == current
        current = date.fromordinal(current.toordinal() + 1)


def test_leap_year_is_absorbed_by_panguni(rule):
    assert rule.month_length(2026, 12) == 28
    assert rule.month_length(2027, 12) == 29


def test_reference_date_is_configurable_and_versioned():
    rule = CalendarRule(reference_month=3, reference_day=22, version='2.0')

    result = rule.from_gregorian(date(2026, 3, 22))

    assert result.month_name == 'சித்திரை'
    assert result.day == 1
    assert result.rule_version == '2.0'


@pytest.mark.parametrize(
    ('month', 'day'),
    [(0, 1), (13, 1), (1, 0), (1, 32), (12, 29)],
)
def test_invalid_tamil_dates_are_rejected(rule, month, day):
    with pytest.raises(ValueError):
        rule.to_gregorian(2026, month, day)


def test_month_names_are_complete():
    assert len(TAMIL_MONTHS) == 12
    assert TAMIL_MONTHS[0] == 'சித்திரை'
    assert TAMIL_MONTHS[-1] == 'பங்குனி'
