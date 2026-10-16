from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from karuvottam.forecast_timeline import (
    PREDICTION_METHOD,
    TIMELINE_MODEL_VERSION,
    ForecastTimelineEngine,
    unavailable_research_score,
)
from karuvottam.lunar_events import LunarEvent
from karuvottam.research_scoring import ResearchScore
from karuvottam.windows import KaruvottamWindow


IST = ZoneInfo('Asia/Kolkata')
GENERATED = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def window(season_type='aadi', year=2026):
    start = datetime(2026, 6, 30, 5, 27, tzinfo=IST)
    duration = 432 if season_type == 'aadi' else 264
    event = LunarEvent(
        event_type='full_moon',
        event_datetime_utc=start.astimezone(timezone.utc),
        event_datetime_local=start,
        source='test',
        calculation_version='test-1',
    )
    return KaruvottamWindow(
        season_type=season_type,
        season_year=year,
        start_datetime_local=start,
        end_datetime_local=start + timedelta(hours=duration),
        duration_hours=duration,
        trigger_event=event,
        sunrise=None,
        rule_version='2.0',
    )


def available_score():
    return ResearchScore(
        status='available',
        score=73.5,
        maximum_score=100.0,
        model_version='research-index-1.0',
        label='experimental_research_index_not_probability',
        quality_flag='valid',
        reason_codes=(),
        components=(),
    )


@pytest.mark.parametrize(
    ('season_type', 'basis_end', 'expected_start', 'expected_end', 'days'),
    [
        (
            'aadi',
            datetime(2026, 12, 20, 6, 22, tzinfo=IST),
            datetime(2026, 12, 21).date(),
            datetime(2027, 6, 18).date(),
            180,
        ),
        (
            'margazhi',
            datetime(2027, 7, 22, 5, 27, tzinfo=IST),
            datetime(2027, 7, 23).date(),
            datetime(2027, 12, 9).date(),
            140,
        ),
    ],
)
def test_exact_inclusive_period_and_traceability(
    season_type, basis_end, expected_start, expected_end, days
):
    timeline = ForecastTimelineEngine(IST).generate(
        window(season_type),
        mapping_basis_end_local=basis_end,
        research_score=available_score(),
        generated_at=GENERATED,
    )

    assert timeline.prediction_start == expected_start
    assert timeline.prediction_end == expected_end
    assert timeline.total_days == days
    assert len(timeline.entries) == days
    assert timeline.entries[0].day_number == 1
    assert timeline.entries[-1].day_number == days
    assert timeline.entries[0].source_window_key == f'{season_type}:2026:2.0'
    assert timeline.entries[0].rule_version == '2.0'
    assert timeline.entries[0].timeline_model_version == TIMELINE_MODEL_VERSION
    assert timeline.entries[0].prediction_method == PREDICTION_METHOD
    assert timeline.entries[0].generated_at == GENERATED.astimezone(IST)


def test_available_index_never_becomes_probability_amount_or_category():
    timeline = ForecastTimelineEngine(IST).generate(
        window(),
        mapping_basis_end_local=datetime(2026, 12, 20, tzinfo=IST),
        research_score=available_score(),
        generated_at=GENERATED,
    )

    entry = timeline.entries[0]
    assert entry.status == 'experimental'
    assert entry.research_score == 73.5
    assert entry.rain_probability_pct is None
    assert entry.predicted_rain_mm is None
    assert entry.rain_category is None
    assert entry.reason_codes == ('rain_amount_model_not_defined',)


def test_missing_input_produces_no_data_for_every_target_date():
    timeline = ForecastTimelineEngine(IST).generate(
        window(),
        mapping_basis_end_local=datetime(2026, 12, 20, tzinfo=IST),
        research_score=unavailable_research_score('observation_data_not_loaded'),
        generated_at=GENERATED,
    )

    assert timeline.status == 'no_data'
    assert all(entry.status == 'no_data' for entry in timeline.entries)
    assert all(entry.research_score is None for entry in timeline.entries)
    assert all(
        entry.reason_codes == ('observation_data_not_loaded',)
        for entry in timeline.entries
    )


@pytest.mark.parametrize('field', ['basis', 'generated'])
def test_naive_timestamps_are_rejected(field):
    basis = datetime(2026, 12, 20, tzinfo=IST)
    generated = GENERATED
    if field == 'basis':
        basis = basis.replace(tzinfo=None)
    else:
        generated = generated.replace(tzinfo=None)

    with pytest.raises(ValueError, match='timezone-aware'):
        ForecastTimelineEngine(IST).generate(
            window(),
            mapping_basis_end_local=basis,
            research_score=available_score(),
            generated_at=generated,
        )


def test_blank_no_data_reason_is_rejected():
    with pytest.raises(ValueError, match='must not be blank'):
        unavailable_research_score('')
