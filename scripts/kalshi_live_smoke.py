"""Kalshi live demo read-only smoke.

CLI entry point:

    python scripts/kalshi_live_smoke.py --dry-run --max-pages 1 --limit 20 --env demo
    python scripts/kalshi_live_smoke.py --dry-run --seek-allowed --min-allowed 1 \
        --max-pages 5 --limit 100 --env demo

Strictly advisory-only.  No order placement.  No portfolio access.  No
secret values are printed under any circumstance.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure the repo root is on sys.path for direct ``python scripts/`` runs.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.ingestion.kalshi_live_config import (  # noqa: E402
    KalshiConfigError,
    load_kalshi_live_config,
)
from src.ingestion.kalshi_live_loader import run_live_kalshi_smoke  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only Kalshi smoke test against the demo (or "
            "production) API.  Writes runtime/release/"
            "kalshi_source_health.json and a quarantine jsonl audit "
            "trail.  Never prints secrets."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help=(
            "Do not persist signal_events; only fetch + normalize + write "
            "source-health/quarantine artifacts. (default: True)"
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=1,
        help="Maximum number of /markets pages to walk (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Per-page market limit (default: 20).",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        choices=("demo", "prod", "production"),
        help=(
            "Override KALSHI_ENV.  Use 'demo' for the safe verification "
            "path.  'production' / 'prod' require operator opt-in."
        ),
    )
    parser.add_argument(
        "--seek-allowed",
        action="store_true",
        default=False,
        help=(
            "Continue paginating until at least --min-allowed accepted "
            "records are observed, OR --max-pages is reached, OR the "
            "cursor is exhausted.  Read-only and quarantine-respecting."
        ),
    )
    parser.add_argument(
        "--min-allowed",
        type=int,
        default=1,
        help="When --seek-allowed is set, target this many allowed records.",
    )
    return parser


_FORBIDDEN_KEYS = {
    "api_key_id",
    "private_key_path",
    "authorization",
    "kalshi-access-key",
    "kalshi-access-signature",
    "kalshi-access-timestamp",
}


def _sanitize_summary(summary: dict) -> dict:
    """Final defensive scrub.

    The loader already omits secrets, but this strips anything that
    could conceivably arrive from raw HTTP exceptions / nested dicts.
    """

    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: _scrub(v)
                for k, v in obj.items()
                if str(k).lower() not in _FORBIDDEN_KEYS
            }
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return obj

    return _scrub(summary)


def _production_env_ready() -> bool:
    """Return True only when a real production credential set is present.

    The smoke MUST NOT call production with an unconfigured/empty key,
    but unauthenticated public GETs are still allowed when the operator
    explicitly opts into a no-auth production probe by leaving
    KALSHI_ENABLE_AUTH=false.  We treat "auth requested but missing
    pieces" as the failure condition.
    """
    enable_auth = (os.environ.get("KALSHI_ENABLE_AUTH", "") or "").strip().lower()
    if enable_auth not in {"1", "true", "yes", "on"}:
        # Public read-only mode — no credentials required.
        return True
    api_key_id = (os.environ.get("KALSHI_API_KEY_ID", "") or "").strip()
    key_path = (os.environ.get("KALSHI_PRIVATE_KEY_PATH", "") or "").strip()
    return bool(api_key_id) and bool(key_path)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # Override KALSHI_ENV before loading config — never echoes the value.
    if args.env:
        env_value = "prod" if args.env in ("prod", "production") else "demo"
        os.environ["KALSHI_ENV"] = env_value
        if env_value == "prod" and not _production_env_ready():
            print(
                json.dumps(
                    {
                        "status": "error",
                        "source_freshness_status": "SOURCE_ERROR_PRODUCTION_ENV_MISSING",
                        "error_type": "KalshiConfigError",
                        "error_message": (
                            "Production smoke requested but auth env is "
                            "incomplete; refusing to run.  Set KALSHI_API_KEY_ID "
                            "and KALSHI_PRIVATE_KEY_PATH (paths redacted) or "
                            "leave KALSHI_ENABLE_AUTH=false for the public path."
                        ),
                        "env": "prod",
                        "advisory_only": True,
                        "broker_api_called": False,
                        "ai_execution_count": 0,
                        "human_review_required": True,
                        "execution_locked": True,
                    },
                    indent=2,
                )
            )
            return 3

    try:
        cfg = load_kalshi_live_config()
    except KalshiConfigError as exc:
        # Never echo env var values; print the message verbatim.
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": "KalshiConfigError",
                    "error_message": str(exc),
                    "advisory_only": True,
                    "broker_api_called": False,
                    "ai_execution_count": 0,
                },
                indent=2,
            )
        )
        return 2

    try:
        result = run_live_kalshi_smoke(
            config=cfg,
            max_pages=args.max_pages,
            limit=args.limit,
            dry_run=args.dry_run,
            seek_allowed=args.seek_allowed,
            min_allowed=args.min_allowed,
        )
    except KalshiConfigError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": "KalshiConfigError",
                    "error_message": str(exc),
                    "advisory_only": True,
                    "broker_api_called": False,
                    "ai_execution_count": 0,
                },
                indent=2,
            )
        )
        return 2

    summary = _sanitize_summary(result.to_dict())
    print(json.dumps(summary, indent=2))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
