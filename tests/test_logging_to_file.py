"""F8 regression: errors reach a rotating log file, not just stdout.

Audit finding F8: ``src/utils/logging_utils.get_logger`` attached only a
StreamHandler — under the silent PowerShell startup scripts stdout is
discarded, so even loud failures were unrecoverable after the fact.

Contract: get_logger attaches a RotatingFileHandler to logs/api_server.log
(5MB x 3) alongside the stream handler; the directory is gitignored.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_get_logger_attaches_rotating_file_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_LOG_DIR", str(tmp_path))
    import importlib

    from src.utils import logging_utils

    importlib.reload(logging_utils)
    logger = logging_utils.get_logger("f8_test_logger")
    file_handlers = [
        h for h in logger.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers, "RotatingFileHandler missing"
    fh = file_handlers[0]
    assert fh.maxBytes == 5 * 1024 * 1024
    assert fh.backupCount == 3

    logger.error("f8 file sink probe")
    fh.flush()
    log_file = Path(fh.baseFilename)
    assert log_file.exists()
    assert "f8 file sink probe" in log_file.read_text()
    # Cleanup so the reloaded module state doesn't leak into other tests.
    importlib.reload(logging_utils)


def test_logs_dir_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    assert "logs/" in gitignore.splitlines() or "logs/" in gitignore
