"""S4-A2: push alerting for degraded state — the cockpit can be closed.

Residual being closed: degraded state (lost writes, recoverable WAL
events, WAL-verification failures) rendered a cockpit banner but nothing
reached an operator who wasn't looking at it.

Design:
* :func:`evaluate_and_alert` is called by a background loop in the API
  server (and is directly callable in tests).  It computes severity from
  the health snapshot, and alerts only on the degraded False→True
  transition, with a persisted cooldown (default 30 minutes) so a
  flapping condition cannot spam.
* Pluggable sinks: structured log + alerts JSONL (always available),
  Telegram webhook (``MVP_ALERT_TELEGRAM_BOT_TOKEN``/``_CHAT_ID``),
  SMTP email (``MVP_ALERT_SMTP_HOST``/``_PORT``/``_FROM``/``_TO``;
  optional ``_USER``/``_PASSWORD``), Windows toast (best-effort, only if
  a toast backend is importable), and a dry-run sink for tests.
* Every outgoing message passes secret redaction.  A sink failure logs
  at ERROR and increments ``alert_delivery_failures_total`` — it never
  crashes the API server.

Severity matrix (first match wins):
    CRITICAL  db_write_failures_total > 0
    HIGH      write_journal_recoverable_total > 0
    HIGH      wal_verification_failures > 0
    LOW       any other degraded condition

Advisory invariants: notification only — no broker, no execution; every
result dict carries the locked stamps.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.runtime_common import RUNTIME_DIR, restrict_file_permissions, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import RUNTIME_DIR, restrict_file_permissions, utc_timestamp  # type: ignore[no-redef]

_logger = logging.getLogger("scripts.alerting")

DEFAULT_COOLDOWN_SECONDS = 30 * 60

_STAMPS = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|xai-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9\-_.]{8,}"
    r"|(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+)",
    re.IGNORECASE,
)

_DELIVERY_FAILURES = 0
_LAST_ALERT_AT: str | None = None


def redact(text: str) -> str:
    return _SECRET_RE.sub("<redacted>", text)


def alert_delivery_failure_count() -> int:
    return _DELIVERY_FAILURES


def last_alert_at() -> str | None:
    return _LAST_ALERT_AT


def _reset_for_tests() -> None:
    global _DELIVERY_FAILURES, _LAST_ALERT_AT
    _DELIVERY_FAILURES = 0
    _LAST_ALERT_AT = None


def _state_path() -> Path:
    override = os.environ.get("MVP_ALERT_STATE_PATH", "").strip()
    if override:
        return Path(override)
    return RUNTIME_DIR / "diagnostics_cache" / "alert_state.json"


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {"degraded": False, "last_alert_epoch": 0.0}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("not a dict")
        return state
    except (ValueError, OSError):
        _logger.error("alert state unreadable; starting fresh")
        return {"degraded": False, "last_alert_epoch": 0.0}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    if is_new:
        restrict_file_permissions(path)


def classify_severity(health: dict[str, Any]) -> str:
    if int(health.get("db_write_failures_total") or 0) > 0:
        return "CRITICAL"
    if int(health.get("write_journal_recoverable_total") or 0) > 0:
        return "HIGH"
    if int(health.get("wal_verification_failures") or 0) > 0:
        return "HIGH"
    return "LOW"


# ---------------------------------------------------------------------------
# Sinks.  Each takes (subject, body) and returns None; raises on failure.
# ---------------------------------------------------------------------------


def log_sink(subject: str, body: str) -> None:
    """Always-on sink: ERROR log line + owner-only alerts JSONL."""
    _logger.error("ALERT %s — %s", subject, body)
    path = RUNTIME_DIR / "diagnostics_cache" / "alerts.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": utc_timestamp(), "subject": subject,
                             "body": body, **_STAMPS}) + "\n")
    if is_new:
        restrict_file_permissions(path)


def telegram_sink(subject: str, body: str) -> None:
    token = os.environ.get("MVP_ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("MVP_ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return  # not configured — not a failure
    import requests  # noqa: PLC0415 - lazy; only when configured

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{subject}\n{body}"},
        timeout=10,
    )
    resp.raise_for_status()


def smtp_sink(subject: str, body: str) -> None:
    host = os.environ.get("MVP_ALERT_SMTP_HOST", "").strip()
    if not host:
        return  # not configured
    import smtplib  # noqa: PLC0415
    from email.message import EmailMessage  # noqa: PLC0415

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("MVP_ALERT_SMTP_FROM", "mvp@localhost")
    msg["To"] = os.environ.get("MVP_ALERT_SMTP_TO", "operator@localhost")
    msg.set_content(body)
    port = int(os.environ.get("MVP_ALERT_SMTP_PORT", "25") or 25)
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        user = os.environ.get("MVP_ALERT_SMTP_USER", "")
        password = os.environ.get("MVP_ALERT_SMTP_PASSWORD", "")
        if user and password:
            smtp.starttls()
            smtp.login(user, password)
        smtp.send_message(msg)


def windows_toast_sink(subject: str, body: str) -> None:
    """Best-effort Windows toast; silently unavailable elsewhere."""
    if os.name != "nt":
        return
    try:  # pragma: no cover - Windows-only path
        from win10toast import ToastNotifier  # type: ignore  # noqa: PLC0415

        ToastNotifier().show_toast(subject, body[:200], duration=10, threaded=True)
    except ImportError:
        _logger.info("windows toast backend not installed; skipping toast sink")


DEFAULT_SINKS: tuple[Callable[[str, str], None], ...] = (
    log_sink,
    telegram_sink,
    smtp_sink,
    windows_toast_sink,
)


def cooldown_seconds() -> int:
    raw = os.environ.get("MVP_ALERT_COOLDOWN_SECONDS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_COOLDOWN_SECONDS
    except ValueError:
        return DEFAULT_COOLDOWN_SECONDS


def evaluate_and_alert(
    health: dict[str, Any],
    *,
    sinks: tuple[Callable[[str, str], None], ...] | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Alert on the degraded False→True transition, with cooldown.

    Returns a stamped summary of what happened (sent / suppressed / not
    degraded).  Never raises — sink failures are counted and logged.
    """
    global _DELIVERY_FAILURES, _LAST_ALERT_AT
    now = time.time() if now_epoch is None else now_epoch
    degraded = bool(health.get("degraded"))
    state = _load_state()
    was_degraded = bool(state.get("degraded"))
    last_alert = float(state.get("last_alert_epoch") or 0.0)

    result: dict[str, Any] = {
        **_STAMPS,
        "degraded": degraded,
        "was_degraded": was_degraded,
        "severity": classify_severity(health) if degraded else "NONE",
        "sent": False,
        "suppressed_by_cooldown": False,
        "delivery_failures": 0,
    }

    # Transition-or-reminder, ALWAYS flap-proof: even a fresh False→True
    # transition respects the cooldown so a flapping condition cannot spam
    # (the operator was already alerted within the window).
    cooldown_ok = (now - last_alert) >= cooldown_seconds() or last_alert == 0.0
    should_alert = degraded and cooldown_ok and (
        not was_degraded or (now - last_alert) >= cooldown_seconds()
    )
    if degraded and not should_alert:
        result["suppressed_by_cooldown"] = True
    if should_alert:
        subject = f"[sleeping-passenger] DEGRADED severity={result['severity']}"
        body = redact(
            "degraded=true "
            f"db_write_failures={health.get('db_write_failures_total')} "
            f"wal_recoverable={health.get('write_journal_recoverable_total')} "
            f"wal_verify_failures={health.get('wal_verification_failures')} "
            "Check the cockpit and logs/api_server.log."
        )
        for sink in sinks if sinks is not None else DEFAULT_SINKS:
            try:
                sink(subject, body)
            except Exception:
                _DELIVERY_FAILURES += 1
                result["delivery_failures"] += 1
                _logger.exception(
                    "alert sink %s failed (total failures=%d)",
                    getattr(sink, "__name__", str(sink)),
                    _DELIVERY_FAILURES,
                )
        result["sent"] = True
        state["last_alert_epoch"] = now
        _LAST_ALERT_AT = utc_timestamp()
        result["last_alert_at"] = _LAST_ALERT_AT

    state["degraded"] = degraded
    _save_state(state)
    return result
