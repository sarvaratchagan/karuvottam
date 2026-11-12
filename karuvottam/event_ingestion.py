"""NOAA IBTrACS v04r01 North Indian Ocean track ingestion."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from config import settings
from karuvottam.data_access import DataAccess, DuplicateRecordError
from karuvottam.event_model import EventAdvisory, EventTrackPoint


LOGGER = logging.getLogger(__name__)
BASE_URL = ('https://www.ncei.noaa.gov/data/'
            'international-best-track-archive-for-climate-stewardship-ibtracs/'
            'v04r01/access/csv/')
DATASETS = {
    'ni': BASE_URL + 'ibtracs.NI.list.v04r01.csv',
    'active': BASE_URL + 'ibtracs.ACTIVE.list.v04r01.csv',
}
SOURCE = 'noaa:ibtracs:v04r01'
GRADE_TYPES = {
    'LPA': 'lpa', 'D': 'depression', 'DD': 'deep_depression',
    'CS': 'cyclone', 'SCS': 'cyclone', 'VSCS': 'cyclone',
    'ESCS': 'cyclone', 'SUCS': 'cyclone',
}
USA_TYPES = {
    'TD': 'depression', 'TS': 'cyclone',
    'TC': 'cyclone', 'HU': 'cyclone', 'HR': 'cyclone',
    'TY': 'cyclone', 'ST': 'cyclone',
}


@dataclass(frozen=True)
class ImportReport:
    dataset: str
    sha256: str
    rows_seen: int
    rows_imported: int
    rows_existing: int
    rows_skipped: int
    retrieved_at_utc: str
    missing_points: int = 0


def _timestamp(value: str) -> datetime:
    return datetime.strptime(value.strip(), '%Y-%m-%d %H:%M:%S').replace(
        tzinfo=timezone.utc
    )


def _number(value: str | None) -> float | None:
    return float(value.strip()) if value and value.strip() else None


def _classification(row: dict[str, str]) -> tuple[str, str] | None:
    grade = row.get('NEWDELHI_GRADE', '').strip()
    if grade:
        normalized = GRADE_TYPES.get(grade.upper())
        return (grade, normalized) if normalized else None
    status = row.get('USA_STATUS', '').strip()
    normalized = USA_TYPES.get(status.upper())
    return (status, normalized) if normalized else None


def import_ibtracs_csv(
    payload: bytes, data_access: DataAccess, *, dataset: str,
    source_url: str, retrieved_at: datetime,
    start_year: int | None = None, end_year: int | None = None,
) -> ImportReport:
    """Import supported NI observations, preserving raw source labels and updates."""
    if dataset not in DATASETS or source_url != DATASETS[dataset]:
        raise ValueError('dataset and source URL must be an approved IBTrACS pair')
    if retrieved_at.tzinfo is None:
        raise ValueError('retrieved_at must be timezone-aware')
    digest = hashlib.sha256(payload).hexdigest()
    try:
        stream = io.StringIO(payload.decode('utf-8-sig'), newline='')
    except UnicodeDecodeError as exc:
        raise ValueError('IBTrACS CSV must be UTF-8') from exc
    reader = csv.DictReader(stream)
    required = {'SID', 'BASIN', 'ISO_TIME', 'LAT', 'LON', 'TRACK_TYPE',
                'NEWDELHI_GRADE', 'USA_STATUS'}
    if not required.issubset(reader.fieldnames or ()):
        raise ValueError('IBTrACS CSV is missing required columns')
    seen = imported = existing = skipped = missing_points = 0
    with data_access.transaction() as work:
        for row in reader:
            seen += 1
            if row['SID'].strip() == '' or row['BASIN'].strip() != 'NI':
                skipped += 1
                continue
            if row['TRACK_TYPE'].strip().upper() not in {
                'MAIN', 'PROVISIONAL', 'US-PROVISIONAL'
            }:
                skipped += 1
                continue
            classification = _classification(row)
            if classification is None:
                skipped += 1
                continue
            if not row['LAT'].strip() or not row['LON'].strip():
                missing_points += 1
                skipped += 1
                continue
            issued = _timestamp(row['ISO_TIME'])
            if (start_year is not None and issued.year < start_year) or (
                end_year is not None and issued.year > end_year
            ):
                skipped += 1
                continue
            label, event_type = classification
            latitude, longitude = float(row['LAT']), float(row['LON'])
            grade = row.get('NEWDELHI_GRADE', '').strip()
            wind_knots = _number(
                row.get('NEWDELHI_WIND') if grade else row.get('USA_WIND')
            )
            pressure = _number(
                row.get('NEWDELHI_PRES') if grade else row.get('USA_PRES')
            )
            quality = (
                'provisional' if 'PROVISIONAL' in row['TRACK_TYPE'].upper()
                else 'historical_best_track'
            )
            advisory = EventAdvisory(
                source=SOURCE, event_key=row['SID'].strip(),
                event_type=event_type, provider_classification=label,
                issued_at=issued, retrieved_at=max(retrieved_at, issued),
                quality_flag=quality,
                source_reference=f"IBTrACS SID {row['SID'].strip()}",
                source_url=source_url,
                classification_basis='provider_category',
                classification_rule_version='ibtracs-newdelhi-usa-status-v1',
                intensity=label,
                center_latitude=latitude, center_longitude=longitude,
                central_pressure_hpa=pressure,
                maximum_wind_kmh=(wind_knots * 1.852 if wind_knots is not None else None),
            )
            try:
                stored, created = work.weather_events.record_advisory(advisory)
            except DuplicateRecordError:
                LOGGER.error(
                    'IBTrACS conflicting bulletin sid=%s issued_at=%s',
                    row['SID'].strip(), issued.isoformat(),
                )
                raise
            work.weather_events.record_point(
                stored.id,
                EventTrackPoint(
                    valid_at=issued, latitude=latitude, longitude=longitude,
                    point_type='observed', source=SOURCE,
                    quality_flag=quality, issued_at=issued,
                ),
            )
            imported += int(created)
            existing += int(not created)
    LOGGER.info(
        'IBTrACS import dataset=%s rows=%s inserted=%s existing=%s skipped=%s missing_points=%s sha256=%s',
        dataset, seen, imported, existing, skipped, missing_points, digest,
    )
    return ImportReport(
        dataset, digest, seen, imported, existing, skipped,
        retrieved_at.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        missing_points,
    )


def fetch_dataset(dataset: str, archive_dir: Path) -> bytes:
    """Fetch a fixed NOAA URL and retain the exact response by checksum."""
    if dataset not in DATASETS:
        raise ValueError('unsupported IBTrACS dataset')
    request = Request(DATASETS[dataset], headers={'User-Agent': 'karuvottam/1.0 research'})
    try:
        with urlopen(request, timeout=60) as response:
            payload = response.read(40 * 1024 * 1024 + 1)
    except (OSError, URLError) as exc:
        LOGGER.error('IBTrACS download failed dataset=%s error_type=%s', dataset, type(exc).__name__)
        raise RuntimeError(f'IBTrACS {dataset} download failed') from exc
    if len(payload) > 40 * 1024 * 1024:
        raise ValueError('IBTrACS response exceeds 40 MiB')
    archive_payload(payload, dataset, archive_dir)
    return payload


def archive_payload(payload: bytes, dataset: str, archive_dir: Path) -> Path:
    """Keep the exact received CSV for replay and provenance checks."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    archive = archive_dir / f'ibtracs-{dataset}-{digest[:16]}.csv'
    if not archive.exists():
        archive.write_bytes(payload)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description='Import NOAA IBTrACS North Indian Ocean tracks')
    parser.add_argument('--dataset', choices=tuple(DATASETS), required=True)
    parser.add_argument('--file', type=Path, help='existing official CSV; otherwise download')
    parser.add_argument(
        '--retrieved-at', help='actual UTC ISO-8601 download time; required with --file'
    )
    parser.add_argument('--start-year', type=int)
    parser.add_argument('--end-year', type=int)
    parser.add_argument('--database', type=Path, default=settings.database_path)
    args = parser.parse_args()
    if args.start_year and args.end_year and args.end_year < args.start_year:
        parser.error('end-year must not precede start-year')
    if args.file and not args.retrieved_at:
        parser.error('--retrieved-at is required when replaying --file')
    if args.retrieved_at:
        try:
            retrieved_at = datetime.fromisoformat(
                args.retrieved_at.replace('Z', '+00:00')
            )
            if retrieved_at.tzinfo is None:
                raise ValueError
        except ValueError:
            parser.error('--retrieved-at must be a timezone-aware ISO-8601 timestamp')
    else:
        retrieved_at = datetime.now(timezone.utc)
    archive_dir = Path('data/imports/events')
    payload = (
        args.file.read_bytes() if args.file else
        fetch_dataset(args.dataset, archive_dir)
    )
    archive_payload(payload, args.dataset, archive_dir)
    report = import_ibtracs_csv(
        payload, DataAccess(args.database), dataset=args.dataset,
        source_url=DATASETS[args.dataset], retrieved_at=retrieved_at,
        start_year=args.start_year, end_year=args.end_year,
    )
    print(report)


if __name__ == '__main__':
    main()
