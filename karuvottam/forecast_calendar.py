"""Day, week, and month read models for forecast timeline presentation."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from itertools import groupby

from karuvottam.calendar_engine import CalendarRule
from karuvottam.forecast_timeline import ForecastEntry, ForecastTimeline
from karuvottam.rain_categories import RAIN_CATEGORIES


VIEW_MODES = {'day', 'week', 'month'}
GREGORIAN_MONTHS_TAMIL = (
    'ஜனவரி',
    'பிப்ரவரி',
    'மார்ச்',
    'ஏப்ரல்',
    'மே',
    'ஜூன்',
    'ஜூலை',
    'ஆகஸ்ட்',
    'செப்டம்பர்',
    'அக்டோபர்',
    'நவம்பர்',
    'டிசம்பர்',
)
CATEGORY_LABELS = {
    definition.code: definition.label_tamil for definition in RAIN_CATEGORIES
}
STATUS_LABELS = {
    'experimental': 'ஆராய்ச்சி நிலை',
    'no_data': 'தரவு இல்லை',
    'validated': 'சரிபார்க்கப்பட்டது',
}
METHOD_LABELS = {
    'window_research_index_no_amount_model': (
        'சாளர ஆய்வு-குறியீடு · மழை அளவு மாதிரி இல்லை'
    ),
}
FORECAST_CSV_COLUMNS = (
    'day_number',
    'target_date',
    'tamil_date',
    'status',
    'research_score',
    'rain_probability_pct',
    'predicted_rain_mm',
    'rain_category',
    'quality_flag',
    'prediction_method',
    'reason_codes',
    'source_window_key',
    'source_window_start_local',
    'source_window_end_local',
    'rule_version',
    'timeline_model_version',
    'score_model_version',
    'category_threshold_version',
    'generated_at',
)


@dataclass(frozen=True)
class ForecastCalendarEntry:
    forecast: ForecastEntry
    tamil_date: str

    @property
    def category_tamil(self) -> str:
        if self.forecast.rain_category is None:
            return 'தரவு இல்லை'
        return CATEGORY_LABELS.get(
            self.forecast.rain_category,
            self.forecast.rain_category,
        )

    @property
    def status_tamil(self) -> str:
        return STATUS_LABELS.get(self.forecast.status, self.forecast.status)

    @property
    def method_tamil(self) -> str:
        return METHOD_LABELS.get(
            self.forecast.prediction_method,
            self.forecast.prediction_method,
        )


@dataclass(frozen=True)
class ForecastCalendarPeriod:
    title: str
    entries: tuple[ForecastCalendarEntry, ...]

    @property
    def start_date(self):
        return self.entries[0].forecast.target_date

    @property
    def end_date(self):
        return self.entries[-1].forecast.target_date

    @property
    def probability_display(self) -> str | None:
        values = sorted(
            {
                entry.forecast.rain_probability_pct
                for entry in self.entries
                if entry.forecast.rain_probability_pct is not None
            }
        )
        if not values:
            return None
        if len(values) == 1:
            return f'{values[0]:g}%'
        return f'{values[0]:g}%–{values[-1]:g}%'

    @property
    def categories_tamil(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                entry.category_tamil
                for entry in self.entries
                if entry.forecast.rain_category is not None
            )
        )

    @property
    def quality_flags(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(entry.forecast.quality_flag for entry in self.entries)
        )

    @property
    def statuses_tamil(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry.status_tamil for entry in self.entries))

    @property
    def methods_tamil(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry.method_tamil for entry in self.entries))

    @property
    def no_data_days(self) -> int:
        return sum(entry.forecast.status == 'no_data' for entry in self.entries)


@dataclass(frozen=True)
class ForecastCalendarView:
    mode: str
    timeline: ForecastTimeline
    entries: tuple[ForecastCalendarEntry, ...]
    periods: tuple[ForecastCalendarPeriod, ...]


class ForecastCalendarService:
    def __init__(self, calendar_rule: CalendarRule) -> None:
        self.calendar_rule = calendar_rule

    def build(
        self,
        timeline: ForecastTimeline,
        mode: str = 'day',
    ) -> ForecastCalendarView:
        if mode not in VIEW_MODES:
            raise ValueError(f'unsupported forecast calendar view: {mode}')
        entries = tuple(
            ForecastCalendarEntry(
                forecast=entry,
                tamil_date=self.calendar_rule.from_gregorian(
                    entry.target_date
                ).format_tamil(),
            )
            for entry in timeline.entries
        )
        if mode == 'day':
            periods = tuple(
                ForecastCalendarPeriod(
                    title=f'நாள் {entry.forecast.day_number}',
                    entries=(entry,),
                )
                for entry in entries
            )
        elif mode == 'week':
            periods = tuple(
                ForecastCalendarPeriod(
                    title=f'வாரம் {start // 7 + 1}',
                    entries=entries[start:start + 7],
                )
                for start in range(0, len(entries), 7)
            )
        else:
            periods = tuple(
                ForecastCalendarPeriod(
                    title=(
                        f'{GREGORIAN_MONTHS_TAMIL[month - 1]} {year}'
                    ),
                    entries=tuple(group_entries),
                )
                for (year, month), group_entries in groupby(
                    entries,
                    key=lambda item: (
                        item.forecast.target_date.year,
                        item.forecast.target_date.month,
                    ),
                )
            )
        return ForecastCalendarView(mode, timeline, entries, periods)

    def export_csv(self, timeline: ForecastTimeline) -> str:
        output = io.StringIO(newline='')
        writer = csv.DictWriter(
            output,
            fieldnames=FORECAST_CSV_COLUMNS,
            lineterminator='\n',
            extrasaction='raise',
        )
        writer.writeheader()
        for entry in timeline.entries:
            writer.writerow(self._csv_row(entry))
        return output.getvalue()

    def _csv_row(self, entry: ForecastEntry) -> dict[str, object]:
        return {
            'day_number': entry.day_number,
            'target_date': entry.target_date.isoformat(),
            'tamil_date': self.calendar_rule.from_gregorian(
                entry.target_date
            ).format_tamil(),
            'status': entry.status,
            'research_score': self._optional(entry.research_score),
            'rain_probability_pct': self._optional(
                entry.rain_probability_pct
            ),
            'predicted_rain_mm': self._optional(entry.predicted_rain_mm),
            'rain_category': entry.rain_category or '',
            'quality_flag': entry.quality_flag,
            'prediction_method': entry.prediction_method,
            'reason_codes': '|'.join(entry.reason_codes),
            'source_window_key': entry.source_window_key,
            'source_window_start_local': (
                entry.source_window_start_local.isoformat()
            ),
            'source_window_end_local': entry.source_window_end_local.isoformat(),
            'rule_version': entry.rule_version,
            'timeline_model_version': entry.timeline_model_version,
            'score_model_version': entry.score_model_version,
            'category_threshold_version': entry.category_threshold_version,
            'generated_at': entry.generated_at.isoformat(),
        }

    @staticmethod
    def _optional(value: object | None) -> object:
        return '' if value is None else value
