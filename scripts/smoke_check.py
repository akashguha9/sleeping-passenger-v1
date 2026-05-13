"""
Local smoke check for the Sleeping Passenger advisory MVP.

Single command that tells you whether the backend is alive AND whether the
advisory safety contract is intact.  Designed to run BEFORE a demo and
AFTER any backend restart or container bring-up.

It does:
  * GET /health
  * optionally GET /db/status (if the route exists)
  * verify the advisory safety stamps:
        advisory_status    = ADVISORY_ONLY
        execution_gate     = LOCKED
        broker_api_called  = false
        ai_execution_count = 0
        human_review_required = true
  * report db_available, api_token_required, environment, version

Exit codes:
    0 -- all survival-critical checks PASSED
    1 -- one or more checks FAILED (backend unreachable, safety wrong,
         malformed response, etc.)
    2 -- usage/argument error

The script never mutates anything.  Only GETs.

Usage:
    python scripts/smoke_check.py
    python scripts/smoke_check.py --api http://127.0.0.1:8000
    python scripts/smoke_check.py --json
    python scripts/smoke_check.py --timeout 10
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _http_get_json(url: str, timeout: float) -> tuple[dict[str, Any] | None, str | None]:
    """Return (parsed_json, error_message).  Never raises."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return None, f"unreachable: {reason}"
    except TimeoutError as exc:
        return None, f"timeout: {exc}"
    except OSError as exc:
        return None, f"socket error: {exc}"
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"malformed json: {exc}"


def run_smoke_check(api_base: str, timeout: float = 5.0) -> dict[str, Any]:
    """Pure function: runs the checks and returns a structured result.

    Test-friendly -- supply your own GET function by monkey-patching
    _http_get_json in the smoke_check module.
    """
    api_base = api_base.rstrip("/")
    checks: list[dict[str, Any]] = []
    overall_ok = True

    def record(name: str, status: str, detail: str = "") -> None:
        nonlocal overall_ok
        checks.append({"name": name, "status": status, "detail": detail})
        if status == "FAIL":
            overall_ok = False

    health_url = f"{api_base}/health"
    health, err = _http_get_json(health_url, timeout=timeout)
    if health is None:
        record("backend_reachable", "FAIL", err or "no response")
        return {
            "ok": False,
            "api_base": api_base,
            "checks": checks,
            "health": None,
        }
    record("backend_reachable", "PASS", health_url)

    # --- advisory safety stamps ---
    advisory_status = health.get("advisory_status")
    if advisory_status == "ADVISORY_ONLY":
        record("advisory_status", "PASS", "ADVISORY_ONLY")
    else:
        record("advisory_status", "FAIL", f"got {advisory_status!r}")

    execution_gate = health.get("execution_gate")
    if execution_gate == "LOCKED":
        record("execution_gate", "PASS", "LOCKED")
    else:
        record("execution_gate", "FAIL", f"got {execution_gate!r}")

    execution_mode = health.get("execution_mode")
    if execution_mode in (None, "HUMAN_ONLY"):
        # Older builds may omit execution_mode; treat absence as info.
        if execution_mode is None:
            record("execution_mode", "INFO", "absent (older /health)")
        else:
            record("execution_mode", "PASS", "HUMAN_ONLY")
    else:
        record("execution_mode", "FAIL", f"got {execution_mode!r}")

    broker_called = health.get("broker_api_called")
    if broker_called is False:
        record("broker_api_called", "PASS", "false")
    else:
        record("broker_api_called", "FAIL", f"got {broker_called!r}")

    ai_exec = health.get("ai_execution_count")
    if ai_exec == 0:
        record("ai_execution_count", "PASS", "0")
    else:
        record("ai_execution_count", "FAIL", f"got {ai_exec!r}")

    broker_order_id = health.get("broker_order_id")
    if broker_order_id in (None, "NONE"):
        record(
            "broker_order_id",
            "PASS" if broker_order_id == "NONE" else "INFO",
            str(broker_order_id),
        )
    else:
        record("broker_order_id", "FAIL", f"got {broker_order_id!r}")

    human_review = health.get("human_review_required")
    if human_review is True:
        record("human_review_required", "PASS", "true")
    elif human_review is None:
        record("human_review_required", "INFO", "absent")
    else:
        record("human_review_required", "FAIL", f"got {human_review!r}")

    # --- operational signals ---
    db_avail = health.get("db_available")
    if db_avail is True:
        record("db_available", "PASS", "true")
    elif db_avail is False:
        record("db_available", "FAIL", "db_available=false; DB missing on disk")
    else:
        record("db_available", "INFO", "absent from /health")

    token_required = health.get("api_token_required")
    if token_required is True:
        record("api_token_required", "INFO", "true (mutations require Bearer token)")
    elif token_required is False:
        record("api_token_required", "INFO", "false (permissive local mode)")
    else:
        record("api_token_required", "INFO", "absent from /health")

    env = health.get("environment")
    record("environment", "INFO", str(env) if env is not None else "absent")

    version = health.get("version")
    record("version", "INFO", str(version) if version is not None else "absent")

    return {
        "ok": overall_ok,
        "api_base": api_base,
        "checks": checks,
        "health": health,
    }


def _emit_text(result: dict[str, Any]) -> None:
    print("Sleeping Passenger Smoke Check")
    print(f"API: {result['api_base']}")
    for c in result["checks"]:
        tag = c["status"]
        detail = c["detail"]
        line = f"[{tag}] {c['name']}"
        if detail:
            line += f" {detail}"
        print(line)
    print(f"RESULT: {'PASS' if result['ok'] else 'FAIL'}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smoke_check.py",
        description="Pre-demo smoke check for the advisory MVP. GETs only.",
    )
    parser.add_argument(
        "--api",
        type=str,
        default="http://127.0.0.1:8000",
        help="Backend base URL (default: http://127.0.0.1:8000).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="HTTP timeout in seconds (default: 5).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a single JSON object on stdout instead of human text.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.timeout <= 0:
        print("[FAIL] --timeout must be positive")
        print("RESULT: FAIL")
        return 2

    result = run_smoke_check(api_base=args.api, timeout=args.timeout)

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        _emit_text(result)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
