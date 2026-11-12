"""Reproducible historical event/rainfall association and holdout analysis."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from config import settings
from karuvottam.data_access import DataAccess, WeatherObservationRecord
from karuvottam.event_ingestion import SOURCE
from karuvottam.event_tracks import great_circle_km


VERSION = 'event-rainfall-1.0'
HOUR = timedelta(hours=1)
BANDS = ('<250', '250-499', '500-999', '1000+')


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def distance_band(distance_km: float) -> str:
    if distance_km < 250:
        return BANDS[0]
    if distance_km < 500:
        return BANDS[1]
    if distance_km < 1000:
        return BANDS[2]
    return BANDS[3]


def _hour_labels(start: datetime, end: datetime) -> tuple[datetime, ...]:
    label = start.replace(minute=0, second=0, microsecond=0)
    if label <= start:
        label += HOUR
    labels = []
    while label <= end:
        labels.append(label)
        label += HOUR
    return tuple(labels)


def _valid_rain(record: WeatherObservationRecord) -> bool:
    if (record.quality_flag != 'valid' or record.is_interpolated
            or record.precipitation_mm is None
            or record.precipitation_interval_minutes != 60
            or not record.precipitation_interval_start_utc
            or not record.precipitation_interval_end_utc):
        return False
    end = _time(record.precipitation_interval_end_utc)
    start = _time(record.precipitation_interval_start_utc)
    return end == _time(record.observed_at_utc) and end - start == HOUR


@dataclass(frozen=True)
class RainWindow:
    expected_hours: int
    valid_hours: int
    rain_mm: float | None
    rain_mm_per_24h: float | None
    raw_references: tuple[str, ...]


def _rain_window(work, location_id: int, source: str,
                 start: datetime, end: datetime) -> RainWindow:
    labels = _hour_labels(start, end)
    if not labels:
        return RainWindow(0, 0, None, None, ())
    records = work.weather_observations.list_between(
        location_id, labels[0], labels[-1], source=source,
    )
    accepted = {
        _time(record.observed_at_utc): record for record in records
        if _valid_rain(record)
    }
    valid = [accepted[label] for label in labels if label in accepted]
    complete = len(valid) == len(labels)
    total = round(sum(record.precipitation_mm for record in valid), 2) if complete else None
    return RainWindow(
        len(labels), len(valid), total,
        round(total * 24 / len(labels), 2) if complete else None,
        tuple(sorted({record.raw_payload_reference for record in valid
                      if record.raw_payload_reference})),
    )


@dataclass(frozen=True)
class EventRainRow:
    event_key: str
    event_year: int
    first_at_utc: str
    last_at_utc: str
    event_type: str
    event_source: str
    event_source_url: str
    event_source_reference: str
    event_retrieved_at_utc: str
    event_quality_flags: str
    first_distance_km: float
    first_distance_band: str
    minimum_distance_km: float
    minimum_distance_band: str
    weather_source: str
    weather_raw_references: str
    pre_expected_hours: int
    pre_valid_hours: int
    pre_rain_mm: float | None
    during_expected_hours: int
    during_valid_hours: int
    during_rain_mm: float | None
    during_rain_mm_per_24h: float | None
    post_expected_hours: int
    post_valid_hours: int
    post_rain_mm: float | None
    quality: str


def build_rows(
    access: DataAccess, *, start_year: int, end_year: int,
    location_name: str, latitude: float, longitude: float,
    timezone_name: str, weather_source: str = 'open-meteo:era5',
) -> tuple[EventRainRow, ...]:
    if end_year < start_year:
        raise ValueError('end_year must not precede start_year')
    with access.transaction() as work:
        location = next((item for item in work.locations.list_active()
                         if item.name == location_name
                         and abs(item.latitude - latitude) < 0.000001
                         and abs(item.longitude - longitude) < 0.000001
                         and item.timezone_name == timezone_name), None)
        if location is None:
            raise ValueError('configured active target location is missing')
        rows = []
        for key in work.weather_events.event_keys_in_years(SOURCE, start_year, end_year):
            history = work.weather_events.history(SOURCE, key)
            observed = {}
            for advisory in history:
                for point in work.weather_events.points(advisory.id):
                    if point.point_type == 'observed':
                        observed[point.valid_at] = point
            points = sorted(observed.values(), key=lambda point: point.valid_at)
            if not points:
                continue
            first, last = _time(points[0].valid_at), _time(points[-1].valid_at)
            pre = _rain_window(work, location.id, weather_source, first-timedelta(hours=24), first)
            during = _rain_window(work, location.id, weather_source, first, last)
            post = _rain_window(work, location.id, weather_source, last, last+timedelta(hours=24))
            distances = [great_circle_km(point.latitude, point.longitude,
                                         latitude, longitude) for point in points]
            refs = sorted(set(pre.raw_references + during.raw_references + post.raw_references))
            complete = all(window.rain_mm is not None for window in (pre, during, post))
            rows.append(EventRainRow(
                event_key=key, event_year=first.year,
                first_at_utc=first.isoformat(), last_at_utc=last.isoformat(),
                event_type=history[-1].event_type, event_source=SOURCE,
                event_source_url=history[-1].source_url or '',
                event_source_reference=history[-1].source_reference or '',
                event_retrieved_at_utc=history[-1].retrieved_at,
                event_quality_flags=';'.join(sorted({row.quality_flag for row in history})),
                first_distance_km=round(distances[0], 1),
                first_distance_band=distance_band(distances[0]),
                minimum_distance_km=round(min(distances), 1),
                minimum_distance_band=distance_band(min(distances)),
                weather_source=weather_source, weather_raw_references=';'.join(refs),
                pre_expected_hours=pre.expected_hours, pre_valid_hours=pre.valid_hours,
                pre_rain_mm=pre.rain_mm,
                during_expected_hours=during.expected_hours,
                during_valid_hours=during.valid_hours,
                during_rain_mm=during.rain_mm,
                during_rain_mm_per_24h=during.rain_mm_per_24h,
                post_expected_hours=post.expected_hours, post_valid_hours=post.valid_hours,
                post_rain_mm=post.rain_mm,
                quality='complete' if complete else 'incomplete',
            ))
    return tuple(rows)


def band_summary(rows: tuple[EventRainRow, ...]) -> list[dict]:
    grouped = defaultdict(list)
    for row in rows:
        if row.quality == 'complete':
            grouped[row.minimum_distance_band].append(row)
    return [
        {
            'minimum_distance_band_km': band,
            'complete_events': len(grouped[band]),
            'mean_pre_mm_per_24h': round(mean(r.pre_rain_mm for r in grouped[band]), 2)
            if grouped[band] else None,
            'mean_during_mm_per_24h': round(mean(r.during_rain_mm_per_24h for r in grouped[band]), 2)
            if grouped[band] else None,
            'mean_post_mm_per_24h': round(mean(r.post_rain_mm for r in grouped[band]), 2)
            if grouped[band] else None,
        }
        for band in BANDS
    ]


def holdout_evaluation(rows: tuple[EventRainRow, ...]) -> dict:
    """Evaluate a first-position-only band mean against a training mean."""
    complete = [row for row in rows if row.quality == 'complete']
    years = sorted({row.event_year for row in complete})
    if len(years) < 2:
        return {'status': 'insufficient_years', 'train_events': 0, 'test_events': 0}
    split_year = years[max(1, int(len(years) * .7))]
    cutoff = datetime(split_year, 1, 1, tzinfo=timezone.utc)
    train = [row for row in complete if row.event_year < split_year
             and _time(row.last_at_utc) + timedelta(hours=24) < cutoff]
    test = [row for row in complete if row.event_year >= split_year]
    result = {'status': 'insufficient_events', 'split_year': split_year,
              'train_events': len(train), 'test_events': len(test),
              'feature': 'first_observed_position_distance_band',
              'outcome': 'during_event_rain_mm_per_24h'}
    if len(train) < 5 or len(test) < 2:
        return result
    baseline = mean(row.during_rain_mm_per_24h for row in train)
    grouped = defaultdict(list)
    for row in train:
        grouped[row.first_distance_band].append(row.during_rain_mm_per_24h)
    band_means = {band: mean(values) for band, values in grouped.items()}
    result.update({
        'status': 'evaluated',
        'baseline_mae_mm_per_24h': round(mean(abs(row.during_rain_mm_per_24h-baseline)
                                               for row in test), 2),
        'band_model_mae_mm_per_24h': round(mean(abs(
            row.during_rain_mm_per_24h-band_means.get(row.first_distance_band, baseline)
        ) for row in test), 2),
        'training_band_counts': {band: len(grouped[band]) for band in BANDS},
    })
    return result


def export(rows: tuple[EventRainRow, ...], output: Path, *, start_year: int,
           end_year: int, location_name: str, latitude: float, longitude: float) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / 'event_rainfall.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(EventRainRow.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    summary = {'version': VERSION, 'location': {'name': location_name,
               'latitude': latitude, 'longitude': longitude},
               'years': [start_year, end_year], 'event_source': SOURCE,
               'weather_sources': sorted({row.weather_source for row in rows}),
               'event_count': len(rows),
               'complete_event_count': sum(row.quality == 'complete' for row in rows),
               'bands': band_summary(rows), 'holdout': holdout_evaluation(rows),
               'csv_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest()}
    (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False,
                                             indent=2) + '\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year', type=int, default=2015)
    parser.add_argument('--end-year', type=int, default=2024)
    parser.add_argument('--weather-source', default='open-meteo:era5')
    parser.add_argument('--database', type=Path, default=settings.database_path)
    parser.add_argument('--output', type=Path,
                        default=Path('data/exports/event-rainfall-2015-2024'))
    args = parser.parse_args()
    rows = build_rows(DataAccess(args.database), start_year=args.start_year,
                      end_year=args.end_year, location_name=settings.location_name,
                      latitude=settings.latitude, longitude=settings.longitude,
                      timezone_name=settings.timezone_name,
                      weather_source=args.weather_source)
    summary = export(rows, args.output, start_year=args.start_year,
                     end_year=args.end_year, location_name=settings.location_name,
                     latitude=settings.latitude, longitude=settings.longitude)
    print(json.dumps({'event_count': summary['event_count'],
                      'complete_event_count': summary['complete_event_count'],
                      'holdout': summary['holdout'], 'output': str(args.output)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
