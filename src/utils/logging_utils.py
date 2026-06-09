"""Structured logging helpers for the read-only MVP subsystem."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
from pathlib import Path
from typing import Any

from .time_utils import utc_now_iso

# F8 audit fix: stdout is DISCARDED under the silent PowerShell startup
# scripts, so a stream-only logger made every failure unrecoverable after
# the fact.  All get_logger loggers therefore also write to a rotating
# file under logs/ (gitignored).  Override the directory with MVP_LOG_DIR
# (tests use a tmp dir); rotation: 5MB x 3 backups.
_LOG_FILE_NAME = "api_server.log"
_LOG_MAX_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 3


def _log_dir() -> Path:
    return Path(os.environ.get("MVP_LOG_DIR", "logs"))


def _build_file_handler() -> logging.Handler | None:
    """Best-effort rotating file handler; None if the dir is unwritable."""
    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / _LOG_FILE_NAME,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        return handler
    except OSError:
        # A read-only filesystem must not break logging entirely — the
        # stream handler still works and this is reported there.
        logging.getLogger(__name__).error(
            "could not create rotating log file in %s", _log_dir()
        )
        return None


def get_logger(name: str) -> logging.Logger:
    """Return a console+file logger configured once per process."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        file_handler = _build_file_handler()
        if file_handler is not None:
            logger.addHandler(file_handler)
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
