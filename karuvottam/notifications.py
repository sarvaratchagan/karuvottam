"""Opt-in source-health notifications with a durable, retryable outbox."""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import urllib.request
from urllib.parse import urlsplit
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from config import settings
from karuvottam.database import connect_database
from karuvottam.event_monitor import DEFAULT_STATE, MonitorStore, SOURCES_TO_POLL

EVENT_KINDS = ('source_health', 'source_recovery')
CHANNELS = ('email', 'message')


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('time must be timezone aware')
    return value.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _email(value: str) -> str:
    value = value.strip()
    name, address = parseaddr(value)
    if (name or address != value or len(value) > 254 or
            not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value)):
        raise ValueError('a single valid email address is required')
    return value


class NotificationStore:
    def __init__(self, database: Path | str):
        self.database = database

    @contextmanager
    def _connect(self):
        db = connect_database(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add_rule(self, event_kind: str, source: str, channel: str,
                 destination: str | None = None) -> int:
        if event_kind not in EVENT_KINDS or source not in (*SOURCES_TO_POLL, 'all'):
            raise ValueError('invalid event or source')
        if channel not in CHANNELS:
            raise ValueError('invalid channel')
        if channel == 'email':
            destination = _email(destination or '')
        elif destination is not None:
            raise ValueError('message destination comes from KARUVOTTAM_MESSAGE_WEBHOOK_URL')
        else:
            destination = 'configured_webhook'
        with self._connect() as db:
            db.execute('''INSERT INTO notification_rules
                (event_kind, source, channel, destination) VALUES (?, ?, ?, ?)
                ON CONFLICT(event_kind, source, channel, destination)
                DO UPDATE SET enabled=1''', (event_kind, source, channel, destination))
            row = db.execute('''SELECT id FROM notification_rules WHERE
                event_kind=? AND source=? AND channel=? AND destination=?''',
                (event_kind, source, channel, destination)).fetchone()
            return row['id']

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> None:
        with self._connect() as db:
            changed = db.execute('UPDATE notification_rules SET enabled=? WHERE id=?',
                                 (int(enabled), rule_id)).rowcount
            if not changed:
                raise ValueError('rule not found')

    def rules(self) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                'SELECT * FROM notification_rules ORDER BY id')]

    def deliveries(self, limit: int = 50) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute('''SELECT d.*, r.channel,
                r.destination FROM notification_deliveries d
                JOIN notification_rules r ON r.id=d.rule_id
                ORDER BY d.id DESC LIMIT ?''', (limit,))]

    def scan(self, monitor: MonitorStore, *, now: datetime | None = None) -> int:
        """Queue once per source-health transition; initial healthy state is silent."""
        current = now or utc_now()
        created = 0
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for item in monitor.statuses(now=current):
                previous = db.execute(
                    'SELECT health, changed_at FROM notification_source_state WHERE source=?',
                    (item.source,)).fetchone()
                changed = previous is None or previous['health'] != item.health
                changed_at = stamp(current) if changed else previous['changed_at']
                if changed:
                    db.execute('''INSERT INTO notification_source_state(source, health, changed_at)
                        VALUES (?, ?, ?) ON CONFLICT(source) DO UPDATE SET
                        health=excluded.health, changed_at=excluded.changed_at''',
                        (item.source, item.health, changed_at))
                if item.health == 'ok' and previous is None:
                    continue
                if item.health == 'ok' and not changed:
                    continue
                event_kind = 'source_recovery' if item.health == 'ok' else 'source_health'
                subject = f'Karuvottam source {item.source}: {item.health}'
                body = (f'Source: {item.source}\nHealth: {item.health}\n'
                        f'Checked at (UTC): {stamp(current)}\n'
                        f'Last success (UTC): {item.last_success_at or "none"}\n'
                        f'Last error code: {item.last_error_code or "none"}\n')
                rules = db.execute('''SELECT id FROM notification_rules WHERE enabled=1
                    AND event_kind=? AND source IN (?, 'all')''',
                    (event_kind, item.source)).fetchall()
                for rule in rules:
                    cursor = db.execute('''INSERT OR IGNORE INTO notification_deliveries
                        (rule_id, source, event_kind, health, subject, body,
                         next_attempt_at, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (rule['id'], item.source, event_kind, item.health,
                         subject, body, stamp(current), changed_at))
                    created += cursor.rowcount
        return created

    def retry(self, delivery_id: int, *, now: datetime | None = None) -> None:
        with self._connect() as db:
            changed = db.execute('''UPDATE notification_deliveries SET status='pending',
                next_attempt_at=?, leased_until=NULL WHERE id=? AND status='failed' ''',
                (stamp(now or utc_now()), delivery_id)).rowcount
            if not changed:
                raise ValueError('failed delivery not found')

    def claim(self, *, now: datetime | None = None) -> dict | None:
        current = now or utc_now()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT d.*, r.channel, r.destination FROM
                notification_deliveries d JOIN notification_rules r ON r.id=d.rule_id
                WHERE r.enabled=1 AND ((d.status IN ('pending','failed') AND
                d.next_attempt_at<=?) OR (d.status='sending' AND d.leased_until<=?))
                ORDER BY d.next_attempt_at, d.id LIMIT 1''',
                (stamp(current), stamp(current))).fetchone()
            if row is None:
                return None
            db.execute('''UPDATE notification_deliveries SET status='sending',
                leased_until=?, attempt_count=attempt_count+1 WHERE id=?''',
                (stamp(current + timedelta(minutes=10)), row['id']))
            return dict(row)

    def finish(self, delivery_id: int, *, error_code: str | None = None,
               now: datetime | None = None) -> None:
        current = now or utc_now()
        with self._connect() as db:
            row = db.execute('''SELECT attempt_count FROM notification_deliveries
                WHERE id=? AND status='sending' ''', (delivery_id,)).fetchone()
            if row is None:
                raise ValueError('claimed delivery not found')
            if error_code:
                delay = min(24 * 60, 5 * 2 ** min(row['attempt_count'] - 1, 9))
                db.execute('''UPDATE notification_deliveries SET status='failed',
                    last_error_code=?, leased_until=NULL, next_attempt_at=?
                    WHERE id=?''', (error_code, stamp(current + timedelta(minutes=delay)),
                                   delivery_id))
            else:
                db.execute('''UPDATE notification_deliveries SET status='sent',
                    last_error_code=NULL, leased_until=NULL, sent_at=? WHERE id=?''',
                    (stamp(current), delivery_id))


def deliver(item: dict, env: dict | None = None) -> None:
    """Send one claimed item; transport configuration stays outside the database."""
    env = os.environ if env is None else env
    if item['channel'] == 'email':
        host = env.get('KARUVOTTAM_SMTP_HOST', '').strip()
        sender = _email(env.get('KARUVOTTAM_SMTP_FROM', ''))
        if not host:
            raise ValueError('SMTP host is not configured')
        port = int(env.get('KARUVOTTAM_SMTP_PORT', '587'))
        if not 1 <= port <= 65535:
            raise ValueError('invalid SMTP port')
        message = EmailMessage()
        message['From'] = sender
        message['To'] = _email(item['destination'])
        message['Subject'] = item['subject']
        message.set_content(item['body'])
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.starttls()
            username = env.get('KARUVOTTAM_SMTP_USERNAME', '')
            if username:
                smtp.login(username, env.get('KARUVOTTAM_SMTP_PASSWORD', ''))
            smtp.send_message(message)
    else:
        url = env.get('KARUVOTTAM_MESSAGE_WEBHOOK_URL', '').strip()
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.fragment):
            raise ValueError('HTTPS message webhook is not configured')
        payload = json.dumps({'text': item['subject'] + '\n' + item['body']}).encode()
        request = urllib.request.Request(url, data=payload,
            headers={'Content-Type': 'application/json'}, method='POST')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
            if response.status >= 400:
                raise OSError('message webhook rejected delivery')


def process_due(store: NotificationStore, *, limit: int = 20,
                send=deliver, now: datetime | None = None) -> tuple[int, int]:
    sent = failed = 0
    for _ in range(limit):
        item = store.claim(now=now)
        if item is None:
            break
        try:
            send(item)
        except Exception as exc:
            store.finish(item['id'], error_code=type(exc).__name__, now=now)
            failed += 1
        else:
            store.finish(item['id'], now=now)
            sent += 1
    return sent, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=settings.database_path)
    parser.add_argument('--state', type=Path, default=DEFAULT_STATE)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add-rule')
    add.add_argument('--event', choices=EVENT_KINDS, required=True)
    add.add_argument('--source', choices=('all', *SOURCES_TO_POLL), default='all')
    add.add_argument('--channel', choices=CHANNELS, required=True)
    add.add_argument('--email')
    for name in ('enable-rule', 'disable-rule'):
        commands.add_parser(name).add_argument('id', type=int)
    commands.add_parser('list-rules')
    commands.add_parser('scan')
    commands.add_parser('send-due')
    commands.add_parser('list-deliveries')
    commands.add_parser('retry').add_argument('id', type=int)
    args = parser.parse_args()
    store = NotificationStore(args.database)
    if args.command == 'add-rule':
        print(store.add_rule(args.event, args.source, args.channel, args.email))
    elif args.command in ('enable-rule', 'disable-rule'):
        store.set_rule_enabled(args.id, args.command == 'enable-rule')
    elif args.command == 'list-rules':
        print(json.dumps(store.rules(), ensure_ascii=False))
    elif args.command == 'scan':
        print(json.dumps({'queued': store.scan(MonitorStore(args.state))}))
    elif args.command == 'send-due':
        sent, failed = process_due(store)
        print(json.dumps({'sent': sent, 'failed': failed}))
        if failed:
            raise SystemExit(1)
    elif args.command == 'list-deliveries':
        print(json.dumps(store.deliveries(), ensure_ascii=False))
    else:
        store.retry(args.id)


if __name__ == '__main__':
    main()
