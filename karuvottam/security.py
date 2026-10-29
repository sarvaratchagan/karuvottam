"""Authentication and input-safety primitives for administration routes."""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass


MAX_AUTHORIZATION_HEADER_BYTES = 1024


@dataclass(frozen=True, repr=False)
class AdminAuthenticator:
    """Validate one environment-configured administrator using HTTP Basic auth."""

    username: str | None
    password: str | None

    @property
    def enabled(self) -> bool:
        return self.username is not None and self.password is not None

    def authenticate(self, authorization_header: str | None) -> bool:
        if not self.enabled or not authorization_header:
            return False
        if len(authorization_header.encode('utf-8')) > MAX_AUTHORIZATION_HEADER_BYTES:
            return False
        try:
            scheme, encoded = authorization_header.split(' ', maxsplit=1)
        except ValueError:
            return False
        if scheme.lower() != 'basic' or not encoded:
            return False
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            return False
        supplied_username, separator, supplied_password = decoded.partition(b':')
        if not separator:
            return False
        expected_username = self.username.encode('utf-8')
        expected_password = self.password.encode('utf-8')
        username_matches = secrets.compare_digest(
            supplied_username, expected_username
        )
        password_matches = secrets.compare_digest(
            supplied_password, expected_password
        )
        return username_matches and password_matches


def query_parameters_are_safe(
    query_string: bytes,
    parameters: list[tuple[str, list[str]]],
    *,
    max_query_bytes: int = 4096,
    max_parameters: int = 20,
    max_name_chars: int = 64,
    max_value_chars: int = 256,
) -> bool:
    """Reject abusive, ambiguous, or control-character query parameters."""
    if len(query_string) > max_query_bytes or len(parameters) > max_parameters:
        return False
    for name, values in parameters:
        if not name or len(name) > max_name_chars or len(values) != 1:
            return False
        if _contains_control_character(name):
            return False
        value = values[0]
        if len(value) > max_value_chars or _contains_control_character(value):
            return False
    return True


def _contains_control_character(value: str) -> bool:
    return any(ord(character) < 32 or ord(character) == 127 for character in value)
