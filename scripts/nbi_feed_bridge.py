"""NBI feed bridge — discover, score, and wire real news-chain outputs.

Closes v1.4's "active event ran against an honest empty feed" gap by making
the feed path an explicit, measured, operator-wireable surface:

    python -m scripts.nbi_feed_bridge discover      # candidate sources
    python -m scripts.nbi_feed_bridge status        # current wiring health
    python -m scripts.nbi_feed_bridge export-latest # normalized latest rows
    python -m scripts.nbi_feed_bridge wire --source <path>
    python -m scripts.nbi_feed_bridge sample --event-id <id>

Feed usability (per candidate):

    RowCountScore = min(1, log(1+rows) / log(1+50))
    FreshnessScore = exp(-0.01 * age_hours)          (half-life ~ 69h)
    SchemaScore   = mapped_required_fields / total_required_fields
    FeedUsability = RowCountScore x FreshnessScore x SchemaScore

Required NBI fields per row: title/text, url/evidence ref, source/provider,
timestamp.  A schema without URLs fails cite-or-drop and scores 0 on that
component — rows from such a source would all be UNVERIFIED anyway.

Wiring writes ``runtime/nbi_feed_bridge_config.json``; the evidence factory
consults it before falling back to the default daily-payload file.  No
headlines are ever invented: an empty/absent feed keeps every downstream
state fail-closed exactly as before.

Advisory-only.  Read-only over data files; the only write is the config.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.runtime_common import REPO_ROOT

FEED_BRIDGE_VERSION = "nbi-feed-bridge-v1.0"

FEED_CONFIG_PATH = REPO_ROOT / "runtime" / "nbi_feed_bridge_config.json"

STATUS_NO_SOURCE = "NO_FEED_SOURCE_DISCOVERED"
STATUS_STALE = "FEED_STALE"
STATUS_READY = "FEED_READY"
STATUS_NOT_WIRED = "FEED_NOT_WIRED"

_ROW_CAP = 50
_FRESHNESS_LAMBDA_PER_HOUR = 0.01
_STALE_USABILITY_FLOOR = 0.3

# Where real news-chain outputs land in this repo today.
_CANDIDATE_GLOBS: tuple[str, ...] = (
    "data/daily_payload/today_news_events.json",
    "data/daily_payload/*news*.json",
    "data/daily_payload/*events*.json",
    "runtime/*news*.json",
)

_TITLE_KEYS = ("headline", "title", "claim_text", "text", "summary")
_URL_KEYS = ("url", "source_url", "link", "canonical_url", "article_url")
_PROVIDER_KEYS = ("provider", "source_name", "source", "api", "feed")
_TIME_KEYS = ("timestamp_utc", "published_at", "publishedAt", "seendate",
              "date", "first_seen", "dateTime")
_REQUIRED_FIELD_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("title", _TITLE_KEYS),
    ("url", _URL_KEYS),
    ("provider", _PROVIDER_KEYS),
    ("timestamp", _TIME_KEYS),
)


def _now(now_iso: str | None) -> datetime:
    if now_iso:
        parsed = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("events", "records", "rows", "articles", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
    return []


def _schema_guess(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Field-group coverage over a row sample (present AND non-empty)."""
    sample = rows[:20]
    mapped: list[str] = []
    missing: list[str] = []
    for group, keys in _REQUIRED_FIELD_GROUPS:
        hit = any(
            any(str(r.get(k) or "").strip() for k in keys) for r in sample
        )
        (mapped if hit else missing).append(group)
    return {
        "mapped_fields": mapped,
        "missing_fields": missing,
        "schema_score": (
            len(mapped) / len(_REQUIRED_FIELD_GROUPS) if sample else 0.0
        ),
    }


def score_feed_candidate(
    path: Path, *, now_iso: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "path": str(path), "usable_for_nbi": False,
            "error": type(exc).__name__, "feed_usability": 0.0,
        }
    rows = _extract_rows(payload)
    # Only rows with a real URL survive cite-or-drop downstream.
    cited_rows = [
        r for r in rows
        if any(str(r.get(k) or "").strip() for k in _URL_KEYS)
    ]
    row_count = len(cited_rows)
    row_score = (
        min(1.0, math.log1p(row_count) / math.log1p(_ROW_CAP))
        if row_count else 0.0
    )
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_hours = max(
            (_now(now_iso) - mtime).total_seconds() / 3600.0, 0.0
        )
    except OSError:
        mtime, age_hours = None, None
    freshness = (
        math.exp(-_FRESHNESS_LAMBDA_PER_HOUR * age_hours)
        if age_hours is not None else 0.0
    )
    schema = _schema_guess(rows)
    usability = row_score * freshness * schema["schema_score"]
    return {
        "path": str(path),
        "source_type": (
            "daily_payload" if "daily_payload" in str(path) else "runtime"
        ),
        "row_count": len(rows),
        "cited_row_count": row_count,
        "last_modified": mtime.isoformat() if mtime else None,
        "age_hours": round(age_hours, 2) if age_hours is not None else None,
        "schema_guess": schema,
        "required_mapping_fields": [g for g, _ in _REQUIRED_FIELD_GROUPS],
        "missing_fields": schema["missing_fields"],
        "row_count_score": round(row_score, 4),
        "freshness_score": round(freshness, 4),
        "feed_usability": round(usability, 4),
        "usable_for_nbi": usability > 0.0,
    }


def discover_feed_sources(
    *, repo_root: Path | str | None = None, now_iso: str | None = None,
) -> list[dict[str, Any]]:
    root = Path(repo_root) if repo_root else REPO_ROOT
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for pattern in _CANDIDATE_GLOBS:
        for path in sorted(root.glob(pattern)):
            key = str(path.resolve())
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            candidates.append(score_feed_candidate(path, now_iso=now_iso))
    candidates.sort(key=lambda c: -c.get("feed_usability", 0.0))
    return candidates


def wire_feed_source(
    source_path: Path | str, *,
    config_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    source = Path(source_path)
    scored = score_feed_candidate(source, now_iso=now_iso)
    if "url" in scored.get("missing_fields", []):
        return {
            "wired": False, "path": str(source),
            "error": (
                "source rows carry no URLs: cite-or-drop would mark every "
                "claim UNVERIFIED — refusing to wire an uncitable feed"
            ),
        }
    target = Path(config_path) if config_path else FEED_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "version": FEED_BRIDGE_VERSION,
        "source_path": str(source),
        "wired_at": _now(now_iso).replace(microsecond=0).isoformat(),
        "usability_at_wiring": scored.get("feed_usability"),
    }, indent=2), encoding="utf-8")
    return {"wired": True, "path": str(source), "config": str(target),
            "usability": scored.get("feed_usability")}


def wired_source_path(
    config_path: Path | str | None = None,
) -> Path | None:
    target = Path(config_path) if config_path else FEED_CONFIG_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    source = payload.get("source_path") if isinstance(payload, dict) else None
    return Path(source) if source else None


def feed_bridge_status(
    *, config_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    wired = wired_source_path(config_path)
    if wired is None:
        candidates = discover_feed_sources(now_iso=now_iso)
        return {
            "report": "nbi_feed_bridge_status",
            "version": FEED_BRIDGE_VERSION,
            "status": (
                STATUS_NOT_WIRED if candidates else STATUS_NO_SOURCE
            ),
            "wired_source": None,
            "best_candidate": candidates[0] if candidates else None,
            "candidates_found": len(candidates),
            "feed_usability": 0.0,
            "safety": advisory_safety_stamps(),
        }
    if not wired.exists():
        return {
            "report": "nbi_feed_bridge_status",
            "version": FEED_BRIDGE_VERSION,
            "status": STATUS_NO_SOURCE,
            "wired_source": str(wired),
            "error": "wired source file missing",
            "feed_usability": 0.0,
            "safety": advisory_safety_stamps(),
        }
    scored = score_feed_candidate(wired, now_iso=now_iso)
    usability = scored.get("feed_usability", 0.0)
    status = (
        STATUS_READY if usability >= _STALE_USABILITY_FLOOR else STATUS_STALE
    )
    return {
        "report": "nbi_feed_bridge_status",
        "version": FEED_BRIDGE_VERSION,
        "status": status,
        "wired_source": str(wired),
        "source_health": scored,
        "feed_usability": usability,
        "safety": advisory_safety_stamps(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI feed bridge: discover/score/wire news-chain outputs."
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("discover")
    sub.add_parser("status")
    sub.add_parser("export-latest")
    wire_p = sub.add_parser("wire")
    wire_p.add_argument("--source", required=True)
    sample_p = sub.add_parser("sample")
    sample_p.add_argument("--event-id", required=True)
    args = parser.parse_args(argv)

    if args.command == "discover":
        print(json.dumps(discover_feed_sources(), indent=2))
    elif args.command == "status":
        print(json.dumps(feed_bridge_status(), indent=2))
    elif args.command == "export-latest":
        from scripts.nbi_evidence_factory import load_feed_rows
        rows = load_feed_rows()
        print(json.dumps({
            "rows": rows if rows is not None else [],
            "available": rows is not None,
            "count": len(rows or []),
        }, indent=2))
    elif args.command == "wire":
        out = wire_feed_source(args.source)
        print(json.dumps(out, indent=2))
        return 0 if out.get("wired") else 1
    elif args.command == "sample":
        from scripts.nbi_claim_ingestion import (
            build_nbi_claims_from_news_rows,
        )
        from scripts.nbi_evidence_factory import load_feed_rows
        rows = load_feed_rows() or []
        claims = build_nbi_claims_from_news_rows(rows[:5], args.event_id)
        print(json.dumps(claims, indent=2, default=str))
    else:
        parser.print_help()
        return 2
    return 0


__all__ = [
    "FEED_BRIDGE_VERSION", "FEED_CONFIG_PATH",
    "STATUS_NO_SOURCE", "STATUS_STALE", "STATUS_READY", "STATUS_NOT_WIRED",
    "score_feed_candidate", "discover_feed_sources", "wire_feed_source",
    "wired_source_path", "feed_bridge_status", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
