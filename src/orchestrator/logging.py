"""Logging configuration for the orchestrator.

Provides a consistent logger hierarchy and optional JSON formatting
for production use. All orchestrator loggers live under the
'orchestrator' namespace.

Usage:
    from orchestrator.logging import configure_logging, get_logger

    # Configure once at startup
    configure_logging(level=logging.INFO, json_format=True)

    # Get module-specific loggers
    log = get_logger("reconciler")
    log.info("starting reconciliation", extra={"planned": 12})
"""

from __future__ import annotations

import json
import logging
import sys
from typing import IO


class JsonFormatter(logging.Formatter):
    """Emit log records as JSON lines for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Merge in any extra fields passed via extra={}
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key not in (
                    "name",
                    "msg",
                    "args",
                    "created",
                    "filename",
                    "funcName",
                    "levelname",
                    "levelno",
                    "lineno",
                    "module",
                    "msecs",
                    "pathname",
                    "process",
                    "processName",
                    "relativeCreated",
                    "stack_info",
                    "exc_info",
                    "exc_text",
                    "thread",
                    "threadName",
                    "taskName",
                    "message",
                ):
                    payload[key] = value
        return json.dumps(payload)


def configure_logging(
    level: int = logging.INFO,
    json_format: bool = False,
    stream: IO[str] | None = None,
) -> logging.Logger:
    """Configure the orchestrator logger.

    Args:
        level: Logging level (default INFO).
        json_format: If True, emit JSON lines for structured log aggregation.
        stream: Output stream (default sys.stderr).

    Returns:
        The configured root logger for the orchestrator namespace.
    """
    logger = logging.getLogger("orchestrator")
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates on reconfigure
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)

    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s [%(name)s] %(message)s")
        )

    logger.addHandler(handler)
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a child logger under the orchestrator namespace.

    Args:
        name: Logger name (will be prefixed with 'orchestrator.').

    Returns:
        A logger instance.
    """
    return logging.getLogger(f"orchestrator.{name}")
