"""Safe diagnostic logging helpers for the web application."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable


REDACTED = '[REDACTED]'
_SENSITIVE_ASSIGNMENT = re.compile(
    r'(?i)(\b(?:api[_-]?key|token|password|secret|authorization)\b)'
    r'(\s*(?:=|:)\s*)([^\s&,;]+)'
)
_BEARER_CREDENTIAL = re.compile(r'(?i)(\bBearer\s+)([^\s,;]+)')


def redact_text(value: object, secrets: Iterable[str] = ()) -> str:
    """Return printable diagnostic text with common credentials removed."""
    text = str(value)
    text = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f'{match.group(1)}{match.group(2)}{REDACTED}', text
    )
    text = _BEARER_CREDENTIAL.sub(
        lambda match: f'{match.group(1)}{REDACTED}', text
    )
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    return text


class RedactingFormatter(logging.Formatter):
    """Format records normally, then scrub messages and tracebacks."""

    def __init__(self, fmt: str, *, secrets: Iterable[str] = ()) -> None:
        super().__init__(fmt)
        self.secrets = tuple(secret for secret in secrets if secret)

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record), self.secrets)


def configure_application_logging(
    app_logger: logging.Logger,
    *,
    log_path: Path,
    level: str,
    secrets: Iterable[str] = (),
) -> RotatingFileHandler:
    """Attach one bounded, redacting file handler to app and package logs."""
    resolved_path = log_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    handler_key = str(resolved_path)
    formatter = RedactingFormatter(
        '%(asctime)s %(levelname)s %(name)s %(message)s',
        secrets=secrets,
    )

    package_logger = logging.getLogger('karuvottam')
    for logger in (app_logger, package_logger):
        existing = next(
            (
                item
                for item in logger.handlers
                if getattr(item, '_karuvottam_log_path', None) == handler_key
            ),
            None,
        )
        if existing is None:
            handler = RotatingFileHandler(
                resolved_path,
                maxBytes=2 * 1024 * 1024,
                backupCount=5,
                encoding='utf-8',
            )
            handler._karuvottam_log_path = handler_key  # type: ignore[attr-defined]
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        else:
            handler = existing
        for logger_handler in logger.handlers:
            logger_handler.setFormatter(formatter)
        logger.setLevel(level)
        logger.propagate = False

    return handler  # type: ignore[return-value]
