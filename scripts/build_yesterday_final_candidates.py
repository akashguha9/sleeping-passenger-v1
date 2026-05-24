"""Builder — yesterday's final candidates (anti-staleness comparison set Y).

Writes ``data/daily_payload/yesterday_final_candidates.json``.

Sources, in priority order:
    1. Most recent previous synthesis output stored in the repo
       (``runtime/daily_synthesis_context.json``).
    2. The existing ``data/daily_payload/yesterday_final_candidates.json``.
    3. Static fallback with empty candidate lists.

Never crashes if yesterday's report is missing — it degrades to the empty
fallback. Carrying the existing payload forward is intentional: it keeps the
anti-staleness layer's set Y stable until a fresh synthesis writes a new one.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.runtime_common import REPO_ROOT, ensure_directory, load_json_file, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT, ensure_directory, load_json_file, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
YESTERDAY_CANDIDATES_PATH = DAILY_PAYLOAD_DIR / "yesterday_final_candidates.json"
SYNTHESIS_CONTEXT_PATH = REPO_ROOT / "runtime" / "daily_synthesis_context.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_directory(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _norm_list(values: Any) -> list[str]:
    out: list[str] = []
    for value in values or []:
        ticker = str(value or "").strip().upper()
        if ":" in ticker:
            ticker = ticker.rsplit(":", 1)[-1].strip()
        if ticker and ticker not in out:
            out.append(ticker)
    return out


def _from_synthesis_context(path: Path) -> dict[str, Any] | None:
    payload = load_json_file(path, default=None)
    if not isinstance(payload, dict):
        return None
    final_candidates = _norm_list(
        list(payload.get("executable_paper_buys") or [])
        + list(payload.get("buy_candidate_not_executable") or [])
    )
    if not final_candidates:
        return None
    return {
        "final_candidates": final_candidates,
        "watchlist": _norm_list(payload.get("watchlist")),
        "avoids": _norm_list(payload.get("avoids")),
        "source": "previous_synthesis_report",
        "freshness": "UPDATED_TODAY",
    }


def _from_existing_payload(path: Path) -> dict[str, Any] | None:
    payload = load_json_file(path, default=None)
    if not isinstance(payload, dict):
        return None
    final_candidates = _norm_list(payload.get("final_candidates"))
    watchlist = _norm_list(payload.get("watchlist"))
    avoids = _norm_list(payload.get("avoids"))
    if not (final_candidates or watchlist or avoids):
        return None
    return {
        "final_candidates": final_candidates,
        "watchlist": watchlist,
        "avoids": avoids,
        "source": "existing_payload",
        "freshness": "UNVERIFIED",
    }


def build_yesterday_final_candidates(
    run_date: str,
    generated_at_utc: str | None = None,
    synthesis_context_path: Path | None = None,
    existing_payload_path: Path | None = None,
) -> dict[str, Any]:
    """Return yesterday's final-candidates payload (pure; priority-ordered)."""
    resolved = (
        _from_synthesis_context(synthesis_context_path or SYNTHESIS_CONTEXT_PATH)
        or _from_existing_payload(existing_payload_path or YESTERDAY_CANDIDATES_PATH)
        or {
            "final_candidates": [],
            "watchlist": [],
            "avoids": [],
            "source": "empty_fallback",
            "freshness": "UNVERIFIED",
        }
    )
    return {
        "run_date": run_date,
        "source": resolved["source"],
        "generated_at_utc": generated_at_utc or utc_timestamp(),
        "final_candidates": resolved["final_candidates"],
        "watchlist": resolved["watchlist"],
        "avoids": resolved["avoids"],
        "freshness": resolved["freshness"],
    }


def write_yesterday_final_candidates(
    run_date: str,
    path: Path | None = None,
    generated_at_utc: str | None = None,
    synthesis_context_path: Path | None = None,
) -> dict[str, Any]:
    target = path or YESTERDAY_CANDIDATES_PATH
    # Read the existing payload BEFORE overwriting it so source 2 still works.
    payload = build_yesterday_final_candidates(
        run_date,
        generated_at_utc,
        synthesis_context_path=synthesis_context_path,
        existing_payload_path=target,
    )
    _write_json(target, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build yesterday's final-candidates payload.")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = parser.parse_args(argv)
    run_date = args.run_date or utc_timestamp()[:10]
    payload = write_yesterday_final_candidates(run_date)
    sys.stdout.write(
        f"yesterday_final_candidates.json written: source={payload['source']} "
        f"final_candidates={len(payload['final_candidates'])} "
        f"watchlist={len(payload['watchlist'])} avoids={len(payload['avoids'])}\n"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
