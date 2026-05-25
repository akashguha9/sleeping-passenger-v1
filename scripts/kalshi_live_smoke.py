"""Kalshi live demo read-only smoke.

CLI entry point:

    python scripts/kalshi_live_smoke.py --dry-run --max-pages 1 --limit 20 --env demo

Strictly advisory-only.  No order placement.  No portfolio access.  No
secret values are printed under any circumstance.
"""
from __future__ import annotations

import argparse
import json
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
            "Run a single-pass read-only Kalshi smoke test against the "
            "demo (or prod) API.  Writes runtime/release/"
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
        choices=("demo", "prod"),
        help=(
            "Override KALSHI_ENV.  Use 'demo' for the safe verification "
            "path.  'prod' requires a separate operator decision."
        ),
    )
    return parser


def _sanitize_summary(summary: dict) -> dict:
    """Final defensive scrub.

    The loader already omits secrets, but this strips anything that
    could conceivably arrive from raw HTTP exceptions / nested dicts.
    """
    forbidden_keys = {
        "api_key_id",
        "private_key_path",
        "authorization",
        "kalshi-access-key",
        "kalshi-access-signature",
        "kalshi-access-timestamp",
    }

    def _scrub(obj):
        if isinstance(obj, dict):
            return {
                k: _scrub(v)
                for k, v in obj.items()
                if str(k).lower() not in forbidden_keys
            }
        if isinstance(obj, list):
            return [_scrub(x) for x in obj]
        return obj

    return _scrub(summary)


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # Override KALSHI_ENV before loading config — never echoes the value.
    if args.env:
        import os
        os.environ["KALSHI_ENV"] = args.env

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
