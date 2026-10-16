"""Traceable daily experimental timelines derived from Karuvottam windows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from karuvottam.rain_categories import THRESHOLD_VERSION
from karuvottam.research_scoring import MODEL_VERSION as SCORE_MODEL_VERSION
from karuvottam.research_scoring import ResearchScore
from karuvottam.windows import KaruvottamWindow


TIMELINE_MODEL_VERSION = 'daily-timeline-1.0'
FORECAST_DAYS = {'aadi': 180, 'margazhi': 140}
PREDICTION_METHOD = 'window_research_index_no_amount_model'


@dataclass(frozen=True)
class ForecastEntry:
    day_number: int
    target_date: date
    target_datetime_local: datetime
    status: str
    research_score: float | None
    rain_probability_pct: float | None
    predicted_rain_mm: float | None
    rain_category: str | None
    quality_flag: str
    reason_codes: tuple[str, ...]
    source_window_key: str
    source_window_start_local: datetime
    source_window_end_local: datetime
    rule_version: str
    timeline_model_version: str
    score_model_version: str
    category_threshold_version: str
    prediction_method: str
    generated_at: datetime


@dataclass(frozen=True)
class ForecastTimeline:
    season_type: str
    season_year: int
    prediction_start: date
    prediction_end: date
    total_days: int
    status: str
    source_window_key: str
    mapping_basis_end_local: datetime
    rule_version: str
    timeline_model_version: str
    score_model_version: str
    category_threshold_version: str
    quality_flag: str
    generated_at: datetime
    entries: tuple[ForecastEntry, ...]


class ForecastTimelineEngine:
    """Build exact daily periods while preserving unavailable-data states."""

    def __init__(self, local_timezone: ZoneInfo) -> None:
        self.local_timezone = local_timezone

    def generate(
        self,
        source_window: KaruvottamWindow,
        *,
        mapping_basis_end_local: datetime,
        research_score: ResearchScore,
        generated_at: datetime,
    ) -> ForecastTimeline:
        self._validate_aware(mapping_basis_end_local, 'mapping_basis_end_local')
        self._validate_aware(generated_at, 'generated_at')
        self._validate_aware(
            source_window.start_datetime_local,
            'source_window.start_datetime_local',
        )
        self._validate_aware(
            source_window.end_datetime_local,
            'source_window.end_datetime_local',
        )
        if research_score.is_available and research_score.score is None:
            raise ValueError('available research_score must contain a score')
        try:
            total_days = FORECAST_DAYS[source_window.season_type]
        except KeyError as exc:
            raise ValueError(
                f'unsupported source season: {source_window.season_type}'
            ) from exc

        start = (
            mapping_basis_end_local.astimezone(self.local_timezone).date()
            + timedelta(days=1)
        )
        end = start + timedelta(days=total_days - 1)
        source_key = self.source_window_key(source_window)
        generated_local = generated_at.astimezone(self.local_timezone)

        if research_score.is_available:
            status = 'experimental'
            entry_reasons = ('rain_amount_model_not_defined',)
            timeline_status = 'experimental_index_only'
        else:
            status = 'no_data'
            entry_reasons = research_score.reason_codes or ('score_unavailable',)
            timeline_status = 'no_data'

        entries = tuple(
            ForecastEntry(
                day_number=offset + 1,
                target_date=target_date,
                target_datetime_local=datetime.combine(
                    target_date,
                    time.min,
                    tzinfo=self.local_timezone,
                ),
                status=status,
                research_score=(
                    research_score.score if status == 'experimental' else None
                ),
                rain_probability_pct=None,
                predicted_rain_mm=None,
                rain_category=None,
                quality_flag=research_score.quality_flag,
                reason_codes=entry_reasons,
                source_window_key=source_key,
                source_window_start_local=source_window.start_datetime_local,
                source_window_end_local=source_window.end_datetime_local,
                rule_version=source_window.rule_version,
                timeline_model_version=TIMELINE_MODEL_VERSION,
                score_model_version=research_score.model_version,
                category_threshold_version=THRESHOLD_VERSION,
                prediction_method=PREDICTION_METHOD,
                generated_at=generated_local,
            )
            for offset in range(total_days)
            for target_date in (start + timedelta(days=offset),)
        )
        return ForecastTimeline(
            season_type=source_window.season_type,
            season_year=source_window.season_year,
            prediction_start=start,
            prediction_end=end,
            total_days=total_days,
            status=timeline_status,
            source_window_key=source_key,
            mapping_basis_end_local=mapping_basis_end_local.astimezone(
                self.local_timezone
            ),
            rule_version=source_window.rule_version,
            timeline_model_version=TIMELINE_MODEL_VERSION,
            score_model_version=research_score.model_version,
            category_threshold_version=THRESHOLD_VERSION,
            quality_flag=research_score.quality_flag,
            generated_at=generated_local,
            entries=entries,
        )

    @staticmethod
    def source_window_key(window: KaruvottamWindow) -> str:
        return f'{window.season_type}:{window.season_year}:{window.rule_version}'

    @staticmethod
    def _validate_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f'{field_name} must be timezone-aware')


def unavailable_research_score(
    reason_code: str,
    *,
    model_version: str = SCORE_MODEL_VERSION,
) -> ResearchScore:
    """Construct the explicit no-input score used by application orchestration."""
    if not reason_code:
        raise ValueError('reason_code must not be blank')
    return ResearchScore(
        status='unavailable',
        score=None,
        maximum_score=100.0,
        model_version=model_version,
        label='experimental_research_index_not_probability',
        quality_flag='unavailable',
        reason_codes=(reason_code,),
        components=(),
    )
