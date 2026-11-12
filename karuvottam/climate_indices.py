"""NOAA PSL DMI and CPC ONI seasonal-context ingestion."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

from config import settings
from karuvottam.data_access import DataAccess


LOGGER = logging.getLogger(__name__)
SOURCES = {
    'dmi': (
        'https://psl.noaa.gov/data/timeseries/month/data/dmi.had.long.csv',
        'iod_dmi', 'NOAA PSL', 'hadisst1.1-dmi-monthly',
    ),
    'oni': (
        'https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/oni/v6/',
        'enso_oni', 'NOAA CPC', 'ersstv6-oni-v6',
    ),
}
SEASONS = ('DJF', 'JFM', 'FMA', 'MAM', 'AMJ', 'MJJ',
           'JJA', 'JAS', 'ASO', 'SON', 'OND', 'NDJ')


@dataclass(frozen=True)
class ClimateSample:
    period_start: date
    period_end: date
    value: float
    classification: str
    quality_flag: str


@dataclass(frozen=True)
class ClimateImportReport:
    source: str
    sha256: str
    samples: int
    inserted: int
    existing: int
    latest_period_end: str
    issue_time_basis: str


def _month_end(year: int, month: int) -> date:
    return date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


def parse_dmi(payload: bytes) -> tuple[ClimateSample, ...]:
    try:
        reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
        if not reader.fieldnames or reader.fieldnames[0] != 'Date':
            raise ValueError('DMI CSV header changed')
        value_column = reader.fieldnames[1]
        samples = []
        for row in reader:
            start = date.fromisoformat(row['Date'].strip())
            if start.day != 1:
                raise ValueError('DMI period must start on day one')
            value = float(row[value_column].strip())
            if not math.isfinite(value):
                raise ValueError('DMI value must be finite')
            if value <= -9999:
                continue
            samples.append(ClimateSample(
                start, _month_end(start.year, start.month), value,
                'positive_dmi' if value > 0 else 'negative_dmi' if value < 0 else 'zero_dmi',
                'source_reported',
            ))
    except (UnicodeDecodeError, KeyError, IndexError, TypeError) as exc:
        raise ValueError('invalid DMI CSV') from exc
    if not samples:
        raise ValueError('DMI CSV contains no usable values')
    return tuple(samples)


class _TableRows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == 'tr':
            self._row = []
        elif tag in ('td', 'th') and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ('td', 'th') and self._cell is not None and self._row is not None:
            self._row.append(''.join(self._cell).strip())
            self._cell = None
        elif tag == 'tr' and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_oni(payload: bytes) -> tuple[ClimateSample, ...]:
    try:
        html = payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('ONI page must be UTF-8') from exc
    if 'ERSSTv6' not in html and 'ERSST.v6' not in html:
        raise ValueError('ONI page no longer identifies ERSSTv6')
    parser = _TableRows()
    parser.feed(html)
    samples = []
    for row in parser.rows:
        if len(row) < 2 or len(row[0]) != 4 or not row[0].isdigit():
            continue
        year = int(row[0])
        if not 1950 <= year <= 2100:
            continue
        for offset, raw in enumerate(row[1:13]):
            try:
                value = float(raw)
            except ValueError:
                continue
            if not math.isfinite(value):
                raise ValueError('ONI value must be finite')
            start_month = 12 if offset == 0 else offset
            start_year = year - 1 if offset == 0 else year
            end_month = 2 if offset == 0 else (offset + 2 - 1) % 12 + 1
            end_year = start_year + (start_month + 2 > 12)
            samples.append(ClimateSample(
                date(start_year, start_month, 1), _month_end(end_year, end_month),
                value,
                'warm_oni_band' if value >= 0.5 else
                'cold_oni_band' if value <= -0.5 else 'neutral_oni_band',
                'source_reported',
            ))
    if not samples:
        raise ValueError('ONI page contains no seasonal values')
    samples.sort(key=lambda item: item.period_end)
    # CPC warns the newest ONI values may be revised after initial publication.
    return tuple(
        ClimateSample(
            sample.period_start, sample.period_end, sample.value,
            sample.classification,
            'recent_estimate' if index >= len(samples) - 2 else sample.quality_flag,
        )
        for index, sample in enumerate(samples)
    )


def archive_payload(payload: bytes, source: str, directory: Path) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    extension = 'csv' if source == 'dmi' else 'html'
    path = directory / f'{source}-{digest[:16]}.{extension}'
    if not path.exists():
        path.write_bytes(payload)
    return path


def fetch_source(source: str) -> tuple[bytes, datetime, datetime, str]:
    if source not in SOURCES:
        raise ValueError('unsupported climate index source')
    request = Request(SOURCES[source][0], headers={'User-Agent': 'karuvottam/1.0 research'})
    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read(3 * 1024 * 1024 + 1)
            modified = response.headers.get('Last-Modified')
    except OSError as exc:
        LOGGER.error('Climate source download failed source=%s error_type=%s', source, type(exc).__name__)
        raise RuntimeError(f'{source} download failed') from exc
    if len(payload) > 3 * 1024 * 1024:
        raise ValueError('climate source response exceeds 3 MiB')
    retrieved = datetime.now(timezone.utc)
    issued = parsedate_to_datetime(modified) if modified else retrieved
    basis = 'http_last_modified' if modified else 'retrieval_proxy'
    return payload, issued, retrieved, basis


def import_climate_index(
    payload: bytes, access: DataAccess, *, source: str,
    issued_at: datetime, retrieved_at: datetime, issue_time_basis: str,
) -> ClimateImportReport:
    if source not in SOURCES:
        raise ValueError('unsupported climate index source')
    if issue_time_basis not in ('http_last_modified', 'retrieval_proxy'):
        raise ValueError('unsupported issue time basis')
    url, index_type, provider, version = SOURCES[source]
    samples = parse_dmi(payload) if source == 'dmi' else parse_oni(payload)
    digest = hashlib.sha256(payload).hexdigest()
    inserted = existing = 0
    with access.transaction() as work:
        if work.climate_indices.has_digest(index_type, digest):
            existing = len(samples)
        else:
            for sample in samples:
                _, created = work.climate_indices.record(
                    index_type=index_type, index_value=sample.value,
                    classification=sample.classification,
                    period_start=sample.period_start, period_end=sample.period_end,
                    issued_at=issued_at, retrieved_at=retrieved_at,
                    provider=provider, data_version=version,
                    quality_flag=sample.quality_flag, source_url=url,
                    source_sha256=digest, issue_time_basis=issue_time_basis,
                )
                inserted += int(created)
                existing += int(not created)
    LOGGER.info(
        'Climate import source=%s inserted=%s existing=%s sha256=%s',
        source, inserted, existing, digest,
    )
    return ClimateImportReport(
        source, digest, len(samples), inserted, existing,
        max(sample.period_end for sample in samples).isoformat(), issue_time_basis,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Import NOAA DMI and ONI seasonal context')
    parser.add_argument('--source', choices=tuple(SOURCES), required=True)
    parser.add_argument('--file', type=Path)
    parser.add_argument('--issued-at', help='UTC ISO-8601 source timestamp; required with --file')
    parser.add_argument('--retrieved-at', help='UTC ISO-8601 download time; required with --file')
    parser.add_argument('--issue-time-basis', choices=('http_last_modified', 'retrieval_proxy'))
    parser.add_argument('--database', type=Path, default=settings.database_path)
    args = parser.parse_args()
    if args.file:
        if not (args.issued_at and args.retrieved_at and args.issue_time_basis):
            parser.error('--file requires --issued-at, --retrieved-at and --issue-time-basis')
        try:
            issued = datetime.fromisoformat(args.issued_at.replace('Z', '+00:00'))
            retrieved = datetime.fromisoformat(args.retrieved_at.replace('Z', '+00:00'))
            if issued.tzinfo is None or retrieved.tzinfo is None:
                raise ValueError
        except ValueError:
            parser.error('issue and retrieval times must be timezone-aware ISO-8601')
        payload, basis = args.file.read_bytes(), args.issue_time_basis
    else:
        payload, issued, retrieved, basis = fetch_source(args.source)
    archive_payload(payload, args.source, Path('data/imports/climate'))
    print(import_climate_index(
        payload, DataAccess(args.database), source=args.source,
        issued_at=issued, retrieved_at=retrieved, issue_time_basis=basis,
    ))


if __name__ == '__main__':
    main()
