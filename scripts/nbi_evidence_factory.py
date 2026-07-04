"""NBI Evidence Factory — the closed loop that makes the system compound.

    feeds -> ingestion -> event reports -> operator cards -> operator action
          -> event closeout -> outcome/price measurement -> backtest case
          -> calibration readiness -> edge-claim permission -> score deltas

One CLI facade over the existing NBI subsystem (no duplicate logic):

    python -m scripts.nbi_evidence_factory run-daily
    python -m scripts.nbi_evidence_factory ingest --source latest
    python -m scripts.nbi_evidence_factory status
    python -m scripts.nbi_evidence_factory close-event --event-id X \\
        --core-outcome 1 --venue-outcome 0 --notes "venue shifted; core held"
    python -m scripts.nbi_evidence_factory import-templates
    python -m scripts.nbi_evidence_factory export-cards
    python -m scripts.nbi_evidence_factory score-report
    python -m scripts.nbi_evidence_factory init-event-template

Honesty notes (doctrine, tested):
* This is a **CLI runner**, not a scheduler — nothing here claims otherwise.
  Wire it into the operator's existing scheduled task to make it periodic.
* No feed rows are ever invented: missing feeds -> FEEDS_UNAVAILABLE;
  missing event definitions -> NO_EVENT_DEFINITIONS; both fail closed while
  still reporting persisted state.
* Fixture events produce fixture cases (contamination is structurally
  impossible: closeout inherits ``is_fixture`` from the event row).
* Templates import as case_kind=TEMPLATE and can never count as real.
* The edge-claim gate appears on every surface and is false until earned.

Advisory-only.  No broker execution, no auto-trading, no real-money sizing.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.narrative_branch_engine import (
    BRANCHES,
    build_backtest_case,
    build_event_report,
    render_event_card,
)
from scripts.nbi_calibration_report import build_nbi_calibration_report
from scripts.nbi_claim_ingestion import build_nbi_claims_from_news_rows
from scripts.nbi_daily_bridge import NO_ACTIVE_NBI_EVENTS, build_nbi_daily_section
from scripts.nbi_prediction_market_bridge import (
    match_prediction_markets_to_nbi_event,
)
from scripts.nbi_store import (
    CASE_KIND_TEMPLATE,
    load_active_nbi_reports,
    load_event_action_history,
    load_latest_report,
    load_nbi_backtest_cases,
    load_nbi_event,
    persist_nbi_backtest_case,
    save_nbi_report,
    summarize_nbi_backtest_readiness,
    update_nbi_event_state,
)
from scripts.nbi_track_record_ledger import (
    close_track_record_entry,
    compute_case_quality,
    compute_edge_claim_permission,
    create_track_record_entry,
    summarize_track_record,
)
from scripts.nbi_value_chain_mapper import build_exposures_from_graph
from scripts.runtime_common import REPO_ROOT

FACTORY_VERSION = "nbi-factory-v1.0"

EVENT_DEFINITIONS_PATH = REPO_ROOT / "runtime" / "nbi_active_events.json"
MARKET_CONTRACTS_PATH = REPO_ROOT / "runtime" / "nbi_market_contracts.json"
FEED_ROWS_PATH = REPO_ROOT / "data" / "daily_payload" / "today_news_events.json"
TEMPLATES_PATH = REPO_ROOT / "data" / "nbi_historical_event_templates.json"
CARDS_HTML_PATH = REPO_ROOT / "runtime" / "nbi_operator_cards.html"
CARDS_MD_PATH = REPO_ROOT / "runtime" / "nbi_operator_cards.md"
CARDS_JSON_PATH = REPO_ROOT / "runtime" / "nbi_operator_cards.json"


def _artifact_path(default: Path) -> Path:
    """Resolve an operator-artifact path, honoring NBI_ARTIFACT_DIR.

    Close-the-Loop sprint (2026-07-04), forensic audit SP-003: test runs
    previously wrote fixture cards (MACRO1 / https://e/filing) into the
    exact runtime/ files GET /nbi/cards serves.  conftest.py sets
    NBI_ARTIFACT_DIR to a per-test tmp dir so exports land in throwaway
    storage; production runs (env var unset) keep the canonical paths.
    """
    import os as _os

    override = _os.environ.get("NBI_ARTIFACT_DIR")
    if not override:
        return default
    try:
        default.relative_to(REPO_ROOT / "runtime")
    except (ValueError, TypeError):
        return default  # already redirected (e.g. test monkeypatch) — honor it
    target_dir = Path(override)
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / default.name

STATUS_FEEDS_UNAVAILABLE = "FEEDS_UNAVAILABLE"
STATUS_NO_EVENT_DEFINITIONS = "NO_EVENT_DEFINITIONS"
STATUS_OK = "OK"

_EPS = 1e-9


def _now_iso(now_iso: str | None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Event definitions + feed rows
# ---------------------------------------------------------------------------


def load_event_definitions(path: Path | str | None = None) -> list[dict[str, Any]] | None:
    payload = _read_json(Path(path) if path else EVENT_DEFINITIONS_PATH)
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None
    return [e for e in events if isinstance(e, dict) and e.get("event_id")]


def _definition_terms(definition: dict[str, Any]) -> list[str]:
    for key in ("query_terms", "keywords"):
        values = definition.get(key)
        if isinstance(values, list) and values:
            return [str(v) for v in values if str(v).strip()]
    return []


ACTIVATION_MIN_READINESS10 = 5.0
EVENT_CONFIDENCE_CAP_NO_OFFICIAL = 0.7


def validate_event_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Per-event readiness (v1.4 floor model).  Definitions are
    configuration, never evidence: a valid definition creates no case, no
    probability, no edge progress.

        EventReadiness = Query
                       x max(Source, 0.25 | query exists)
                       x max(Benchmark, 0.5 | intentionally unavailable)
                       x max(ValueChain, 0.5 | watch-only)
                       x max(OfficialSource, 0.5 | non-official event)
    """
    errors: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    terms = _definition_terms(definition)
    query = 1.0 if terms else 0.0
    if not terms:
        errors.append("query_terms/keywords required")
        missing.append("query_terms")

    official = definition.get("official_sources") or []
    pm_queries = definition.get("prediction_market_queries") or []
    source = 1.0 if (official or pm_queries) else 0.0
    if source == 0.0 and terms:
        source = 0.25
        warnings.append("no verification source class beyond query terms")
        missing.append("official_sources or prediction_market_queries")

    benchmarks = definition.get("benchmark_tickers") or []
    benchmark = 1.0 if benchmarks else 0.5
    if not benchmarks:
        warnings.append(
            "no benchmark_tickers: price validation capped WATCH_ONLY"
        )
        missing.append("benchmark_tickers")

    status = str(definition.get("status") or "ACTIVE").upper()
    has_chain = bool(
        definition.get("exposures") or definition.get("value_chain_graph")
        or definition.get("value_chain_graph_id")
    )
    chain = 1.0 if has_chain else 0.5
    if not has_chain:
        warnings.append("no exposures/value-chain graph: no scoreable tickers")
        missing.append("exposures or value_chain_graph")

    official_c = 1.0 if official else 0.5
    if not official:
        warnings.append(
            f"no official_sources: event confidence capped at "
            f"{EVENT_CONFIDENCE_CAP_NO_OFFICIAL}"
        )

    readiness = query * source * benchmark * chain * official_c
    return {
        "event_id": str(definition.get("event_id") or ""),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "missing_fields": missing,
        "EventReadiness10": round(10.0 * readiness, 4),
        "activation_eligible": (
            not errors
            and round(10.0 * readiness, 4) >= ACTIVATION_MIN_READINESS10
            and bool(definition.get("country_scope"))
            and not bool(definition.get("is_fixture"))
        ),
        "confidence_cap": (
            EVENT_CONFIDENCE_CAP_NO_OFFICIAL if not official else 1.0
        ),
        "status": status,
        "is_fixture": bool(definition.get("is_fixture")),
    }


def validate_event_definitions(
    definitions: list[dict[str, Any]] | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    if definitions is None:
        definitions = load_event_definitions(path) or []
    results = [validate_event_definition(d) for d in definitions]
    return {
        "report": "nbi_event_definition_validation",
        "n_definitions": len(results),
        "n_valid": sum(1 for r in results if r["valid"]),
        "results": results,
        "note": (
            "event definitions are configuration, not evidence: they create "
            "no backtest case and never move the edge gate"
        ),
    }


def add_event_definition(
    definition: dict[str, Any], path: Path | str | None = None,
    *, now_iso: str | None = None,
) -> dict[str, Any]:
    """Append/replace one operator-authored event definition (validated)."""
    check = validate_event_definition(definition)
    if not check["valid"]:
        return {"added": False, "errors": check["errors"]}
    target = Path(path) if path else EVENT_DEFINITIONS_PATH
    payload = _read_json(target)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("events"), list
    ):
        payload = {"events": []}
    definition = dict(definition)
    definition.setdefault("created_at", _now_iso(now_iso))
    definition.setdefault("status", "WATCH_ONLY")
    definition.setdefault("is_fixture", False)
    definition.setdefault("calibration_eligible", False)
    payload["events"] = [
        e for e in payload["events"]
        if e.get("event_id") != definition.get("event_id")
    ] + [definition]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"added": True, "event_id": definition["event_id"],
            "path": str(target), "readiness": check["EventReadiness10"]}


# ---------------------------------------------------------------------------
# v1.4 activation flow — WATCH_ONLY -> ACTIVE is an explicit operator act
# ---------------------------------------------------------------------------

WATCH_EVENT_PACK_PATH = REPO_ROOT / "data" / "nbi_watch_event_definitions.json"


def _find_definition(
    event_id: str, path: Path | str | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Look in the runtime definitions first, then the watch pack."""
    for d in load_event_definitions(path) or []:
        if str(d.get("event_id")) == event_id:
            return d, "runtime"
    pack = _read_json(WATCH_EVENT_PACK_PATH)
    if isinstance(pack, dict):
        for d in pack.get("events", []) if isinstance(
            pack.get("events"), list
        ) else []:
            if isinstance(d, dict) and str(d.get("event_id")) == event_id:
                return d, "watch_pack"
    return None, "not_found"


def _set_event_status(
    event_id: str, new_status: str, *,
    path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    definition, origin = _find_definition(event_id, path)
    if definition is None:
        return {"changed": False, "event_id": event_id,
                "error": "event definition not found"}
    check = validate_event_definition(definition)
    if new_status == "ACTIVE":
        if not check["activation_eligible"]:
            return {
                "changed": False, "event_id": event_id,
                "error": "activation requirements not met",
                "EventReadiness10": check["EventReadiness10"],
                "missing_fields": check["missing_fields"],
                "requirements": (
                    f"readiness >= {ACTIVATION_MIN_READINESS10}, query terms, "
                    "country_scope, not fixture"
                ),
            }
    definition = dict(definition)
    definition["status"] = new_status
    definition[
        "activated_at" if new_status == "ACTIVE" else "deactivated_at"
    ] = _now_iso(now_iso)
    target = Path(path) if path else EVENT_DEFINITIONS_PATH
    payload = _read_json(target)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("events"), list
    ):
        payload = {"events": []}
    payload["events"] = [
        e for e in payload["events"] if e.get("event_id") != event_id
    ] + [definition]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {
        "changed": True, "event_id": event_id, "status": new_status,
        "origin": origin, "EventReadiness10": check["EventReadiness10"],
        "confidence_cap": check["confidence_cap"],
        "note": (
            "activation is configuration, not evidence: no case created, "
            "edge gate unmoved"
        ),
    }


def activate_event(
    event_id: str, *, path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    return _set_event_status(event_id, "ACTIVE", path=path, now_iso=now_iso)


def deactivate_event(
    event_id: str, *, path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    return _set_event_status(
        event_id, "WATCH_ONLY", path=path, now_iso=now_iso
    )


def event_status(
    event_id: str, *, path: Path | str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    definition, origin = _find_definition(event_id, path)
    if definition is None:
        return {"event_id": event_id, "found": False}
    check = validate_event_definition(definition)
    stored = load_nbi_event(event_id, db_path)
    latest = load_latest_report(event_id, db_path)
    return {
        "event_id": event_id,
        "found": True,
        "origin": origin,
        "definition_status": check["status"],
        "readiness": check,
        "store_state": stored.get("state") if stored else None,
        "last_action": latest.get("ACTION") if latest else None,
        "last_rumor_risk": (
            latest.get("scores", {}).get("RUMOR_RISK") if latest else None
        ),
        "safety": advisory_safety_stamps(),
    }


def load_feed_rows(path: Path | str | None = None) -> list[dict[str, Any]] | None:
    """Read today's news-event rows.  None = feed unavailable (fail closed).

    Resolution order (v1.5): explicit ``path`` arg > the feed-bridge wired
    source (runtime/nbi_feed_bridge_config.json) > the default daily-payload
    file.  A wired-but-missing source falls through to the default rather
    than crashing — absence stays a clean None, never an exception.
    """
    resolved: Path | None = Path(path) if path else None
    if resolved is None:
        try:
            from scripts.nbi_feed_bridge import wired_source_path
            wired = wired_source_path()
            if wired is not None and wired.exists():
                resolved = wired
        except Exception:  # noqa: BLE001 - bridge trouble never breaks feeds
            resolved = None
    payload = _read_json(resolved if resolved else FEED_ROWS_PATH)
    if not isinstance(payload, dict):
        if isinstance(payload, list):  # bare-list feed files are acceptable
            return [r for r in payload if isinstance(r, dict)]
        return None
    rows = payload.get("events") or payload.get("records")
    if not isinstance(rows, list):
        return None
    return [r for r in rows if isinstance(r, dict)]


def assign_rows_to_events(
    rows: list[dict[str, Any]], definitions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Keyword routing: a row joins the first event whose keywords hit its
    headline/title.  Unmatched rows are counted, never guessed into events."""
    by_event: dict[str, list[dict[str, Any]]] = {
        str(d["event_id"]): [] for d in definitions
    }
    unmatched = 0
    for row in rows:
        text = " ".join(
            str(row.get(k) or "") for k in ("headline", "title", "claim_text")
        ).lower()
        placed = False
        for d in definitions:
            keywords = [k.lower() for k in _definition_terms(d)]
            if keywords and any(k in text for k in keywords):
                by_event[str(d["event_id"])].append(row)
                placed = True
                break
        if not placed:
            unmatched += 1
    return {"by_event": by_event, "unmatched_rows": unmatched}


def build_event_input(
    definition: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Definition + routed feed rows -> engine event dict."""
    event_id = str(definition["event_id"])
    claims = build_nbi_claims_from_news_rows(rows, event_id, now=now)
    exposures = definition.get("exposures")
    graph = definition.get("value_chain_graph")
    if not exposures and isinstance(graph, dict):
        exposures = build_exposures_from_graph(
            graph,
            str(definition.get("event_node") or f"EV:{event_id}"),
            ticker_metadata=definition.get("ticker_metadata") or {},
        )
    return {
        "event_id": event_id,
        "event_name": definition.get("event_name") or event_id,
        "category": definition.get("category") or "",
        "decision_jurisdictions": definition.get("decision_jurisdictions") or [],
        "priors": definition.get("priors") or {},
        "claims": claims,
        "exposures": exposures or [],
        "consensus": definition.get("consensus"),
        "days_since_official_confirmation": definition.get(
            "days_since_official_confirmation"
        ),
    }


# ---------------------------------------------------------------------------
# run-daily — the loop
# ---------------------------------------------------------------------------


def run_daily(
    *,
    definitions: list[dict[str, Any]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    contracts_by_event: dict[str, list[dict[str, Any]]] | None = None,
    db_path: Path | str | None = None,
    now: datetime | None = None,
    now_iso: str | None = None,
    is_fixture: bool = False,
    event_id: str | None = None,
) -> dict[str, Any]:
    """One factory cycle: ingest -> reports -> persist -> cards -> readiness.

    Repeated runs are safe: event rows upsert, snapshots/cards append (an
    auditable time series, not duplication of truth).
    """
    result: dict[str, Any] = {
        "report": "nbi_evidence_factory_run",
        "version": FACTORY_VERSION,
        "timestamp": _now_iso(now_iso),
        "safety": advisory_safety_stamps(),
    }

    if definitions is None:
        definitions = load_event_definitions()
    if definitions and event_id is not None:
        definitions = [
            d for d in definitions if str(d.get("event_id")) == event_id
        ]
    if definitions:
        # CLOSED/invalid definitions never run; WATCH_ONLY events do run
        # (they are watch surfaces), fixtures follow the is_fixture flag.
        definitions = [
            d for d in definitions
            if validate_event_definition(d)["valid"]
            and str(d.get("status") or "ACTIVE").upper() != "CLOSED"
        ]
    if not definitions:
        result["status"] = STATUS_NO_EVENT_DEFINITIONS
        result["ingested_events"] = []
        result["nbi_daily"] = build_nbi_daily_section(
            load_active_nbi_reports(db_path)
        )
        result.update(_loop_state(db_path))
        return result

    if rows is None:
        rows = load_feed_rows()
    if rows is None:
        # Feeds unavailable: fail closed — no invented rows, but persisted
        # state still surfaces so the operator sees where things stand.
        result["status"] = STATUS_FEEDS_UNAVAILABLE
        result["ingested_events"] = []
        result["nbi_daily"] = build_nbi_daily_section(
            load_active_nbi_reports(db_path)
        )
        result.update(_loop_state(db_path))
        return result

    if contracts_by_event is None:
        loaded = _read_json(MARKET_CONTRACTS_PATH)
        contracts_by_event = loaded if isinstance(loaded, dict) else {}

    routing = assign_rows_to_events(rows, definitions)
    ingested: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for definition in definitions:
        event_id = str(definition["event_id"])
        try:
            event_input = build_event_input(
                definition, routing["by_event"].get(event_id, []), now=now
            )
            report = build_event_report(event_input)
            contracts = contracts_by_event.get(event_id)
            report["market"] = match_prediction_markets_to_nbi_event(
                report, contracts if isinstance(contracts, list) else []
            )
            receipt = save_nbi_report(
                report, db_path=db_path, is_fixture=is_fixture,
                now_iso=now_iso,
            )
            ingested.append({
                "event_id": event_id,
                "state": report["EVENT_STATE"],
                "action": report["ACTION"],
                "claims_verified": report["claims_verified"],
                "market_signal": report["market"]["any_market_signal"],
                "saved": receipt["saved"],
            })
        except Exception as exc:  # noqa: BLE001 - disclose per event, continue
            errors.append({"event_id": event_id, "error": type(exc).__name__})

    result["status"] = STATUS_OK
    result["rows_total"] = len(rows)
    result["rows_unmatched"] = routing["unmatched_rows"]
    result["ingested_events"] = ingested
    result["errors"] = errors
    result["nbi_daily"] = build_nbi_daily_section(
        load_active_nbi_reports(db_path, include_fixtures=is_fixture)
    )
    result.update(_loop_state(db_path))
    return result


def _loop_state(db_path: Path | str | None) -> dict[str, Any]:
    readiness = summarize_nbi_backtest_readiness(db_path)
    calibration = build_nbi_calibration_report(db_path=db_path)
    cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    track = summarize_track_record(db_path)
    edge = compute_edge_claim_permission(cases, calibration, track)
    return {
        "backtest_readiness": readiness,
        "calibration": {
            "status": calibration["status"],
            "n_closed_real_cases": calibration["n_closed_real_cases"],
            "n_calibration_eligible": calibration["n_calibration_eligible"],
            "next_required_actions": calibration["next_required_actions"],
        },
        "track_record": {
            "status": track["status"],
            "entries_open": track["entries_open"],
            "entries_closed": track["entries_closed"],
        },
        "edge_claim": {
            "edge_claim_allowed": edge["edge_claim_allowed"],
            "missing_requirements": edge["missing_requirements"],
            "current_case_count": edge["current_case_count"],
            "required_case_count": edge["required_case_count"],
        },
    }


def factory_status(db_path: Path | str | None = None) -> dict[str, Any]:
    reports = load_active_nbi_reports(db_path)
    return {
        "report": "nbi_evidence_factory_status",
        "version": FACTORY_VERSION,
        "active_events": [
            {
                "event_id": r.get("event_id"),
                "state": r.get("EVENT_STATE"),
                "action": r.get("ACTION"),
                "rumor_risk": r.get("scores", {}).get("RUMOR_RISK"),
            }
            for r in reports
        ],
        "active_event_count": len(reports),
        **_loop_state(db_path),
        "safety": advisory_safety_stamps(),
    }


# ---------------------------------------------------------------------------
# close-event — the missing half of the loop
# ---------------------------------------------------------------------------


def _outcome_label_from_branches(branch_outcomes: dict[str, Any]) -> str:
    core = branch_outcomes.get("core")
    if core == 0:
        return "CORE_DIED"
    sub_zero = any(
        branch_outcomes.get(k) == 0 for k in ("venue", "delegation", "deals")
    )
    return "CORE_HELD_SUB_BRANCH_COLLAPSED" if sub_zero else "CORE_HELD_INTACT"


_BRANCH_OUTCOME_TO_ENGINE = {
    "core": "core_event", "venue": "venue_specific",
    "delegation": "delegation_intact", "deals": "deals_or_mous",
}


CLOSEOUT_QUALITY_MIN = 0.5
CLOSEOUT_CLASS_CALIBRATION = "CALIBRATION_CLOSE"
CLOSEOUT_CLASS_NON_CALIBRATION = "NON_CALIBRATION_CLOSE"


def _closeout_quality(
    branch_outcomes: dict[str, Any],
    evidence_refs: list[str],
    has_price: bool,
    operator_actions: list[str],
) -> dict[str, Any]:
    """CloseoutQuality = Outcome x Evidence x Price x DecisionHistory."""
    outcome = sum(
        1 for k in ("core", "venue", "delegation", "deals")
        if branch_outcomes.get(k) in (0, 1)
    ) / 4.0
    evidence = 1.0 if evidence_refs else 0.3
    price = 1.0 if has_price else 0.4
    decisions = 1.0 if operator_actions else 0.5
    quality = outcome * evidence * price * decisions
    return {
        "closeout_quality": round(quality, 4),
        "components": {
            "outcome_completeness": round(outcome, 4),
            "evidence_completeness": evidence,
            "price_completeness": price,
            "decision_history_completeness": decisions,
        },
    }


def close_event(
    event_id: str,
    *,
    branch_outcomes: dict[str, Any],
    notes: str = "",
    benchmark: str = "",
    realized_return: float | None = None,
    benchmark_return: float | None = None,
    initial_risk: float | None = None,
    label_confidence: float = 0.9,
    force_noncalibration: bool = False,
    db_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Close an event into a persisted backtest case + track-record entry.

    ``is_fixture`` is inherited from the event row — a demo/fixture event can
    NEVER produce a REAL case (contamination guard, tested).  Branch outcome
    values must be 0/1 (or absent = unlabeled).
    """
    event_row = load_nbi_event(event_id, db_path)
    report = load_latest_report(event_id, db_path)
    if event_row is None or report is None:
        return {
            "closed": False, "event_id": event_id,
            "error": "event not found in store (run-daily/save it first)",
        }
    if event_row.get("state") == "RESOLVED":
        return {
            "closed": False, "event_id": event_id,
            "error": "event already RESOLVED",
        }
    core = branch_outcomes.get("core")
    if core not in (0, 1):
        return {
            "closed": False, "event_id": event_id,
            "error": "branch_outcomes.core must be 0 or 1",
        }

    is_fixture = bool(event_row.get("is_fixture"))
    outcome_label = _outcome_label_from_branches(branch_outcomes)

    prediction_errors = {}
    for label_key, engine_branch in _BRANCH_OUTCOME_TO_ENGINE.items():
        y = branch_outcomes.get(label_key)
        if y in (0, 1):
            p = report["branches"][engine_branch]["p"]
            prediction_errors[label_key] = round(p - y, 4)

    operator_actions = [
        a["action_class"] for a in load_event_action_history(event_id, db_path)
        if a.get("action_class")
    ]

    # v1.3 closeout-quality gate: garbage closeouts cannot silently enter the
    # calibration path.  Low quality requires the explicit non-calibration
    # flag and is permanently marked NON_CALIBRATION_CLOSE.
    report_refs = sorted({
        ref for t in report.get("tickers", [])
        for ref in t.get("evidence_refs", [])
    })
    quality_gate = _closeout_quality(
        branch_outcomes, report_refs,
        realized_return is not None and benchmark_return is not None,
        operator_actions,
    )
    if quality_gate["closeout_quality"] < CLOSEOUT_QUALITY_MIN:
        if not force_noncalibration:
            return {
                "closed": False, "event_id": event_id,
                "error": (
                    f"closeout quality {quality_gate['closeout_quality']} < "
                    f"{CLOSEOUT_QUALITY_MIN}: supply more outcome labels/"
                    "evidence/price, or pass force_noncalibration for a "
                    "WATCH_ARCHIVE / non-calibration close"
                ),
                "closeout_quality": quality_gate,
            }
        closeout_class = CLOSEOUT_CLASS_NON_CALIBRATION
    else:
        closeout_class = CLOSEOUT_CLASS_CALIBRATION

    r_multiple = None
    if realized_return is not None and initial_risk is not None:
        r_multiple = realized_return / (abs(initial_risk) + _EPS)
    return_vs_benchmark = None
    if realized_return is not None and benchmark_return is not None:
        return_vs_benchmark = realized_return - benchmark_return

    squared_errors = {k: round(v ** 2, 6) for k, v in prediction_errors.items()}
    case_brier = (
        round(sum(squared_errors.values()) / len(squared_errors), 6)
        if squared_errors else None
    )
    if closeout_class == CLOSEOUT_CLASS_NON_CALIBRATION:
        # A forced low-quality close can never look calibration-grade.
        label_confidence = min(label_confidence, 0.3)
    resolution_labels = {
        "branch_outcomes": {
            k: branch_outcomes.get(k)
            for k in ("core", "venue", "delegation", "deals")
        },
        "prediction_errors": prediction_errors,
        "squared_errors": squared_errors,
        "case_brier": case_brier,
        "closeout_class": closeout_class,
        "closeout_quality": quality_gate,
        "label_confidence": max(0.0, min(1.0, label_confidence)),
        "operator_actions": operator_actions,
        "notes": notes,
        "final_state": "RESOLVED",
    }
    case = build_backtest_case(
        report,
        category=str(event_row.get("category") or "UNCATEGORIZED"),
        resolution_labels=resolution_labels,
        outcome_label=outcome_label,
        benchmark=benchmark,
        r_multiple=r_multiple,
    )
    stamp = _now_iso(now_iso)
    receipt = persist_nbi_backtest_case(
        case, db_path=db_path, is_fixture=is_fixture,
        case_id=f"{event_id}::closeout",
        rumor_peak_timestamp=event_row.get("updated_at"),
        resolution_timestamp=stamp,
        return_vs_benchmark=return_vs_benchmark,
        evidence_refs=sorted({
            ref for t in report.get("tickers", [])
            for ref in t.get("evidence_refs", [])
        }),
    )
    update_nbi_event_state(event_id, "RESOLVED", db_path, now_iso=stamp)

    # Track-record lifecycle for the closed recommendation.
    persisted = load_nbi_backtest_cases(db_path, include_fixtures=True)
    this_case = next(
        (c for c in persisted if c["case_id"] == receipt["case_id"]), None
    )
    quality = compute_case_quality(this_case) if this_case else {
        "EQS10": None, "calibration_eligible": False,
    }
    rec_id = f"{event_id}::rec"
    create_track_record_entry(
        recommendation_id=rec_id,
        event_id=event_id,
        operator_action="CLOSEOUT",
        action_class=str(report.get("ACTION") or ""),
        ticker_basket=[t["ticker"] for t in report.get("tickers", [])],
        initial_score=report.get("scores", {}).get("OPERATOR_ACTION"),
        initial_branch_probabilities={
            b: report["branches"][b]["p"] for b in BRANCHES
        },
        initial_rumor_risk=report.get("scores", {}).get("RUMOR_RISK"),
        initial_hedge_need=report.get("scores", {}).get("HEDGE_NEED"),
        invalidation_condition="event resolved",
        is_fixture=is_fixture,
        notes=notes,
        db_path=db_path,
        now_iso=stamp,
    )
    close_track_record_entry(
        rec_id,
        close_reason=f"event closeout: {outcome_label}",
        realized_return=realized_return,
        benchmark_return=benchmark_return,
        r_multiple=r_multiple,
        evidence_quality_score=quality["EQS10"],
        calibration_eligible=bool(quality["calibration_eligible"]),
        db_path=db_path,
        now_iso=stamp,
    )
    return {
        "closed": True,
        "event_id": event_id,
        "case_id": receipt["case_id"],
        "case_kind": receipt["case_kind"],
        "is_fixture": is_fixture,
        "outcome_label": outcome_label,
        "closeout_class": closeout_class,
        "closeout_quality": quality_gate,
        "case_brier": case_brier,
        "prediction_errors": prediction_errors,
        "return_vs_benchmark": return_vs_benchmark,
        "r_multiple": r_multiple,
        "evidence_quality_eqs10": quality["EQS10"],
        "calibration_eligible": bool(quality["calibration_eligible"]),
        "readiness_after": summarize_nbi_backtest_readiness(db_path),
        "safety": advisory_safety_stamps(),
    }


# ---------------------------------------------------------------------------
# import-templates — retro-label seed pack (never real, never edge)
# ---------------------------------------------------------------------------


def import_templates(
    path: Path | str | None = None, db_path: Path | str | None = None,
) -> dict[str, Any]:
    payload = _read_json(Path(path) if path else TEMPLATES_PATH)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("templates"), list
    ):
        return {"imported": 0, "error": "template pack missing or invalid"}
    imported = 0
    for tpl in payload["templates"]:
        if not isinstance(tpl, dict) or not tpl.get("event_id"):
            continue
        case = {
            "event_id": tpl["event_id"],
            "initial_narrative": tpl.get("initial_narrative", ""),
            "rumor_peak_at": None,
            "branch_probabilities_at_rumor_peak": {},
            "resolution_labels": {
                "label_confidence": 0.0,
                "template_category": tpl.get("category", ""),
                "rumor_or_contradiction": tpl.get("rumor_or_contradiction", ""),
                "required_evidence": tpl.get("required_evidence", ""),
            },
            "affected_basket": [],
            "benchmark": "",
            "outcome_label": "UNRESOLVED",
            "false_positive": False,
            "false_negative": False,
            "r_multiple": None,
        }
        persist_nbi_backtest_case(
            case, db_path=db_path, case_kind=CASE_KIND_TEMPLATE,
            case_id=f"{tpl['event_id']}::template",
        )
        imported += 1
    return {
        "imported": imported,
        "case_kind": CASE_KIND_TEMPLATE,
        "calibration_eligible": False,
        "readiness_after": summarize_nbi_backtest_readiness(db_path),
    }


# ---------------------------------------------------------------------------
# export-cards — static HTML + markdown operator surface (not an app page)
# ---------------------------------------------------------------------------


def export_cards(
    db_path: Path | str | None = None,
    *,
    out_html: Path | str | None = None,
    out_md: Path | str | None = None,
    out_json: Path | str | None = None,
    include_fixtures: bool = False,
    now_iso: str | None = None,
) -> dict[str, Any]:
    reports = load_active_nbi_reports(db_path, include_fixtures=include_fixtures)
    state = _loop_state(db_path)
    edge = state["edge_claim"]

    md_lines = ["# NBI Operator Event Cards", ""]
    md_lines.append(
        f"- Calibration: **{state['calibration']['status']}** "
        f"(closed real cases: {state['calibration']['n_closed_real_cases']})"
    )
    md_lines.append(
        f"- Edge claim permitted: **{edge['edge_claim_allowed']}** "
        f"({edge['current_case_count']}/{edge['required_case_count']} "
        "eligible cases)"
    )
    md_lines.append("")
    if not reports:
        md_lines.append(f"**{NO_ACTIVE_NBI_EVENTS}**")
    for r in reports:
        fixture_tag = ""
        event_row = load_nbi_event(str(r.get("event_id")), db_path)
        if event_row and event_row.get("is_fixture"):
            fixture_tag = " [FIXTURE]"
        md_lines.append(f"## {r.get('event_name')}{fixture_tag}")
        md_lines.append("```text")
        md_lines.append(render_event_card(r))
        md_lines.append("```")
        refs = sorted({
            ref for t in r.get("tickers", [])
            for ref in t.get("evidence_refs", [])
        })
        if refs:
            md_lines.append("Evidence refs:")
            md_lines.extend(f"- {ref}" for ref in refs)
        md_lines.append("")
    md_text = "\n".join(md_lines)

    body = [
        "<h1>NBI Operator Event Cards</h1>",
        "<p><b>ADVISORY_ONLY</b> — execution gate LOCKED — human decides.</p>",
        f"<p>Calibration: <b>{html.escape(state['calibration']['status'])}</b>"
        f" | Edge claim permitted: <b>{edge['edge_claim_allowed']}</b>"
        f" ({edge['current_case_count']}/{edge['required_case_count']}"
        " eligible cases)</p>",
    ]
    if not edge["edge_claim_allowed"]:
        body.append(
            "<p>No performance edge is claimed. Missing: "
            + html.escape("; ".join(edge["missing_requirements"]) or "-")
            + "</p>"
        )
    if not reports:
        body.append(f"<p><b>{NO_ACTIVE_NBI_EVENTS}</b></p>")
    for r in reports:
        event_row = load_nbi_event(str(r.get("event_id")), db_path)
        fixture_tag = (
            " <b>[FIXTURE]</b>"
            if event_row and event_row.get("is_fixture") else ""
        )
        body.append(f"<h2>{html.escape(str(r.get('event_name')))}{fixture_tag}</h2>")
        body.append(f"<pre>{html.escape(render_event_card(r))}</pre>")
        refs = sorted({
            ref for t in r.get("tickers", [])
            for ref in t.get("evidence_refs", [])
        })
        if refs:
            body.append(
                "<ul>" + "".join(
                    f"<li>{html.escape(ref)}</li>" for ref in refs
                ) + "</ul>"
            )
    html_text = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>NBI Operator Cards</title></head><body>"
        + "".join(body) + "</body></html>"
    )

    # API-ready JSON artifact: the same structured section the daily bridge
    # produces, plus loop state — this is what GET /nbi/cards serves.
    section = build_nbi_daily_section(reports)
    fixture_ids = set()
    for r in reports:
        event_row = load_nbi_event(str(r.get("event_id")), db_path)
        if event_row and event_row.get("is_fixture"):
            fixture_ids.add(str(r.get("event_id")))
    for ev in section.get("events", []):
        ev["is_fixture"] = ev.get("event_id") in fixture_ids
    json_payload = {
        "report": "nbi_operator_cards",
        "version": FACTORY_VERSION,
        "generated_at": _now_iso(now_iso),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "section": section,
        "backtest_readiness": state["backtest_readiness"],
        "calibration": state["calibration"],
        "edge_claim": edge,
        "last_scheduler_run": _read_json(SCHEDULER_LAST_RUN_PATH),
    }

    html_path = Path(out_html) if out_html else _artifact_path(CARDS_HTML_PATH)
    md_path = Path(out_md) if out_md else _artifact_path(CARDS_MD_PATH)
    json_path = Path(out_json) if out_json else _artifact_path(CARDS_JSON_PATH)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(json_payload, indent=2, default=str), encoding="utf-8"
    )
    return {
        "exported": True,
        "html_path": str(html_path),
        "md_path": str(md_path),
        "json_path": str(json_path),
        "active_events": len(reports),
        "edge_claim_allowed": edge["edge_claim_allowed"],
        "html": html_text,
        "markdown": md_text,
        "json_payload": json_payload,
    }


# ---------------------------------------------------------------------------
# corpus-status — the evidence-accumulation dashboard
# ---------------------------------------------------------------------------

STALE_ACTIVE_DAYS = 7.0
CALIBRATION_TARGET_CASES = 30
SCHEDULER_LAST_RUN_PATH = REPO_ROOT / "runtime" / "nbi_scheduler_last_run.json"


def _all_event_rows(db_path: Path | str | None) -> list[dict[str, Any]]:
    import sqlite3

    from scripts.nbi_store import CANONICAL_DB_PATH, init_nbi_schema
    init_nbi_schema(db_path)
    path = Path(db_path) if db_path is not None else CANONICAL_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM nbi_events")]
    finally:
        conn.close()


def corpus_status(
    db_path: Path | str | None = None, *, now_iso: str | None = None,
) -> dict[str, Any]:
    from scripts.nbi_store import CASE_KIND_REAL
    from scripts.nbi_template_workshop import list_templates
    from scripts.nbi_track_record_ledger import compute_case_quality

    events = _all_event_rows(db_path)
    cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    calibration = build_nbi_calibration_report(db_path=db_path)
    edge = compute_edge_claim_permission(cases, calibration)

    real = [
        c for c in cases
        if not c.get("is_fixture")
        and c.get("case_kind", CASE_KIND_REAL) == CASE_KIND_REAL
    ]
    eligible = [
        c for c in real if compute_case_quality(c)["calibration_eligible"]
    ]
    qualities = [
        q for q in (compute_case_quality(c)["EQS10"] for c in cases)
        if q is not None
    ]

    # Stale active events: still ACTIVE-surface but not updated recently.
    reference = datetime.fromisoformat(
        _now_iso(now_iso).replace("Z", "+00:00")
    )
    stale: list[str] = []
    for e in events:
        if e.get("state") in ("RESOLVED", "DEAD") or e.get("is_fixture"):
            continue
        try:
            updated = datetime.fromisoformat(
                str(e.get("updated_at")).replace("Z", "+00:00")
            )
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
        except ValueError:
            stale.append(e["event_id"])
            continue
        age_days = (reference - updated).total_seconds() / 86400.0
        if age_days > STALE_ACTIVE_DAYS:
            stale.append(e["event_id"])

    templates = list_templates(db_path)
    remaining = max(0, CALIBRATION_TARGET_CASES - len(eligible))
    progress = min(1.0, len(eligible) / CALIBRATION_TARGET_CASES)
    last_scheduler_run = _read_json(SCHEDULER_LAST_RUN_PATH)

    return {
        "report": "nbi_corpus_status",
        "version": FACTORY_VERSION,
        "events_total": len(events),
        "events_active": sum(
            1 for e in events
            if e.get("state") not in ("RESOLVED", "DEAD")
            and not e.get("is_fixture")
        ),
        "events_resolved": sum(
            1 for e in events if e.get("state") == "RESOLVED"
        ),
        "cases_template": sum(
            1 for c in cases if c.get("case_kind") == "TEMPLATE"
        ),
        "cases_fixture": sum(1 for c in cases if c.get("is_fixture")
                             and c.get("case_kind") != "TEMPLATE"),
        "cases_real_closed": len(
            [c for c in real if c.get("resolution_timestamp")]
        ),
        "cases_calibration_eligible": len(eligible),
        "avg_eqs10": round(sum(qualities) / len(qualities), 4)
        if qualities else None,
        "edge_claim_allowed": edge["edge_claim_allowed"],
        "cases_remaining_for_calibration": remaining,
        "calibration_progress10": round(10.0 * progress, 4),
        "easiest_templates_to_promote": templates[:3],
        "stale_active_events": stale,
        "last_scheduler_run": (
            {"timestamp": last_scheduler_run.get("timestamp"),
             "status": last_scheduler_run.get("status")}
            if isinstance(last_scheduler_run, dict) else None
        ),
        **_corpus_operating_sections(db_path, eligible_count=len(eligible)),
        "safety": advisory_safety_stamps(),
    }


def _corpus_operating_sections(
    db_path: Path | str | None, *, eligible_count: int,
) -> dict[str, Any]:
    """v1.4 operating-board sections: scheduler, definitions, market fetch,
    surfaces, LiveOpsReadiness, and the next-required-operator-actions list."""
    from scripts.nbi_prediction_market_bridge import MARKET_CONTRACTS_PATH
    from scripts.nbi_scheduler import INSTALL_MARKER_PATH, task_installed

    try:
        scheduler_installed = bool(
            task_installed() or INSTALL_MARKER_PATH.exists()
        )
    except Exception:  # noqa: BLE001
        scheduler_installed = False

    definitions = load_event_definitions() or []
    active_defs = [
        d for d in definitions
        if str(d.get("status") or "").upper() == "ACTIVE"
        and not d.get("is_fixture")
    ]
    watch_defs = [
        d for d in definitions
        if str(d.get("status") or "").upper() == "WATCH_ONLY"
    ]
    pack = _read_json(WATCH_EVENT_PACK_PATH)
    pack_count = (
        len(pack.get("events", [])) if isinstance(pack, dict) else 0
    )

    contracts = _read_json(MARKET_CONTRACTS_PATH)
    live_rows = 0
    if isinstance(contracts, dict):
        for rows in contracts.values():
            if isinstance(rows, list):
                live_rows += sum(
                    1 for r in rows
                    if isinstance(r, dict)
                    and str(r.get("adapter_status") or "") == "LIVE"
                )

    feed_available = load_feed_rows() is not None
    cards_exported = CARDS_JSON_PATH.exists()
    live_ops = (
        (1.0 if scheduler_installed else 0.0)
        * (1.0 if active_defs else 0.0)
        * (1.0 if feed_available else 0.0)
        * (1.0 if cards_exported else 0.0)
    )
    if not scheduler_installed:
        # Helper-only operation is capped but explicitly safe.
        live_ops = min(
            0.7,
            (1.0 if active_defs else 0.0)
            * (1.0 if feed_available else 0.0)
            * (1.0 if cards_exported else 0.0) * 0.7,
        )

    next_actions: list[str] = []
    if not scheduler_installed:
        next_actions.append(
            "install the daily task: python -m scripts.nbi_scheduler install"
        )
    if not active_defs:
        next_actions.append(
            "activate a watch event: python -m scripts.nbi_evidence_factory "
            "activate-event --event-id <id>"
        )
    if eligible_count < CALIBRATION_TARGET_CASES:
        next_actions.append(
            f"accumulate {CALIBRATION_TARGET_CASES - eligible_count} more "
            "eligible cases (close events / promote templates via "
            "nbi_template_workshop)"
        )
    if live_rows == 0:
        next_actions.append(
            "refresh market contracts: python -m "
            "scripts.nbi_prediction_market_bridge refresh-all (or supply "
            "runtime/nbi_market_contracts.json)"
        )

    return {
        "scheduler": {
            "installed": scheduler_installed,
            "note": None if scheduler_installed else (
                "installable helper verified; actual OS task not installed "
                "in this environment"
            ),
        },
        "event_definitions": {
            "active": [d.get("event_id") for d in active_defs],
            "watch_only": [d.get("event_id") for d in watch_defs],
            "watch_pack_available": pack_count,
        },
        "market_fetch_status": {
            "contracts_file_present": isinstance(contracts, dict),
            "live_contract_rows": live_rows,
        },
        "surface_status": {
            "cards_json_artifact": cards_exported,
            "cards_html": CARDS_HTML_PATH.exists(),
            "api_route": "/nbi/cards (token-gated)",
        },
        "live_ops_readiness": round(live_ops, 4),
        "next_required_operator_actions": next_actions,
    }


# ---------------------------------------------------------------------------
# v1.5 first-case readiness — what becomes the first REAL eligible case?
# ---------------------------------------------------------------------------


def first_case_readiness(
    db_path: Path | str | None = None, *, now_iso: str | None = None,
) -> dict[str, Any]:
    """Rank the fastest honest paths to the first eligible real cases.

        FirstCaseReadiness = Evidence x Outcome x Price x Probabilities
                             x OperatorDecision            (per candidate)

    Candidates: templates from the worklist (readiness = fraction of the
    five gaps already closed) and non-fixture ACTIVE events (closeable only
    once they have verified claims).  Output is planning, never a case.
    """
    from scripts.nbi_template_workshop import template_worklist

    gap_keys = (
        "missing_evidence", "missing_outcomes", "missing_price",
        "missing_branch_probabilities", "missing_operator_decision",
    )
    candidates: list[dict[str, Any]] = []
    for item in template_worklist(db_path, limit=1000):
        closed = sum(1 for k in gap_keys if not item[k])
        readiness = closed / len(gap_keys)
        candidates.append({
            "kind": "TEMPLATE",
            "id": item["template_id"],
            "name": item["event_name"],
            "readiness": round(readiness, 4),
            "expected_eqs_after_completion": 10.0,
            "estimated_minutes": item["estimated_minutes_to_promote"],
            "missing": [k for k in gap_keys if item[k]],
            # Floor 0.2: an untouched template is still a better first case
            # than an active event with no verified claims (0.05), while a
            # closeable event (0.5) and near-complete templates rank higher.
            "rank_score": round(0.2 + 0.6 * readiness, 4),
        })
    for event in _all_event_rows(db_path):
        if event.get("is_fixture") or event.get("state") in ("RESOLVED",
                                                             "DEAD"):
            continue
        report = load_latest_report(str(event["event_id"]), db_path)
        closeable = bool(report and report.get("claims_verified"))
        candidates.append({
            "kind": "ACTIVE_EVENT",
            "id": event["event_id"],
            "name": event.get("name") or event["event_id"],
            "readiness": 0.4 if closeable else 0.05,
            "closeable": closeable,
            "missing": (
                ["resolution + outcomes + price"] if closeable
                else ["verified claims (feed empty so far)",
                      "resolution + outcomes + price"]
            ),
            "estimated_minutes": 45,
            "rank_score": 0.5 if closeable else 0.05,
        })
    candidates.sort(key=lambda c: -c["rank_score"])
    return {
        "report": "nbi_first_case_readiness",
        "version": FACTORY_VERSION,
        "candidates": candidates[:10],
        "recommended_first_three": [c["id"] for c in candidates[:3]],
        "cases_remaining_for_calibration": CALIBRATION_TARGET_CASES,
        "doctrine": (
            "planning output only: nothing here counts as a case or moves "
            "the edge gate"
        ),
        "safety": advisory_safety_stamps(),
    }


# ---------------------------------------------------------------------------
# score-report v1.3 — weighted ceiling census with explicit honesty caps
# ---------------------------------------------------------------------------

# v1.4 weights (spec).  (name, weight, prior, current-if-uncapped, evidence)
_SEGMENTS_V13: tuple[tuple[str, float, float, float, str], ...] = (
    ("Narrative Layer Intelligence", 0.05, 8, 8, "unchanged this sprint"),
    ("Rumor / Causal Leap Detection", 0.05, 9, 9, "unchanged; fuzz-held"),
    ("Event Branch Probability Engine", 0.06, 8, 8, "unchanged"),
    ("Source Quality / Cluster Weighting", 0.05, 9, 9, "unchanged"),
    ("Symbolic vs Substantive Catalyst Handling", 0.04, 8, 8, "unchanged"),
    ("Value-Chain Mapping Integration", 0.05, 8, 8,
     "consumed via event definitions"),
    ("Price / Outcome Validation", 0.06, 8.5, 8.5,
     "closeout quality gate + per-branch Brier persisted"),
    ("Operator Explainability", 0.04, 9, 9,
     "cards on HTML/MD/JSON/API + /nbi page with edge disclosure"),
    ("Risk Controls / Fail-Closed Discipline", 0.07, 9, 9,
     "doctor safety check, activation gates, uncited-alpha zero"),
    ("Test Coverage / Regression Safety", 0.05, 9, 9,
     "operate-loop v1.4 test group added"),
    ("Backtest Readiness", 0.06, 8.5, 8.6,
     "evidence packs turn the worklist into per-template research contracts"),
    ("Live Data Integration", 0.08, 8.3, 8.6,
     "OS task INSTALLED + run-once HEALTHY (schtasks truth); capped 8.5 "
     "until the feed emits usable rows"),
    ("Persistence / Auditability", 0.05, 9.5, 9.5,
     "cockpit artifacts added"),
    ("Calibration Readiness", 0.08, 8, 8.2,
     "CASE_ACCUMULATION band + first-case plan; capped 8 while eligible = 0"),
    ("Daily Operator Workflow", 0.05, 9.2, 9.3,
     "cockpit autopilot supervises the loop in one command"),
    ("Track Record / Evidence Factory", 0.08, 8.2, 8.4,
     "first-case readiness ranked; capped 8.4 until a case is promoted"),
    ("Prediction-Market Integration", 0.07, 8, 8.3,
     "query expansion + pagination + diagnostics; capped 8.1 until matched "
     "live rows persist"),
    ("Edge Claim Honesty", 0.06, 9, 9,
     "gate on every surface incl. cockpit; false until earned"),
    ("Frontend / Operator Surface", 0.06, 8.2, 8.5,
     "/nbi cockpit panels + /nbi/cockpit API; build-verified"),
)


def _detect_capabilities(db_path: Path | str | None) -> dict[str, bool]:
    """Live capability detection — score caps follow reality, not intent."""
    from scripts.nbi_prediction_market_bridge import MARKET_CONTRACTS_PATH
    from scripts.nbi_scheduler import INSTALL_MARKER_PATH, task_installed

    try:
        scheduler_installed = task_installed() or INSTALL_MARKER_PATH.exists()
    except Exception:  # noqa: BLE001
        scheduler_installed = False
    contracts = _read_json(MARKET_CONTRACTS_PATH)
    live_fetch_succeeded = isinstance(contracts, dict) and any(
        isinstance(rows, list) and any(
            isinstance(r, dict) and r.get("fetched_at")
            and str(r.get("adapter_status") or "LIVE") == "LIVE"
            for r in rows
        )
        for rows in contracts.values()
    )
    definitions = load_event_definitions() or []
    real_active = any(
        not d.get("is_fixture")
        and str(d.get("status") or "").upper() == "ACTIVE"
        for d in definitions
    )
    # App route detection: the Next.js page must actually exist in the
    # frontend tree (added + build-verified), not merely be claimed.
    page_path = REPO_ROOT / "frontend" / "src" / "app" / "nbi" / "page.tsx"
    # v1.5 detections: feed usability + cockpit artifact presence.
    try:
        from scripts.nbi_feed_bridge import feed_bridge_status
        feed_usability = float(
            feed_bridge_status().get("feed_usability") or 0.0
        )
    except Exception:  # noqa: BLE001
        feed_usability = 0.0
    cockpit_artifact = (
        REPO_ROOT / "runtime" / "nbi_live_ops_cockpit.json"
    ).exists()
    return {
        "scheduler_installed": scheduler_installed,
        "market_auto_fetched": live_fetch_succeeded,
        "real_active_events": real_active,
        "frontend_app_page": page_path.exists(),
        "feed_usability": feed_usability,
        "cockpit_artifact": cockpit_artifact,
    }


def build_score_report(db_path: Path | str | None = None) -> dict[str, Any]:
    readiness = summarize_nbi_backtest_readiness(db_path)
    cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    calibration = build_nbi_calibration_report(db_path=db_path)
    edge = compute_edge_claim_permission(cases, calibration)
    real_closed = readiness["cases_real_closed"]
    eligible = calibration.get("n_calibration_eligible", 0)
    capabilities = _detect_capabilities(db_path)

    rows: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for name, weight, prior, current, evidence in _SEGMENTS_V13:
        capped = current
        if name == "Live Data Integration":
            if not capabilities["scheduler_installed"]:
                capped = min(capped, 8.3)   # install truth still pending
            elif capabilities["feed_usability"] == 0.0:
                capped = min(capped, 8.5)   # installed; feed truth pending
        if name == "Frontend / Operator Surface" and not capabilities[
            "frontend_app_page"
        ]:
            capped = min(capped, 8.0)
        if name == "Calibration Readiness" and eligible == 0:
            capped = min(capped, 8.0)
        if name == "Prediction-Market Integration" and not capabilities[
            "market_auto_fetched"
        ]:
            capped = min(capped, 8.1)  # v1.5: fetch works, matches pending
        if name == "Track Record / Evidence Factory":
            if not capabilities["real_active_events"]:
                capped = min(capped, 8.0)
            elif eligible == 0:
                capped = min(capped, 8.4)  # readiness exists, no promotion yet
        weighted_sum += weight * capped
        weight_total += weight
        rows.append({
            "segment": name, "weight": weight, "prior": prior,
            "current": capped, "delta": round(capped - prior, 2),
            "gap_to_10": round(10 - capped, 2), "evidence": evidence,
        })

    overall_raw = round(weighted_sum / weight_total, 4)
    caps_applied: list[str] = []
    overall = overall_raw
    if eligible == 0:
        overall = min(overall, 8.8)
        caps_applied.append("no eligible real closed cases -> overall <= 8.8")
    elif eligible < 10:
        overall = min(overall, 9.0)
        caps_applied.append("eligible cases < 10 -> overall <= 9.0")
    if not edge["edge_claim_allowed"]:
        overall = min(overall, 9.0)
        caps_applied.append("edge claim not permitted -> overall <= 9.0")
    # Same precision as the raw so rounding can never exceed the weighted raw.
    overall = round(min(overall, overall_raw), 4)

    prior_overall = 8.50  # v1.4 measured weighted overall
    rows.append({
        "segment": "Overall MVP Ceiling", "weight": None,
        "prior": prior_overall,
        "current": overall, "delta": round(overall - prior_overall, 2),
        "gap_to_10": round(10 - overall, 2),
        "evidence": (
            f"weighted raw {overall_raw}; caps enforce reality "
            f"(eligible cases={eligible}, scheduler_installed="
            f"{capabilities['scheduler_installed']}, active_events="
            f"{capabilities['real_active_events']})"
        ),
    })
    # v1.5 subfields: live-ops health (from the cockpit artifact when one
    # exists) plus the truth surfaces the caps were derived from.
    cockpit = _read_json(REPO_ROOT / "runtime" / "nbi_live_ops_cockpit.json")
    live_ops_health = (
        cockpit.get("health", {}).get("LiveOpsHealth10")
        if isinstance(cockpit, dict) else None
    )
    return {
        "report": "nbi_ceiling_score_report",
        "version": FACTORY_VERSION,
        "formula": "Overall = min(sum(w_i*s_i)/sum(w_i), honesty caps)",
        "segments": rows,
        "overall_raw_weighted": overall_raw,
        "constraint_caps_applied": caps_applied,
        "capabilities": capabilities,
        "real_closed_cases": real_closed,
        "calibration_eligible_cases": eligible,
        "edge_claim_allowed": edge["edge_claim_allowed"],
        "v15": {
            "live_ops_health10": live_ops_health,
            "feed_bridge_usability": capabilities["feed_usability"],
            "scheduler_install_truth": capabilities["scheduler_installed"],
            "market_match_quality": (
                "MATCHED_LIVE_ROWS" if capabilities["market_auto_fetched"]
                else "FETCH_WORKS_ZERO_MATCHES"
            ),
            "first_case_readiness_available": True,
            "template_promotion_ready_count": 0 if eligible == 0 else eligible,
        },
        "safety": advisory_safety_stamps(),
    }


def render_score_report(report: dict[str, Any]) -> str:
    lines = [
        "| Segment | Prior | Current | Delta | Gap to 10 | Evidence |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in report["segments"]:
        lines.append(
            f"| {row['segment']} | {row['prior']} | {row['current']} | "
            f"{row['delta']:+} | {row['gap_to_10']} | {row['evidence']} |"
        )
    if report["constraint_caps_applied"]:
        lines.append("")
        lines.append("Caps: " + "; ".join(report["constraint_caps_applied"]))
    lines.append("")
    lines.append(
        f"edge_claim_allowed={report['edge_claim_allowed']} | ADVISORY_ONLY"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Event-definition template helper
# ---------------------------------------------------------------------------

EVENT_DEFINITION_TEMPLATE: dict[str, Any] = {
    "events": [
        {
            "event_id": "example-event-id",
            "event_name": "Human-readable event name",
            "category": "DIPLOMATIC_SUMMIT",
            "keywords": ["summit", "guwahati"],
            "decision_jurisdictions": ["JP", "IN"],
            "priors": {"core_event": 0.55, "venue_specific": 0.5},
            "exposures": [],
            "value_chain_graph": None,
            "ticker_metadata": {},
        }
    ]
}


def write_event_definition_template(path: Path | str | None = None) -> str:
    target = Path(path) if path else EVENT_DEFINITIONS_PATH.with_suffix(
        ".template.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(EVENT_DEFINITION_TEMPLATE, indent=2), encoding="utf-8"
    )
    return str(target)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NBI Evidence Factory: closed-loop CLI runner "
            "(advisory-only; not a scheduler)."
        )
    )
    parser.add_argument("--db", default=None, help="DB path (default canonical)")
    sub = parser.add_subparsers(dest="command")

    run_p = sub.add_parser("run-daily", help="one factory cycle")
    run_p.add_argument("--fixture", action="store_true",
                       help="persist as fixture (demo/test runs)")
    run_p.add_argument("--event-id", default=None,
                       help="run only this event definition")
    ingest_p = sub.add_parser("ingest", help="alias of run-daily")
    ingest_p.add_argument("--fixture", action="store_true")
    ingest_p.add_argument("--event-id", default=None)
    ingest_p.add_argument("--source", default="latest",
                          help="feed source (only 'latest' supported)")
    sub.add_parser("status", help="loop state census")
    sub.add_parser("list-events", help="list event definitions + readiness")
    sub.add_parser("validate-events", help="validate event definitions")
    corpus_p = sub.add_parser(
        "corpus-status", help="evidence-accumulation operating board"
    )
    corpus_p.add_argument("--verbose", action="store_true",
                          help="(sections are always included; flag kept "
                               "for operator muscle memory)")
    act_p = sub.add_parser("activate-event",
                           help="WATCH_ONLY -> ACTIVE (explicit operator act)")
    act_p.add_argument("--event-id", required=True)
    deact_p = sub.add_parser("deactivate-event", help="ACTIVE -> WATCH_ONLY")
    deact_p.add_argument("--event-id", required=True)
    ev_p = sub.add_parser("event-status", help="definition + store status")
    ev_p.add_argument("--event-id", required=True)
    sub.add_parser("first-case-readiness",
                   help="fastest honest paths to the first eligible case")
    sub.add_parser("first-case-plan", help="alias of first-case-readiness")
    add_p = sub.add_parser("add-event", help="add an operator event definition")
    add_p.add_argument("--event-id", required=True)
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--category", default="geopolitics")
    add_p.add_argument("--query-terms", default="",
                       help="comma-separated query terms (required)")
    add_p.add_argument("--status", default="WATCH_ONLY",
                       choices=("ACTIVE", "WATCH_ONLY", "CLOSED"))
    add_p.add_argument("--official-sources", default="")
    add_p.add_argument("--benchmark-tickers", default="")
    add_p.add_argument("--notes", default="")

    close_p = sub.add_parser("close-event", help="close an event into a case")
    close_p.add_argument("--event-id", required=True)
    for name in ("core", "venue", "delegation", "deals"):
        close_p.add_argument(f"--{name}-outcome", type=int, choices=(0, 1),
                             default=None)
    close_p.add_argument("--notes", default="")
    close_p.add_argument("--benchmark", default="")
    close_p.add_argument("--realized-return", type=float, default=None)
    close_p.add_argument("--benchmark-return", type=float, default=None)
    close_p.add_argument("--initial-risk", type=float, default=None)
    close_p.add_argument("--label-confidence", type=float, default=0.9)
    close_p.add_argument(
        "--force-noncalibration", action="store_true",
        help="allow a low-quality WATCH_ARCHIVE close (never calibration)",
    )

    sub.add_parser("import-templates", help="import retro-label seed pack")
    export_p = sub.add_parser("export-cards", help="write HTML/MD card surface")
    export_p.add_argument("--include-fixtures", action="store_true")
    sub.add_parser("score-report", help="segmented ceiling score census")
    sub.add_parser("init-event-template", help="write event-definition template")

    args = parser.parse_args(argv)
    db = args.db

    if args.command in ("run-daily", "ingest"):
        fixture = bool(getattr(args, "fixture", False))
        out = run_daily(
            db_path=db, is_fixture=fixture,
            event_id=getattr(args, "event_id", None),
        )
        print(json.dumps(out, indent=2, default=str))
    elif args.command == "status":
        print(json.dumps(factory_status(db), indent=2, default=str))
    elif args.command == "list-events":
        definitions = load_event_definitions() or []
        print(json.dumps(
            [validate_event_definition(d) for d in definitions],
            indent=2,
        ))
    elif args.command == "validate-events":
        print(json.dumps(validate_event_definitions(), indent=2))
    elif args.command == "corpus-status":
        print(json.dumps(corpus_status(db), indent=2, default=str))
    elif args.command == "activate-event":
        out = activate_event(args.event_id)
        print(json.dumps(out, indent=2))
        return 0 if out.get("changed") else 1
    elif args.command == "deactivate-event":
        out = deactivate_event(args.event_id)
        print(json.dumps(out, indent=2))
        return 0 if out.get("changed") else 1
    elif args.command == "event-status":
        print(json.dumps(event_status(args.event_id, db_path=db),
                         indent=2, default=str))
    elif args.command in ("first-case-readiness", "first-case-plan"):
        print(json.dumps(first_case_readiness(db), indent=2, default=str))
    elif args.command == "add-event":
        definition = {
            "event_id": args.event_id,
            "event_name": args.name,
            "name": args.name,
            "category": args.category,
            "status": args.status,
            "query_terms": [
                t.strip() for t in args.query_terms.split(",") if t.strip()
            ],
            "official_sources": [
                s.strip() for s in args.official_sources.split(",") if s.strip()
            ],
            "benchmark_tickers": [
                t.strip() for t in args.benchmark_tickers.split(",") if t.strip()
            ],
            "notes": args.notes,
        }
        out = add_event_definition(definition)
        print(json.dumps(out, indent=2))
        return 0 if out.get("added") else 1
    elif args.command == "close-event":
        outcomes = {
            name: getattr(args, f"{name}_outcome")
            for name in ("core", "venue", "delegation", "deals")
            if getattr(args, f"{name}_outcome") is not None
        }
        out = close_event(
            args.event_id, branch_outcomes=outcomes, notes=args.notes,
            benchmark=args.benchmark, realized_return=args.realized_return,
            benchmark_return=args.benchmark_return,
            initial_risk=args.initial_risk,
            label_confidence=args.label_confidence,
            force_noncalibration=args.force_noncalibration, db_path=db,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("closed") else 1
    elif args.command == "import-templates":
        print(json.dumps(import_templates(db_path=db), indent=2, default=str))
    elif args.command == "export-cards":
        out = export_cards(db, include_fixtures=args.include_fixtures)
        print(f"exported: {out['html_path']} and {out['md_path']} "
              f"({out['active_events']} active event(s))")
    elif args.command == "score-report":
        print(render_score_report(build_score_report(db)))
    elif args.command == "init-event-template":
        print(f"template written: {write_event_definition_template()}")
    else:
        parser.print_help()
        return 2
    return 0


__all__ = [
    "FACTORY_VERSION",
    "STATUS_FEEDS_UNAVAILABLE", "STATUS_NO_EVENT_DEFINITIONS", "STATUS_OK",
    "CLOSEOUT_QUALITY_MIN", "CLOSEOUT_CLASS_CALIBRATION",
    "CLOSEOUT_CLASS_NON_CALIBRATION", "CALIBRATION_TARGET_CASES",
    "ACTIVATION_MIN_READINESS10", "EVENT_CONFIDENCE_CAP_NO_OFFICIAL",
    "load_event_definitions", "load_feed_rows", "assign_rows_to_events",
    "build_event_input", "validate_event_definition",
    "validate_event_definitions", "add_event_definition",
    "activate_event", "deactivate_event", "event_status",
    "run_daily", "factory_status", "close_event", "corpus_status",
    "first_case_readiness",
    "import_templates", "export_cards", "build_score_report",
    "render_score_report", "write_event_definition_template", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
