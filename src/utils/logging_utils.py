"""Structured logging helpers for the read-only MVP subsystem."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .time_utils import utc_now_iso


def get_logger(name: str) -> logging.Logger:
    """Return a basic console logger configured once per process."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a single structured JSON log line."""
    payload = {"timestamp": utc_now_iso(), "event": event, **fields}
    logger.info(json.dumps(payload, sort_keys=True))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
