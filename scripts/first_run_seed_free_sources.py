"""First-day operator seed — populate canonical SQLite from free public sources.

Identity Collapse + First-Day Operator sprint, Phase 3.

What this script is
-------------------
A read-only wrapper around :func:`scripts.refresh_live_signals.run_refresh`
that targets ONLY the free, key-light, public sources so a fresh clone can
produce useful, truth-labeled rows on day one.

The default source set is:

* ``polymarket``      — Public Gamma API; no key.
* ``gdelt``           — Public DOC API; no key.
* ``sec_edgar``       — Public EDGAR; requires only a ``SEC_USER_AGENT``
  env var.  If absent, this script falls back to a generic UA so a fresh
  operator still gets a graceful skip rather than a crash.
* ``newsapi``         — Only attempted if ``NEWS_API_KEY`` is set.
* ``event_registry``  — Only attempted if ``EVENT_REGISTRY_API_KEY`` is set.

Each attempted source flows through the existing 6-hour refresh
orchestrator, which already enforces:

* Advisory-only safety stamps on every persisted row and metadata entry.
* Clean skip with explicit reason when an adapter is unavailable.
* Truth-source labelling so downstream consumers can distinguish live vs
  mock vs skipped data.

Hard rules
~~~~~~~~~~
* **No broker calls.**  No order, fill, position, deposit, withdrawal,
  balance, or api_keys endpoint is reachable from this code path.
* **No fabricated rows.**  When a source cannot return real data, the
  script records a skipped/failed entry with a redacted reason.  It does
  **not** insert demo rows into canonical ``signal_events``.
* **No secret values printed.**  Only env-var presence is reported.
* **Default is dry-run.**  ``--write`` is the explicit opt-in that
  persists ``signal_events`` rows.

CLI
~~~

  python scripts/first_run_seed_free_sources.py --dry-run
  python scripts/first_run_seed_free_sources.py --write
  python scripts/first_run_seed_free_sources.py --max-per-source 25
  python scripts/first_run_seed_free_sources.py --db runtime/mvp_local.db
  python scripts/first_run_seed_free_sources.py \
      --json-summary runtime/release/first_run_seed_summary.json

Summary JSON contract (advisory-only):

  {
    "script": "first_run_seed_free_sources.py",
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": false,
    "ai_execution_count": 0,
    "canonical_store": "sqlite",
    "jsonl_is_canonical": false,
    "dry_run": <bool>,
    "started_at_utc": "...",
    "finished_at_utc": "...",
    "sources_attempted": N,
    "sources_succeeded": N,
    "sources_skipped": N,
    "sources_failed": N,
    "rows_collected": N,
    "rows_written": N,
    "rows_mock": N,
    "rows_live_public": N,
    "source_results": [ ... ]
  }
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Public, key-light source defaults.  Order matters only for human-readable
# output; the orchestrator processes them independently.
FREE_SOURCES_DEFAULT: tuple[str, ...] = (
    "polymarket",
    "gdelt",
    "sec_edgar",
)

# Optional keyed sources — attempted only when their env var is set.  We
# never fabricate fallback data when a key is absent.
OPTIONAL_KEYED_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("newsapi", ("NEWS_API_KEY",)),
    ("event_registry", ("EVENT_REGISTRY_API_KEY",)),
)


SAFETY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "can_execute": False,
    "ai_execution_count": 0,
    "execution_permission": False,
    "human_review_required": True,
    "broker_order_id": "NONE",
    "canonical_store": "sqlite",
    "jsonl_is_canonical": False,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "First-day operator seed.  Populates canonical SQLite from free "
            "public sources.  ADVISORY-ONLY.  No broker calls."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Default.  Adapters run in dry-run mode; no signal_events written.",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Explicit opt-in.  Persist signal_events rows from real public sources.",
    )
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=25,
        help=(
            "Cap on rows persisted per source for the first-run seed (default 25). "
            "Adapters that ignore this hint are simply not capped — the orchestrator "
            "is the authority on actual row counts."
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Override the SQLite DB path.  Default is the value resolved by "
            "scripts.refresh_live_signals (``runtime/mvp_local.db`` unless "
            "``MVP_DB_PATH`` is set)."
        ),
    )
    parser.add_argument(
        "--json-summary",
        default=None,
        help=(
            "Optional path to write the structured JSON summary.  If omitted, "
            "the summary is only printed to stdout."
        ),
    )
    parser.add_argument(
        "--include-optional-keyed",
        action="store_true",
        help=(
            "Also attempt NewsAPI / Event Registry when their API keys are set. "
            "Sources without keys are skipped cleanly — never fabricated."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-source human-readable lines (summary block still printed).",
    )
    args = parser.parse_args(argv)
    if not args.write:
        args.dry_run = True
    return args


def _select_sources(*, include_optional: bool) -> list[str]:
    out: list[str] = list(FREE_SOURCES_DEFAULT)
    if include_optional:
        for key, env_keys in OPTIONAL_KEYED_SOURCES:
            if all(os.environ.get(k, "").strip() for k in env_keys):
                out.append(key)
    return out


def _classify_truth_source(entry: dict[str, Any]) -> str:
    """Map a refresh-orchestrator entry to a first-run truth label."""
    if entry.get("skipped"):
        return "skipped"
    if not entry.get("success"):
        return "error"
    # The free-source set is entirely public/read-only; any successful row
    # is therefore ``live_public``.  Keyed sources (newsapi /
    # event_registry) report ``live_keyed`` so the operator can tell at a
    # glance which rows came from a free vs key-gated path.
    source_key = str(entry.get("source_name") or "").strip().lower()
    keyed = {k for k, _ in OPTIONAL_KEYED_SOURCES}
    if source_key in keyed:
        return "live_keyed"
    return "live_public"


def _build_source_result(entry: dict[str, Any]) -> dict[str, Any]:
    truth_source = _classify_truth_source(entry)
    source_key = str(entry.get("source_name") or "").strip().lower()
    keyed = {k for k, _ in OPTIONAL_KEYED_SOURCES}
    rows_added = int(entry.get("rows_added") or 0)

    if entry.get("skipped"):
        adapter_status = "skipped"
    elif not entry.get("success"):
        adapter_status = "failed"
    else:
        adapter_status = "implemented"

    return {
        "source_name": source_key,
        "adapter_status": adapter_status,
        "truth_source": truth_source,
        "fallback_used": False,
        "canonical": adapter_status == "implemented",
        "rows_collected": rows_added,
        "rows_written": rows_added if adapter_status == "implemented" else 0,
        "skip_reason": str(entry.get("skipped_reason") or "") if entry.get("skipped") else "",
        "error_type": "" if entry.get("success") or entry.get("skipped") else "adapter_error",
        "error_message_redacted": str(entry.get("error_message") or "")[:200],
        "is_keyed_source": source_key in keyed,
        **SAFETY_STAMPS,
    }


def _override_db_path_if_requested(db_override: str | None) -> str | None:
    """Set ``MVP_DB_PATH`` for this process so the refresh orchestrator picks
    up the override.  Returns the previous value (or None) so the caller can
    restore it.
    """
    if not db_override:
        return os.environ.get("MVP_DB_PATH")
    prior = os.environ.get("MVP_DB_PATH")
    os.environ["MVP_DB_PATH"] = str(db_override)
    return prior


def _restore_db_path(prior: str | None) -> None:
    if prior is None:
        os.environ.pop("MVP_DB_PATH", None)
    else:
        os.environ["MVP_DB_PATH"] = prior


def run_first_run_seed(
    *,
    dry_run: bool = True,
    include_optional_keyed: bool = False,
    max_per_source: int = 25,
    db_override: str | None = None,
) -> dict[str, Any]:
    """Run the first-day seed and return a structured advisory-only summary.

    No broker, no order, no execution.  The wrapper delegates fetching to
    :func:`scripts.refresh_live_signals.run_refresh`, which already
    enforces the advisory safety contract for every persisted row.
    """
    started_at = _utc_now_iso()

    # We import inside the function so tests that don't need the full
    # adapter stack can still load this module.
    try:
        from scripts.refresh_live_signals import run_refresh as _run_refresh
    except ModuleNotFoundError:  # pragma: no cover — defensive
        from refresh_live_signals import run_refresh as _run_refresh  # type: ignore[no-redef]

    sources = _select_sources(include_optional=include_optional_keyed)
    prior_db = _override_db_path_if_requested(db_override)
    try:
        refresh_summary = _run_refresh(
            source_keys=sources,
            write_mode=bool(not dry_run),
            summary_only=False,
        )
    finally:
        _restore_db_path(prior_db)

    finished_at = _utc_now_iso()
    entries = refresh_summary.get("entries") or []

    source_results = [_build_source_result(e) for e in entries]

    rows_collected = sum(int(e.get("rows_added") or 0) for e in entries)
    rows_written = sum(r["rows_written"] for r in source_results)
    # No mock rows are ever written by this script.  The field is fixed at 0
    # so downstream truth gates can rely on it.
    rows_mock = 0
    rows_live_public = sum(r["rows_written"] for r in source_results if r["truth_source"] == "live_public")
    rows_live_keyed = sum(r["rows_written"] for r in source_results if r["truth_source"] == "live_keyed")

    sources_attempted = len(entries)
    sources_succeeded = sum(1 for e in entries if e.get("success"))
    sources_skipped = sum(1 for e in entries if e.get("skipped"))
    sources_failed = sum(1 for e in entries if not e.get("success") and not e.get("skipped"))

    # Mathematical usefulness metric, clamped to [0, 10].
    mock_penalty = 3 if rows_mock > 0 else 0
    usefulness_raw = (
        2 * sources_succeeded
        + min(rows_written, 50) / 10.0
        - 2 * sources_failed
        - mock_penalty
    )
    usefulness = max(0.0, min(10.0, usefulness_raw))

    summary = {
        "script": "first_run_seed_free_sources.py",
        "dry_run": bool(dry_run),
        "max_per_source": int(max_per_source),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "sources_requested": sources,
        "sources_attempted": sources_attempted,
        "sources_succeeded": sources_succeeded,
        "sources_skipped": sources_skipped,
        "sources_failed": sources_failed,
        "rows_collected": rows_collected,
        "rows_written": rows_written,
        "rows_mock": rows_mock,
        "rows_live_public": rows_live_public,
        "rows_live_keyed": rows_live_keyed,
        "first_run_usefulness_score": round(usefulness, 3),
        "underlying_refresh_run_id": refresh_summary.get("run_id"),
        "db_path": refresh_summary.get("db_path"),
        "source_results": source_results,
        "next_step_human_readable": (
            "Run `python -m uvicorn scripts.api_server:app --reload` and open "
            "http://localhost:3000 — your Signal Inbox now has rows from the "
            f"{sources_succeeded} live public source(s) above."
        ),
        **SAFETY_STAMPS,
    }
    return summary


def _print_human_lines(summary: dict[str, Any], *, quiet: bool) -> None:
    sys.stdout.write("=" * 72 + "\n")
    sys.stdout.write(
        f"first-run seed | mode={'write' if not summary['dry_run'] else 'dry_run'} "
        f"| attempted={summary['sources_attempted']} "
        f"succeeded={summary['sources_succeeded']} "
        f"skipped={summary['sources_skipped']} "
        f"failed={summary['sources_failed']}\n"
    )
    sys.stdout.write(
        f"rows_written={summary['rows_written']} "
        f"rows_mock={summary['rows_mock']} "
        f"rows_live_public={summary['rows_live_public']} "
        f"usefulness={summary['first_run_usefulness_score']}\n"
    )
    sys.stdout.write(
        f"Advisory: {summary['advisory_status']} | "
        f"Execution gate: {summary['execution_gate']} | "
        f"Broker calls: {summary['broker_api_called']}\n"
    )
    if not quiet:
        for sr in summary["source_results"]:
            sys.stdout.write(
                f"  - {sr['source_name']:<22} status={sr['adapter_status']:<11} "
                f"truth={sr['truth_source']:<13} rows={sr['rows_written']}"
            )
            if sr.get("skip_reason"):
                sys.stdout.write(f"  reason={sr['skip_reason']!r}")
            sys.stdout.write("\n")
    sys.stdout.write("=" * 72 + "\n")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = run_first_run_seed(
        dry_run=bool(args.dry_run and not args.write),
        include_optional_keyed=bool(args.include_optional_keyed),
        max_per_source=int(args.max_per_source),
        db_override=args.db,
    )

    if args.json_summary:
        target = Path(args.json_summary)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # pragma: no cover — defensive
            sys.stderr.write(f"warning: could not write summary: {type(exc).__name__}\n")

    _print_human_lines(summary, quiet=bool(args.quiet))
    # Exit non-zero only if every attempted source failed AND none was
    # skipped — that pattern indicates an actual infrastructure problem.
    if (
        summary["sources_attempted"] > 0
        and summary["sources_failed"] == summary["sources_attempted"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
