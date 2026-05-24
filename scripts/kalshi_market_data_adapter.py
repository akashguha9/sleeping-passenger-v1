"""Kalshi market-data adapter — read-only, advisory-only.

Mirrors the spirit of ``scripts/polymarket_gamma_adapter.py``: a standalone
CLI that hits public market-discovery endpoints, normalises markets, and
emits either a compact human summary or a machine-readable JSON dump.
Persistence is OFF by default — use ``--write`` to opt in.

Hard non-goals (do not add):
- Trading endpoints, order placement, portfolio access, account/balance
  endpoints, fill subscriptions, authentication, API keys, or any
  POST/DELETE method.

Default command shapes::

    python scripts/kalshi_market_data_adapter.py --summary --limit 10
    python scripts/kalshi_market_data_adapter.py --json --limit 10
    python scripts/kalshi_market_data_adapter.py --write --limit 25
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.ingestion.kalshi_loader import KalshiLoader, normalize_kalshi_records
    from scripts.kalshi_normalizer import (
        CANONICAL_CATEGORIES,
        CANONICAL_SOURCE,
        classify_kalshi_category,
    )
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover
    from ingestion.kalshi_loader import KalshiLoader, normalize_kalshi_records  # type: ignore[no-redef]
    from kalshi_normalizer import (  # type: ignore[no-redef]
        CANONICAL_CATEGORIES,
        CANONICAL_SOURCE,
        classify_kalshi_category,
    )
    from runtime_common import utc_timestamp  # type: ignore[no-redef]


_ENDPOINT_NAMES = ("/markets", "/events")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Kalshi read-only market-data adapter. Public GETs only, "
            "no trading, no auth, no order placement. Default mode is "
            "dry-run + summary."
        ),
    )
    out = p.add_mutually_exclusive_group()
    out.add_argument("--summary", action="store_true", help="Compact human summary (default).")
    out.add_argument("--json", action="store_true", help="Full machine-readable JSON.")
    p.add_argument("--limit", type=int, default=25, help="Max markets to request per page (default: 25).")
    p.add_argument("--max-pages", type=int, default=3, help="Max pages to walk (default: 3).")
    p.add_argument(
        "--write",
        action="store_true",
        help="Persist approved Kalshi rows to canonical SQLite (signal_events). Off by default.",
    )
    p.add_argument(
        "--mock",
        action="store_true",
        help="Use in-process mock fixtures instead of hitting the network.",
    )
    return p


def _build_report(
    *,
    accepted: list[dict[str, Any]],
    raw_records: list[dict[str, Any]],
    fetched_at: str,
    persisted: int,
    write_mode: bool,
    is_mock: bool,
    event_lookup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from scripts.kalshi_normalizer import infer_kalshi_category

    accepted_categories = Counter(
        str(rec.get("category") or "") for rec in accepted
    )
    accepted_sources = Counter(
        str(rec.get("category_source") or "explicit_category") for rec in accepted
    )
    rejected_summary: dict[str, int] = Counter()
    rejection_reasons: dict[str, int] = Counter()
    rejected_sample_titles: list[str] = []
    for rec in raw_records:
        # First-pass: explicit category match.
        explicit = classify_kalshi_category(rec.get("category"), tags=rec.get("tags"))
        if explicit["allowed"]:
            continue
        # Second-pass: evidence-based inference (what the normalizer
        # actually applies).  Anything that fails this pass is the real
        # rejection set.
        cat, reason = infer_kalshi_category(rec, event_lookup=event_lookup)
        if cat is not None:
            continue  # picked up by inference — counted as accepted via the normalizer
        raw_key = explicit["raw_category"] or "<missing>"
        rejected_summary[raw_key] += 1
        rejection_reasons[reason] += 1
        title = str(rec.get("title") or "").strip()
        if title and len(rejected_sample_titles) < 5:
            rejected_sample_titles.append(title)

    sample = [
        {
            "event_id": rec["event_id"],
            "category": rec["category"],
            "category_source": rec.get("category_source"),
            "category_reason": rec.get("category_reason"),
            "title": rec["title"],
            "implied_probability": rec.get("implied_probability"),
            "source": rec["source"],
            "source_label": rec["source_label"],
            "advisory_status": rec["advisory_status"],
            "execution_permission": rec["execution_permission"],
            "execution_gate": rec["execution_gate"],
            "broker_api_called": rec["broker_api_called"],
            "ai_execution_count": rec["ai_execution_count"],
        }
        for rec in accepted[:5]
    ]
    return {
        "artifact_kind": "kalshi_market_data_report",
        "source_name": CANONICAL_SOURCE,
        "source_label": "Kalshi",
        "fetched_at": fetched_at,
        "is_mock_run": is_mock,
        "auth_required": False,
        "endpoints_used": list(_ENDPOINT_NAMES),
        "fetched_count": len(raw_records),
        "accepted_count": len(accepted),
        "rejected_count": len(raw_records) - len(accepted),
        "events_persisted": persisted,
        "write_mode": write_mode,
        "allowed_categories": list(CANONICAL_CATEGORIES),
        "accepted_categories": dict(accepted_categories),
        "accepted_category_sources": dict(accepted_sources),
        "rejected_categories": dict(rejected_summary),
        "rejected_category_reasons": dict(rejection_reasons),
        "rejected_sample_titles": rejected_sample_titles,
        "sample": sample,
        "read_only_contract": {
            "advisory_status": "ADVISORY_ONLY",
            "execution_permission": "ADVISORY_ONLY",
            "execution_gate": "LOCKED",
            "human_review_required": True,
            "broker_api_called": False,
            "ai_execution_count": 0,
            "trading_endpoints_called": False,
            "auth_headers_sent": False,
        },
        "note": (
            "Kalshi adapter is read-only: only public market-discovery "
            "endpoints are called. Trading, portfolio, account, order, "
            "and authenticated endpoints are intentionally not wired. "
            "Resolution terms may differ across venues — review required."
        ),
    }


def _format_summary(report: dict[str, Any]) -> str:
    accepted_lines = "\n".join(
        f"  - {cat}: {n}"
        for cat, n in sorted(report["accepted_categories"].items())
    ) or "  (none)"
    rejected_lines = "\n".join(
        f"  - {cat}: {n}"
        for cat, n in sorted(report["rejected_categories"].items())
    ) or "  (none)"
    sources = report.get("accepted_category_sources") or {}
    sources_line = ", ".join(
        f"{src}={n}" for src, n in sorted(sources.items())
    ) or "(none)"
    reasons = report.get("rejected_category_reasons") or {}
    reason_lines = "\n".join(
        f"  - {r}: {n}" for r, n in sorted(reasons.items())
    ) or "  (none)"
    rejected_titles = report.get("rejected_sample_titles") or []
    sample_lines = "\n".join(
        f"  - {t[:80]}" for t in rejected_titles
    ) or "  (none)"
    return "\n".join(
        [
            "Kalshi market-data adapter (read-only, advisory-only)",
            f"  fetched_at:        {report['fetched_at']}",
            f"  is_mock_run:       {report['is_mock_run']}",
            f"  auth_required:     {report['auth_required']}",
            f"  endpoints_used:    {', '.join(report['endpoints_used'])}",
            f"  fetched_count:     {report['fetched_count']}",
            f"  accepted_count:    {report['accepted_count']}",
            f"  rejected_count:    {report['rejected_count']}",
            f"  events_persisted:  {report['events_persisted']}",
            f"  write_mode:        {report['write_mode']}",
            "  accepted_categories:",
            accepted_lines,
            f"  accepted_category_sources: {sources_line}",
            "  rejected_categories:",
            rejected_lines,
            "  rejected_category_reasons:",
            reason_lines,
            "  rejected_sample_titles:",
            sample_lines,
            "  read-only contract: ADVISORY_ONLY | HUMAN_REVIEW_REQUIRED | "
            "execution_gate=LOCKED | broker_api_called=False | ai_execution_count=0",
        ]
    )


def _persist_signal_events(events: list[dict[str, Any]], fetched_at: str) -> int:
    try:
        try:
            from scripts.persistence import insert_signal_event
        except ModuleNotFoundError:
            from persistence import insert_signal_event  # type: ignore[no-redef]
    except Exception:
        return 0
    count = 0
    for ev in events:
        try:
            inserted = insert_signal_event(
                event_id=ev["event_id"],
                source_name=CANONICAL_SOURCE,
                raw_payload=ev,
                fetched_at=fetched_at,
            )
            if inserted:
                count += 1
        except Exception:
            pass
    return count


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    loader = KalshiLoader(
        limit=args.limit,
        max_pages=args.max_pages,
        use_mock_fixtures=args.mock or None,
    )
    fetched_at = utc_timestamp()
    loader_result = loader.safe_fetch()

    if loader_result.skipped:
        skipped_report = {
            "artifact_kind": "kalshi_market_data_report",
            "source_name": CANONICAL_SOURCE,
            "fetched_at": fetched_at,
            "status": "skipped",
            "skip_reason": loader_result.skip_reason,
            "auth_required": False,
            "endpoints_used": list(_ENDPOINT_NAMES),
            "events_persisted": 0,
            "write_mode": args.write,
            "read_only_contract": {
                "advisory_status": "ADVISORY_ONLY",
                "execution_permission": "ADVISORY_ONLY",
                "execution_gate": "LOCKED",
                "human_review_required": True,
                "broker_api_called": False,
                "ai_execution_count": 0,
            },
        }
        if args.json:
            print(json.dumps(skipped_report, indent=2))
        else:
            print("Kalshi adapter skipped: " + loader_result.skip_reason)
        return 0

    event_lookup = getattr(loader, "last_event_lookup", None) or {}
    accepted = normalize_kalshi_records(
        loader_result.records,
        fetched_at_utc=fetched_at,
        event_lookup=event_lookup,
    )
    persisted = 0
    if args.write:
        persisted = _persist_signal_events(accepted, fetched_at)

    is_mock = any(rec.get("is_mock_fixture") for rec in loader_result.records)
    report = _build_report(
        accepted=accepted,
        raw_records=loader_result.records,
        fetched_at=fetched_at,
        persisted=persisted,
        write_mode=args.write,
        is_mock=is_mock,
        event_lookup=event_lookup,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_summary(report))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(run())
