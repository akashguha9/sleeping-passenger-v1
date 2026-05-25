"""Kalshi source-health watchdog (read-only).

Inspects the canonical ``kalshi_source_health.json``, compares the
freshness age against the configured TTL, and — only when stale or
missing — runs another read-only Kalshi smoke to refresh the artifact.

Strict safety contract:
- GET-only.  Re-uses the read-only client + smoke loader.
- No trading / portfolio / account endpoints.  Ever.
- Never prints API Key ID, private-key path, auth headers, or signatures.
- Never persists signal_events (dry-run smoke).

CLI:

    python scripts/kalshi_watchdog_refresh.py --dry-run --max-pages 5 --limit 100 --env demo

Exit codes:
    0   fresh OR refresh succeeded
    1   stale AND refresh failed
    2   config error / safety violation
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.kalshi_runner import (  # noqa: E402
    DEFAULT_KALSHI_HEALTH_PATH,
    _atomic_write_json,
)
from src.ingestion.kalshi_live_config import (  # noqa: E402
    KalshiConfigError,
    load_kalshi_live_config,
)
from src.ingestion.kalshi_live_loader import run_live_kalshi_smoke  # noqa: E402


_LOG = logging.getLogger(__name__)
_REPO_ROOT_PATH = _REPO_ROOT
DEFAULT_KALSHI_WATCHDOG_SUMMARY_PATH = (
    _REPO_ROOT_PATH / "runtime" / "release" / "kalshi_watchdog_summary.json"
)


@dataclass
class WatchdogResult:
    fresh: bool = False
    stale: bool = False
    missing: bool = False
    refresh_attempted: bool = False
    refresh_succeeded: bool = False
    source_freshness_status: str = "UNVERIFIED"
    age_seconds: float | None = None
    ttl_seconds: int = 0
    last_successful_fetch_at_utc: str | None = None
    error_type: str = ""
    error_message: str = ""
    summary_path: str = ""
    advisory_only: bool = True
    human_review_required: bool = True
    execution_locked: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    safety_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_utc(text: Any) -> datetime | None:
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _read_health(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Kalshi read-only watchdog — refresh source-health when "
            "stale.  Never touches trading/account/order endpoints."
        )
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--env",
        type=str,
        default="demo",
        choices=("demo", "prod", "production"),
        help="KALSHI_ENV override.  Defaults to demo.",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=None,
        help=(
            "Override the TTL used to classify freshness.  Defaults to "
            "the value persisted in source-health (or KALSHI_FRESHNESS_TTL_SECONDS)."
        ),
    )
    parser.add_argument(
        "--seek-allowed",
        action="store_true",
        default=True,
        help=(
            "Use seek-allowed pagination on refresh to maximise the "
            "chance of recovering an accepted-scope row when the "
            "first demo page is weather-heavy."
        ),
    )
    parser.add_argument(
        "--min-allowed",
        type=int,
        default=1,
        help="Target accepted-record count when --seek-allowed is set.",
    )
    parser.add_argument(
        "--health-path",
        type=str,
        default=None,
        help="Override the source-health path (tests use tmp_path).",
    )
    parser.add_argument(
        "--summary-path",
        type=str,
        default=None,
        help="Override the watchdog summary output path (tests).",
    )
    return parser


def run_watchdog(
    *,
    health_path: Path | None = None,
    summary_path: Path | None = None,
    env: str = "demo",
    ttl_seconds: int | None = None,
    max_pages: int = 5,
    limit: int = 100,
    dry_run: bool = True,
    seek_allowed: bool = True,
    min_allowed: int = 1,
    now_utc: datetime | None = None,
    refresh_callable: Any = None,
) -> WatchdogResult:
    """Drive the watchdog logic.  Pure (apart from the source-health read
    + optional refresh call), so tests can inject ``now_utc`` and a
    refresh fake.
    """
    health = Path(health_path) if health_path else DEFAULT_KALSHI_HEALTH_PATH
    summary = Path(summary_path) if summary_path else DEFAULT_KALSHI_WATCHDOG_SUMMARY_PATH
    now = now_utc or _utc_now()

    payload = _read_health(health)
    result = WatchdogResult()
    if payload is None:
        result.missing = True
        result.source_freshness_status = "MISSING"
    else:
        ttl = int(
            ttl_seconds
            if ttl_seconds is not None
            else int(payload.get("freshness_ttl_seconds") or 0)
            or int(os.environ.get("KALSHI_FRESHNESS_TTL_SECONDS", "21600") or "21600")
        )
        result.ttl_seconds = ttl
        last_str = payload.get("last_successful_fetch_at_utc")
        last_dt = _parse_utc(last_str)
        result.last_successful_fetch_at_utc = last_str
        if last_dt is None:
            result.stale = True
        else:
            age = (now - last_dt).total_seconds()
            result.age_seconds = age
            if age < 0 or age <= ttl:
                result.fresh = True
            else:
                result.stale = True
        result.source_freshness_status = str(
            payload.get("source_freshness_status") or "UNVERIFIED"
        )

    needs_refresh = result.stale or result.missing
    if needs_refresh:
        result.refresh_attempted = True
        env_value = "prod" if env in ("prod", "production") else "demo"
        os.environ["KALSHI_ENV"] = env_value
        if refresh_callable is None:
            refresh_callable = run_live_kalshi_smoke
        try:
            cfg = load_kalshi_live_config()
            # Belt-and-braces safety re-check before any HTTP.
            cfg.assert_read_only_safe()
            refresh_result = refresh_callable(
                config=cfg,
                max_pages=max_pages,
                limit=limit,
                dry_run=dry_run,
                seek_allowed=seek_allowed,
                min_allowed=min_allowed,
                health_path=health,
            )
            result.refresh_succeeded = getattr(refresh_result, "status", "error") == "ok"
            result.source_freshness_status = getattr(
                refresh_result, "source_freshness_status", result.source_freshness_status
            )
            if not result.refresh_succeeded:
                result.error_type = getattr(refresh_result, "error_type", "")
                result.error_message = getattr(refresh_result, "error_message", "")
        except KalshiConfigError as exc:
            result.error_type = "KalshiConfigError"
            result.error_message = str(exc)
            result.refresh_succeeded = False
        except Exception as exc:  # noqa: BLE001
            result.error_type = type(exc).__name__
            # Never embed response body in the summary.
            result.error_message = type(exc).__name__
            result.refresh_succeeded = False

    # Assert safety stamps before persisting the summary.
    safety_violations: list[str] = []
    if not result.advisory_only:
        safety_violations.append("advisory_only must be True")
    if result.broker_api_called:
        safety_violations.append("broker_api_called must be False")
    if result.ai_execution_count != 0:
        safety_violations.append("ai_execution_count must be 0")
    result.safety_violations = safety_violations

    summary_payload = result.to_dict()
    summary_payload["watchdog_run_at_utc"] = now.isoformat()
    summary_payload["env"] = env
    try:
        _atomic_write_json(summary, summary_payload)
        result.summary_path = str(summary)
    except OSError as exc:  # pragma: no cover
        _LOG.warning("kalshi watchdog summary write failed: %s", exc)

    return result


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    result = run_watchdog(
        health_path=Path(args.health_path) if args.health_path else None,
        summary_path=Path(args.summary_path) if args.summary_path else None,
        env=args.env,
        ttl_seconds=args.ttl_seconds,
        max_pages=args.max_pages,
        limit=args.limit,
        dry_run=args.dry_run,
        seek_allowed=args.seek_allowed,
        min_allowed=args.min_allowed,
    )
    payload = result.to_dict()
    payload["env"] = args.env
    print(json.dumps(payload, indent=2))
    if result.fresh:
        return 0
    if result.refresh_attempted and result.refresh_succeeded:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
