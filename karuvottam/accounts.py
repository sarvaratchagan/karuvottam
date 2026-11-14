"""Database-backed web accounts and operator-managed role assignments."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from config import settings
from karuvottam.database import connect_database

ROLES = ('admin', 'researcher', 'viewer', 'data-maintainer')
USERNAME_PATTERN = re.compile(r'[A-Za-z0-9._-]{1,64}\Z')
HASH_PREFIX = 'scrypt-v1'


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    source: str


def validate_username(username: str) -> str:
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError('username must contain 1-64 ASCII letters, digits, dots, underscores or hyphens')
    return username


def _password_bytes(password: str | bytes) -> bytes:
    raw = password.encode('utf-8') if isinstance(password, str) else password
    if not 16 <= len(raw) <= 256:
        raise ValueError('password must be 16-256 UTF-8 bytes')
    return raw


def hash_password(password: str | bytes) -> str:
    raw = _password_bytes(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(raw, salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f'{HASH_PREFIX}${salt.hex()}${digest.hex()}'


def verify_password(password: bytes, encoded: str) -> bool:
    try:
        prefix, salt_hex, digest_hex = encoded.split('$')
        if prefix != HASH_PREFIX or len(salt_hex) != 32 or len(digest_hex) != 64:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(password, salt=salt, n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


class AccountStore:
    def __init__(self, database: Path | str):
        self.database = database

    @contextmanager
    def _connect(self):
        if str(self.database) != ':memory:' and not Path(self.database).is_file():
            raise FileNotFoundError('migrated account database is unavailable')
        db = connect_database(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def count(self) -> int:
        with self._connect() as db:
            return db.execute('SELECT count(*) FROM user_accounts').fetchone()[0]

    def list_accounts(self) -> list[dict]:
        with self._connect() as db:
            return [dict(row) for row in db.execute('''SELECT id, username, role,
                enabled, created_at, updated_at FROM user_accounts ORDER BY username''')]

    def create(self, username: str, password: str, role: str) -> int:
        validate_username(username)
        if settings.admin_username and username.lower() == settings.admin_username.lower():
            raise ValueError('username is reserved for the environment administrator')
        if role not in ROLES:
            raise ValueError('invalid role')
        encoded = hash_password(password)
        with self._connect() as db:
            try:
                cursor = db.execute('''INSERT INTO user_accounts
                    (username, password_hash, role) VALUES (?, ?, ?)''',
                    (username, encoded, role))
            except sqlite3.IntegrityError as exc:
                raise ValueError('username already exists') from exc
            return cursor.lastrowid

    def set_role(self, username: str, role: str) -> None:
        if role not in ROLES:
            raise ValueError('invalid role')
        self._update(username, 'role', role)

    def set_enabled(self, username: str, enabled: bool) -> None:
        self._update(username, 'enabled', int(enabled))

    def set_password(self, username: str, password: str) -> None:
        self._update(username, 'password_hash', hash_password(password))

    def _update(self, username: str, field: str, value: object) -> None:
        validate_username(username)
        with self._connect() as db:
            cursor = db.execute(f'''UPDATE user_accounts SET {field}=?,
                updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE username=? COLLATE NOCASE''', (value, username))
            if cursor.rowcount != 1:
                raise ValueError('account not found')

    def authenticate(self, username: bytes, password: bytes) -> Principal | None:
        try:
            name = username.decode('ascii')
            validate_username(name)
        except (UnicodeDecodeError, ValueError):
            return None
        with self._connect() as db:
            row = db.execute('''SELECT username, password_hash, role, enabled
                FROM user_accounts WHERE username=? COLLATE NOCASE''', (name,)).fetchone()
        if row is None or not verify_password(password, row['password_hash']):
            return None
        if not row['enabled']:
            return None
        return Principal(row['username'], row['role'], 'database')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=settings.database_path)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create')
    create.add_argument('username')
    create.add_argument('--role', required=True, choices=ROLES)
    for command in ('set-role', 'enable', 'disable', 'set-password'):
        action = commands.add_parser(command)
        action.add_argument('username')
        if command == 'set-role':
            action.add_argument('--role', required=True, choices=ROLES)
    commands.add_parser('list')
    args = parser.parse_args()
    store = AccountStore(args.database)
    if args.command == 'create':
        password = getpass.getpass('Password: ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('passwords do not match')
        print(store.create(args.username, password, args.role))
    elif args.command == 'set-password':
        password = getpass.getpass('New password: ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('passwords do not match')
        store.set_password(args.username, password)
    elif args.command == 'set-role':
        store.set_role(args.username, args.role)
    elif args.command in ('enable', 'disable'):
        store.set_enabled(args.username, args.command == 'enable')
    else:
        import json
        print(json.dumps(store.list_accounts(), ensure_ascii=False))


if __name__ == '__main__':
    main()
