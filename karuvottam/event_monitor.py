"""Scheduled source polling and freshness checks for Phase 8 feeds."""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from config import PROJECT_ROOT, settings
from karuvottam.climate_indices import (
    archive_payload as archive_climate, fetch_source, import_climate_index,
)
from karuvottam.data_access import DataAccess, DataAccessError, DuplicateRecordError
from karuvottam.event_ingestion import (
    DATASETS, archive_payload as archive_event, fetch_dataset,
    import_ibtracs_csv,
)
from karuvottam.error_handling import configure_application_logging


LOGGER = logging.getLogger(__name__)
SOURCES_TO_POLL = ('active', 'dmi', 'oni')
MAX_POLL_AGE = {'active': timedelta(hours=24),
                'dmi': timedelta(days=45), 'oni': timedelta(days=45)}
MAX_INDEX_PERIOD_AGE = timedelta(days=120)
STATE_VERSION = 'event-source-monitor-1.0'
DEFAULT_STATE = Path(os.environ.get(
    'KARUVOTTAM_SOURCE_MONITOR_STATE',
    PROJECT_ROOT / 'data/monitor/source_status.json',
))


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('time must be timezone-aware')
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def _error_code(exc: Exception) -> str:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, HTTPError):
            if current.code == 429:
                return 'rate_limited'
            return 'http_server_error' if current.code >= 500 else 'http_error'
        if isinstance(current, (URLError, TimeoutError, ConnectionError)):
            return 'network_error'
        current = current.__cause__
    if isinstance(exc, DuplicateRecordError):
        return 'conflicting_record'
    if isinstance(exc, DataAccessError):
        return 'database_error'
    if isinstance(exc, ValueError):
        return 'invalid_source_data'
    if isinstance(exc, OSError):
        return 'io_error'
    return 'unexpected_error'


@dataclass(frozen=True)
class SourceStatus:
    source: str
    health: str
    last_attempt_at: str | None
    last_success_at: str | None
    last_retrieved_at: str | None
    latest_period_end: str | None
    last_error_code: str | None
    last_digest: str | None
    last_usable_rows: int | None
    last_skipped_rows: int | None
    last_missing_points: int | None
    no_usable_rows: bool


class MonitorStore:
    """Atomic state file; an unsuccessful run retains the last good provenance."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != STATE_VERSION or not isinstance(data.get('sources'), dict):
                raise ValueError('invalid source monitor state')
            return data
        except FileNotFoundError:
            return {'version': STATE_VERSION, 'sources': {}}

    def record(self, source: str, *, attempted_at: datetime,
               success: dict | None = None, error_code: str | None = None) -> None:
        if source not in SOURCES_TO_POLL:
            raise ValueError('unsupported source')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.with_suffix('.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._read()
            item = state['sources'].get(source, {})
            item['last_attempt_at'] = _utc(attempted_at)
            item['last_error_code'] = error_code
            if success is not None:
                item.update(success)
                item['last_success_at'] = _utc(attempted_at)
            state['sources'][source] = item
            fd, temporary = tempfile.mkstemp(prefix='.source-status-',
                                              dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(state, stream, ensure_ascii=False, sort_keys=True, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            fcntl.flock(lock, fcntl.LOCK_UN)

    def statuses(self, *, now: datetime | None = None) -> tuple[SourceStatus, ...]:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError('now must be timezone-aware')
        try:
            state = self._read()['sources']
        except (ValueError, json.JSONDecodeError, OSError, AttributeError):
            state = None
        result = []
        for source in SOURCES_TO_POLL:
            item = state.get(source, {}) if state is not None else {}
            if not isinstance(item, dict):
                item = {}
                state = None
            success_at = item.get('last_success_at')
            error = item.get('last_error_code')
            try:
                if state is None:
                    health = 'state_unavailable'
                elif error:
                    health = 'last_attempt_failed'
                elif not success_at:
                    health = 'never_polled'
                elif source in ('dmi', 'oni') and not item.get('latest_period_end'):
                    health = 'state_unavailable'
                elif current - _parse(success_at) > MAX_POLL_AGE[source]:
                    health = 'poll_overdue'
                elif (source in ('dmi', 'oni') and item.get('latest_period_end')
                      and current.date() - date.fromisoformat(item['latest_period_end'])
                      > MAX_INDEX_PERIOD_AGE):
                    health = 'index_stale'
                else:
                    health = 'ok'
            except (ValueError, TypeError, OverflowError):
                health = 'state_unavailable'
            result.append(SourceStatus(
                source, health, item.get('last_attempt_at'), success_at,
                item.get('last_retrieved_at'), item.get('latest_period_end'),
                error, item.get('last_digest'), item.get('last_usable_rows'),
                item.get('last_skipped_rows'), item.get('last_missing_points'),
                bool(item.get('no_usable_rows')),
            ))
        return tuple(result)


def poll(source: str, access: DataAccess, store: MonitorStore, *,
         archive_root: Path = PROJECT_ROOT / 'data/imports',
         now: datetime | None = None) -> SourceStatus:
    if source not in SOURCES_TO_POLL:
        raise ValueError('unsupported source')
    attempted = now or datetime.now(timezone.utc)
    try:
        if source == 'active':
            payload = fetch_dataset('active', archive_root / 'events')
            retrieved = datetime.now(timezone.utc) if now is None else now
            archive_event(payload, 'active', archive_root / 'events')
            report = import_ibtracs_csv(
                payload, access, dataset='active', source_url=DATASETS['active'],
                retrieved_at=retrieved,
            )
            usable = report.rows_imported + report.rows_existing
            success = {
                'last_retrieved_at': _utc(retrieved),
                'last_digest': report.sha256,
                'last_usable_rows': usable,
                'last_skipped_rows': report.rows_skipped,
                'last_missing_points': report.missing_points,
                'no_usable_rows': usable == 0,
                'latest_period_end': None,
            }
            if report.rows_skipped:
                LOGGER.warning('Source rows skipped source=active count=%s',
                               report.rows_skipped)
            if report.missing_points:
                LOGGER.warning('Source points missing coordinates source=active count=%s',
                               report.missing_points)
        else:
            payload, issued, retrieved, basis = fetch_source(source)
            archive_climate(payload, source, archive_root / 'climate')
            report = import_climate_index(
                payload, access, source=source, issued_at=issued,
                retrieved_at=retrieved, issue_time_basis=basis,
            )
            success = {
                'last_retrieved_at': _utc(retrieved),
                'last_digest': report.sha256,
                'last_usable_rows': report.samples,
                'last_skipped_rows': 0,
                'last_missing_points': 0,
                'no_usable_rows': False,
                'latest_period_end': report.latest_period_end,
            }
        store.record(source, attempted_at=attempted, success=success)
        LOGGER.info('Source poll succeeded source=%s usable_rows=%s sha256=%s',
                    source, success['last_usable_rows'], success['last_digest'])
    except Exception as exc:
        code = _error_code(exc)
        LOGGER.error('Source poll failed source=%s code=%s error_type=%s',
                     source, code, type(exc).__name__)
        try:
            store.record(source, attempted_at=attempted, error_code=code)
        except (OSError, ValueError, TypeError) as state_exc:
            LOGGER.error('Source monitor state write failed source=%s error_type=%s',
                         source, type(state_exc).__name__)
            return SourceStatus(source, 'state_unavailable', _utc(attempted),
                                None, None, None, code, None, None, None, None,
                                False)
    return next(item for item in store.statuses(now=attempted) if item.source == source)


def main() -> None:
    configure_application_logging(
        LOGGER, log_path=settings.log_path, level=settings.log_level,
        secrets=(settings.weather_api_key or '', settings.admin_password or ''),
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('poll', 'check'))
    parser.add_argument('--source', choices=SOURCES_TO_POLL, action='append')
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--database', type=Path, default=settings.database_path)
    args = parser.parse_args()
    store = MonitorStore(args.state)
    if args.command == 'poll':
        selected = tuple(dict.fromkeys(args.source or SOURCES_TO_POLL))
        statuses = tuple(poll(source, DataAccess(args.database), store)
                         for source in selected)
        unhealthy = any(item.health != 'ok' for item in statuses)
    else:
        selected = tuple(dict.fromkeys(args.source or SOURCES_TO_POLL))
        statuses = tuple(item for item in store.statuses()
                         if item.source in selected)
        unhealthy = any(item.health != 'ok' for item in statuses)
    print(json.dumps([item.__dict__ for item in statuses], ensure_ascii=False))
    if unhealthy:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
