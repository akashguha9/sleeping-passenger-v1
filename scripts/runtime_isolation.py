"""S4-A5: runtime isolation checker — refuse global-Python server boots.

Residual being closed: the Windows host ran the MVP from global
site-packages, so dependency drift on the host silently changed runtime
behaviour and `requirements.lock` guaranteed nothing.

What this module does:
* :func:`check_runtime_isolation` — pure inspection: are we in a venv,
  are global site-packages reachable, which interpreter, and the sha256
  of ``requirements.lock`` (so health can prove WHICH dependency set the
  process believes it runs).
* :func:`enforce_isolation_or_die` — called from the SERVER boot path
  (``python scripts/api_server.py`` / the start scripts).  Refuses to
  start from a global interpreter unless ``MVP_ALLOW_GLOBAL_PYTHON=1``;
  with the override, the process runs but health reports degraded
  isolation.  Deliberately NOT enforced on import or under pytest —
  TestClient startups in CI run on a non-venv interpreter and the test
  suite is not the deployment boundary; the start scripts are.

Advisory invariants: inspection only — no broker, no execution.
"""
from __future__ import annotations

import hashlib
import logging
import os
import site
import sys
from pathlib import Path
from typing import Any

_logger = logging.getLogger("scripts.runtime_isolation")

_REPO_ROOT = Path(__file__).resolve().parents[1]

_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}


class RuntimeIsolationError(RuntimeError):
    """Server boot refused: running from a global (non-venv) interpreter."""


def dependency_lock_hash() -> str | None:
    lock = _REPO_ROOT / "requirements.lock"
    if not lock.exists():
        return None
    return hashlib.sha256(lock.read_bytes()).hexdigest()


def global_python_override_active() -> bool:
    return os.environ.get("MVP_ALLOW_GLOBAL_PYTHON", "").strip() == "1"


def check_runtime_isolation() -> dict[str, Any]:
    """Pure inspection of the current interpreter's isolation posture."""
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    # In a venv created without --system-site-packages, ENABLE_USER_SITE is
    # False and global site dirs are not on the path.
    user_site_enabled = bool(getattr(site, "ENABLE_USER_SITE", False))
    return {
        **_STAMPS,
        "runtime_isolated": in_venv and not user_site_enabled,
        "in_venv": in_venv,
        "global_site_packages_enabled": (not in_venv) or user_site_enabled,
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "dependency_lock_hash": dependency_lock_hash(),
        "global_python_override_active": global_python_override_active(),
    }


def enforce_isolation_or_die() -> dict[str, Any]:
    """Boot-path gate: raise unless venv-isolated or explicitly overridden."""
    status = check_runtime_isolation()
    if status["runtime_isolated"]:
        _logger.info(
            "runtime isolation OK: %s (lock=%s)",
            status["python_executable"],
            (status["dependency_lock_hash"] or "missing")[:16],
        )
        return status
    if global_python_override_active():
        _logger.error(
            "RUNNING FROM GLOBAL PYTHON with MVP_ALLOW_GLOBAL_PYTHON=1 — "
            "dependency reproducibility is NOT guaranteed; health is degraded."
        )
        return status
    raise RuntimeIsolationError(
        "refusing to start from a global (non-venv) Python interpreter. "
        "Run scripts/windows/bootstrap_venv.ps1 then "
        "scripts/windows/start_mvp_clean_venv.ps1, or set "
        "MVP_ALLOW_GLOBAL_PYTHON=1 to override (health will show degraded)."
    )
