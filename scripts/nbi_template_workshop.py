"""NBI template workshop — audited TEMPLATE -> REAL promotion, one command.

The 20 historical templates are seeds, not evidence.  This workshop is the
only sanctioned path for turning one into a REAL calibration case, and it
extracts every requirement explicitly:

    list / show                      — inventory + per-template gap report
    attach-evidence  --url ...       — dated, http(s)-validated citations
    attach-outcome   --core 1 ...    — branch outcome labels + confidence
    attach-price     --return ...    — realized vs benchmark returns
    attach-probabilities --p-core .. — retro branch probabilities (basis
                                       note REQUIRED: reconstructions must
                                       say what they were reconstructed from)
    validate                         — EQS + promotion-blocker report
    promote --to-real --operator-confirmed
                                     — the ONLY way case_kind changes

Promotion rule (all enforced, tested):

    PromoteToReal = 1[EQS10 >= 7] x 1[outcome labels complete]
                  x 1[evidence refs valid] x 1[explicit operator flag]
                  x 1[not fixture-locked]

    CalibrationEligible = PromoteToReal x 1[price data complete]
                        x 1[branch probabilities available]

Every mutation is appended to the ``nbi_template_audit`` table — the trail
shows exactly what evidence turned a template into a case, and when.

Advisory-only.  No broker, no execution, no invented outcomes: the workshop
only records what the operator attaches, and refuses what is incomplete.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.advisory_contract import advisory_safety_stamps
from scripts.nbi_store import (
    CANONICAL_DB_PATH,
    CASE_KIND_REAL,
    CASE_KIND_TEMPLATE,
    init_nbi_schema,
    load_nbi_backtest_cases,
    summarize_nbi_backtest_readiness,
)
from scripts.nbi_track_record_ledger import compute_case_quality

WORKSHOP_VERSION = "nbi-workshop-v1.0"

_AUDIT_SCHEMA = """CREATE TABLE IF NOT EXISTS nbi_template_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}'
)"""

_BRANCH_KEYS = ("core", "venue", "delegation", "deals")
_ENGINE_BRANCH = {
    "core": "core_event", "venue": "venue_specific",
    "delegation": "delegation_intact", "deals": "deals_or_mous",
}


def _resolve(db_path: Path | str | None) -> Path:
    return Path(db_path) if db_path is not None else CANONICAL_DB_PATH


def _connect(db_path: Path | str | None) -> sqlite3.Connection:
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    init_nbi_schema(db_path)
    conn.execute(_AUDIT_SCHEMA)
    return conn


def _now_iso(now_iso: str | None) -> str:
    if now_iso:
        return now_iso
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _audit(conn: sqlite3.Connection, case_id: str, action: str,
           payload: dict[str, Any], stamp: str) -> None:
    conn.execute(
        "INSERT INTO nbi_template_audit (case_id, timestamp, action, "
        "payload_json) VALUES (?,?,?,?)",
        (case_id, stamp, action, json.dumps(payload, default=str)),
    )


def _load_case_row(conn: sqlite3.Connection, case_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM nbi_backtest_cases WHERE case_id = ?", (case_id,)
    ).fetchone()


def _resolve_case_id(conn: sqlite3.Connection, template_id: str) -> str | None:
    """Accept either the full case_id or the template event_id."""
    for candidate in (template_id, f"{template_id}::template"):
        if _load_case_row(conn, candidate) is not None:
            return candidate
    return None


def _labels(row: sqlite3.Row) -> dict[str, Any]:
    try:
        return json.loads(row["resolution_labels_json"])
    except ValueError:
        return {}


def _case_dict(row: sqlite3.Row) -> dict[str, Any]:
    case = dict(row)
    for key in ("branch_probabilities_json", "resolution_labels_json",
                "affected_basket_json", "benchmark_json", "evidence_refs_json"):
        try:
            case[key.removesuffix("_json")] = json.loads(case.pop(key))
        except ValueError:
            case[key.removesuffix("_json")] = None
    return case


def list_templates(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    out = []
    for c in cases:
        if c.get("case_kind") != CASE_KIND_TEMPLATE:
            continue
        quality = compute_case_quality(c)
        out.append({
            "case_id": c["case_id"],
            "event_id": c["event_id"],
            "initial_narrative": c["initial_narrative"],
            "EQS10": quality["EQS10"],
            "blockers": _promotion_blockers(c, quality,
                                            operator_confirmed=True),
        })
    return sorted(out, key=lambda t: t["EQS10"], reverse=True)


def attach_evidence(
    template_id: str, *, url: str, source_type: str = "",
    db_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return {"attached": False,
                "error": f"invalid evidence URL {url!r} (must be http(s))"}
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"attached": False, "error": "template not found"}
        row = _load_case_row(conn, case_id)
        refs = json.loads(row["evidence_refs_json"] or "[]")
        if url not in refs:
            refs.append(url)
        labels = _labels(row)
        sources = labels.setdefault("evidence_source_types", {})
        if source_type:
            sources[url] = source_type.upper()
        stamp = _now_iso(now_iso)
        conn.execute(
            "UPDATE nbi_backtest_cases SET evidence_refs_json = ?, "
            "resolution_labels_json = ? WHERE case_id = ?",
            (json.dumps(refs), json.dumps(labels), case_id),
        )
        _audit(conn, case_id, "ATTACH_EVIDENCE",
               {"url": url, "source_type": source_type}, stamp)
        conn.commit()
    finally:
        conn.close()
    return {"attached": True, "case_id": case_id, "evidence_refs": refs}


def attach_outcome(
    template_id: str, *, branch_outcomes: dict[str, Any],
    label_confidence: float = 0.9,
    db_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    core = branch_outcomes.get("core")
    if core not in (0, 1):
        return {"attached": False, "error": "core outcome (0/1) required"}
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"attached": False, "error": "template not found"}
        row = _load_case_row(conn, case_id)
        labels = _labels(row)
        labels["branch_outcomes"] = {
            k: branch_outcomes.get(k) for k in _BRANCH_KEYS
        }
        labels["label_confidence"] = max(0.0, min(1.0, label_confidence))
        labels.setdefault("operator_actions", []).append("RETRO_LABELED")
        if core == 0:
            outcome = "CORE_DIED"
        elif any(branch_outcomes.get(k) == 0 for k in ("venue", "delegation",
                                                       "deals")):
            outcome = "CORE_HELD_SUB_BRANCH_COLLAPSED"
        else:
            outcome = "CORE_HELD_INTACT"
        labels["outcome_label"] = outcome
        # Prediction errors, when retro probabilities are present.
        probs = json.loads(row["branch_probabilities_json"] or "{}")
        errors = {}
        for key in _BRANCH_KEYS:
            y = branch_outcomes.get(key)
            p = probs.get(_ENGINE_BRANCH[key])
            if y in (0, 1) and p is not None:
                errors[key] = round(float(p) - y, 4)
        if errors:
            labels["prediction_errors"] = errors
        stamp = _now_iso(now_iso)
        conn.execute(
            "UPDATE nbi_backtest_cases SET resolution_labels_json = ? "
            "WHERE case_id = ?",
            (json.dumps(labels), case_id),
        )
        _audit(conn, case_id, "ATTACH_OUTCOME",
               {"branch_outcomes": labels["branch_outcomes"],
                "outcome_label": outcome}, stamp)
        conn.commit()
    finally:
        conn.close()
    return {"attached": True, "case_id": case_id, "outcome_label": outcome}


def attach_price(
    template_id: str, *, realized_return: float, benchmark_return: float,
    ticker: str = "", initial_risk: float | None = None,
    db_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"attached": False, "error": "template not found"}
        rvb = realized_return - benchmark_return
        r_multiple = None
        if initial_risk is not None:
            r_multiple = realized_return / (abs(initial_risk) + 1e-9)
        row = _load_case_row(conn, case_id)
        labels = _labels(row)
        labels["price_ticker"] = ticker.upper()
        stamp = _now_iso(now_iso)
        conn.execute(
            "UPDATE nbi_backtest_cases SET return_vs_benchmark = ?, "
            "r_multiple = ?, resolution_labels_json = ? WHERE case_id = ?",
            (rvb, r_multiple, json.dumps(labels), case_id),
        )
        _audit(conn, case_id, "ATTACH_PRICE",
               {"ticker": ticker, "realized_return": realized_return,
                "benchmark_return": benchmark_return,
                "r_multiple": r_multiple}, stamp)
        conn.commit()
    finally:
        conn.close()
    return {"attached": True, "case_id": case_id,
            "return_vs_benchmark": rvb, "r_multiple": r_multiple}


def attach_probabilities(
    template_id: str, *, probabilities: dict[str, float], basis: str,
    db_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    """Retro branch probabilities.  ``basis`` is REQUIRED: a reconstruction
    must state what it was reconstructed from (contemporaneous odds, dated
    reporting, etc.) or it is not attachable."""
    if not (basis or "").strip():
        return {"attached": False,
                "error": "basis note required for retro probabilities"}
    clean = {}
    for key, engine_branch in _ENGINE_BRANCH.items():
        value = probabilities.get(key)
        if value is not None:
            clean[engine_branch] = max(0.0, min(1.0, float(value)))
    if not clean:
        return {"attached": False, "error": "no probabilities supplied"}
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"attached": False, "error": "template not found"}
        row = _load_case_row(conn, case_id)
        labels = _labels(row)
        labels["probability_basis"] = basis
        stamp = _now_iso(now_iso)
        conn.execute(
            "UPDATE nbi_backtest_cases SET branch_probabilities_json = ?, "
            "resolution_labels_json = ? WHERE case_id = ?",
            (json.dumps(clean), json.dumps(labels), case_id),
        )
        _audit(conn, case_id, "ATTACH_PROBABILITIES",
               {"probabilities": clean, "basis": basis}, stamp)
        conn.commit()
    finally:
        conn.close()
    return {"attached": True, "case_id": case_id, "probabilities": clean}


def _promotion_blockers(
    case: dict[str, Any], quality: dict[str, Any], *, operator_confirmed: bool,
) -> list[str]:
    blockers: list[str] = []
    labels = case.get("resolution_labels") or {}
    if quality["EQS10"] is None or quality["EQS10"] < 7.0:
        blockers.append(f"EQS10 {quality['EQS10']} < 7")
    outcomes = labels.get("branch_outcomes") or {}
    if outcomes.get("core") not in (0, 1):
        blockers.append("outcome labels incomplete (core missing)")
    if not case.get("evidence_refs"):
        blockers.append("no valid evidence refs")
    if not operator_confirmed:
        blockers.append("explicit --operator-confirmed flag required")
    return blockers


def validate_template(
    template_id: str, db_path: Path | str | None = None,
) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"valid": False, "error": "template not found"}
        case = _case_dict(_load_case_row(conn, case_id))
    finally:
        conn.close()
    # Quality is evaluated as if promoted (kind REAL, closed) so the report
    # shows what WOULD block promotion, not the template's frozen state.
    probe = dict(case, case_kind=CASE_KIND_REAL, is_fixture=0,
                 resolution_timestamp=case.get("resolution_timestamp")
                 or "probe")
    quality = compute_case_quality(probe)
    blockers = _promotion_blockers(probe, quality, operator_confirmed=True)
    return {
        "valid": not blockers,
        "case_id": case_id,
        "case_kind": case.get("case_kind"),
        "EQS10": quality["EQS10"],
        "eqs_components": quality["components"],
        "promotion_blockers": blockers,
        "calibration_would_be_eligible": (
            not blockers
            and case.get("return_vs_benchmark") is not None
            and bool(case.get("branch_probabilities"))
        ),
    }


def promote_template(
    template_id: str, *, to_real: bool = False, operator_confirmed: bool = False,
    db_path: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    """The only sanctioned TEMPLATE -> REAL transition.  Refuses anything
    incomplete; sets resolution_timestamp so the case counts as closed."""
    if not to_real:
        return {"promoted": False, "error": "--to-real flag required"}
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"promoted": False, "error": "template not found"}
        row = _load_case_row(conn, case_id)
        case = _case_dict(row)
        if case.get("case_kind") != CASE_KIND_TEMPLATE:
            return {"promoted": False,
                    "error": f"case_kind {case.get('case_kind')} is not TEMPLATE"}
        stamp = _now_iso(now_iso)
        probe = dict(case, case_kind=CASE_KIND_REAL, is_fixture=0,
                     resolution_timestamp=stamp)
        quality = compute_case_quality(probe)
        blockers = _promotion_blockers(
            probe, quality, operator_confirmed=operator_confirmed
        )
        if blockers:
            return {"promoted": False, "case_id": case_id,
                    "EQS10": quality["EQS10"], "blockers": blockers}
        conn.execute(
            "UPDATE nbi_backtest_cases SET case_kind = ?, is_fixture = 0, "
            "resolution_timestamp = ? WHERE case_id = ?",
            (CASE_KIND_REAL, stamp, case_id),
        )
        _audit(conn, case_id, "PROMOTE_TO_REAL",
               {"EQS10": quality["EQS10"],
                "operator_confirmed": operator_confirmed}, stamp)
        conn.commit()
    finally:
        conn.close()
    readiness = summarize_nbi_backtest_readiness(db_path)
    return {
        "promoted": True,
        "case_id": case_id,
        "case_kind": CASE_KIND_REAL,
        "EQS10": quality["EQS10"],
        "calibration_eligible": compute_case_quality(
            dict(probe)
        )["calibration_eligible"],
        "readiness_after": readiness,
        "edge_claim_note": (
            "promotion never opens the edge gate by itself; "
            f"{readiness['cases_real_closed']} real closed case(s) so far"
        ),
        "safety": advisory_safety_stamps(),
    }


# ---------------------------------------------------------------------------
# v1.4 worklist + batch operations
# ---------------------------------------------------------------------------

WORKLIST_PATH_DEFAULT = "runtime/nbi_template_worklist.json"
_MINUTES_BASE = 5
_MINUTES_PER_MISSING = 10


def _template_gaps(case: dict[str, Any]) -> dict[str, bool]:
    labels = case.get("resolution_labels") or {}
    outcomes = labels.get("branch_outcomes") or {}
    return {
        "missing_evidence": not case.get("evidence_refs"),
        "missing_outcomes": outcomes.get("core") not in (0, 1),
        "missing_price": case.get("return_vs_benchmark") is None,
        "missing_branch_probabilities": not case.get("branch_probabilities"),
        "missing_operator_decision": not labels.get("operator_actions"),
    }


def template_worklist(
    db_path: Path | str | None = None, *, limit: int = 10,
) -> list[dict[str, Any]]:
    """Prioritized retro-fill worklist: what exactly each template needs."""
    cases = load_nbi_backtest_cases(db_path, include_fixtures=True)
    items: list[dict[str, Any]] = []
    for case in cases:
        if case.get("case_kind") != CASE_KIND_TEMPLATE:
            continue
        probe = dict(case, case_kind=CASE_KIND_REAL, is_fixture=0,
                     resolution_timestamp=case.get("resolution_timestamp")
                     or "probe")
        quality = compute_case_quality(probe)
        gaps = _template_gaps(case)
        n_missing = sum(1 for v in gaps.values() if v)
        labels = case.get("resolution_labels") or {}
        items.append({
            "template_id": case["case_id"],
            "event_id": case["event_id"],
            "event_name": case.get("initial_narrative", ""),
            **gaps,
            "required_evidence_note": labels.get("required_evidence", ""),
            "estimated_minutes_to_promote": (
                _MINUTES_BASE + _MINUTES_PER_MISSING * n_missing
            ),
            "EQS10_current": quality["EQS10"],
            "calibration_eligible": (
                not any(gaps.values()) and quality["EQS10"] >= 7.0
            ),
            "priority": round(
                quality["EQS10"] - n_missing, 4
            ),
        })
    items.sort(key=lambda t: (-t["priority"], t["template_id"]))
    return items[:limit]


def export_worklist(
    db_path: Path | str | None = None, *,
    out_path: Path | str | None = None, limit: int = 10,
    now_iso: str | None = None,
) -> dict[str, Any]:
    from scripts.runtime_common import REPO_ROOT
    items = template_worklist(db_path, limit=limit)
    target = Path(out_path) if out_path else REPO_ROOT / WORKLIST_PATH_DEFAULT
    payload = {
        "report": "nbi_template_worklist",
        "version": WORKSHOP_VERSION,
        "generated_at": _now_iso(now_iso),
        "doctrine": (
            "worklist items are TEMPLATES awaiting real evidence; none "
            "counts as a case and none moves the edge gate"
        ),
        "items": items,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"exported": True, "path": str(target), "items": len(items)}


def batch_validate(
    db_path: Path | str | None = None,
    template_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    if template_ids is None:
        template_ids = [t["template_id"] for t in
                        template_worklist(db_path, limit=1000)]
    return [validate_template(tid, db_path) for tid in template_ids]


def batch_promote(
    template_ids: list[str], *,
    operator_confirmed: bool = False,
    db_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Promote ONLY the explicitly listed ids; each still runs the full
    single-template gate (incomplete/fixture templates are refused)."""
    results = [
        promote_template(tid, to_real=True,
                         operator_confirmed=operator_confirmed,
                         db_path=db_path, now_iso=now_iso)
        for tid in template_ids
    ]
    return {
        "requested": len(template_ids),
        "promoted": sum(1 for r in results if r.get("promoted")),
        "refused": sum(1 for r in results if not r.get("promoted")),
        "results": results,
        "readiness_after": summarize_nbi_backtest_readiness(db_path),
    }


# ---------------------------------------------------------------------------
# v1.5 evidence packs — the per-template research contract
# ---------------------------------------------------------------------------

EVIDENCE_PACKS_DIR = "runtime/nbi_template_evidence_packs"


def make_evidence_pack(
    template_id: str, *, db_path: Path | str | None = None,
    out_dir: Path | str | None = None, now_iso: str | None = None,
) -> dict[str, Any]:
    """Write the research contract for one template: exactly what evidence
    must be attached before promotion is possible.  Never fills anything."""
    from scripts.runtime_common import REPO_ROOT
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id)
        if case_id is None:
            return {"generated": False, "error": "template not found"}
        case = _case_dict(_load_case_row(conn, case_id))
    finally:
        conn.close()
    labels = case.get("resolution_labels") or {}
    outcomes = labels.get("branch_outcomes") or {}
    gaps = _template_gaps(case)
    narrative = str(case.get("initial_narrative") or "")
    queries = [
        f"{narrative} official statement",
        f"{narrative} outcome date",
        f"{narrative} market reaction benchmark return",
        f"{labels.get('rumor_or_contradiction', '')} debunk confirm".strip(),
    ]
    pack = {
        "template_id": case_id,
        "event_id": case.get("event_id"),
        "event_name": narrative,
        "required_evidence_urls": 1,
        "official_source_needed": True,
        "media_source_needed": True,
        "price_data_needed": gaps["missing_price"],
        "benchmark_needed": gaps["missing_price"],
        "branch_probabilities_needed": gaps["missing_branch_probabilities"],
        "operator_decision_needed": gaps["missing_operator_decision"],
        "invalidation_condition_needed": not labels.get(
            "invalidation_condition"
        ),
        "outcome_labels_needed": gaps["missing_outcomes"],
        "current_missing_fields": [k for k, v in gaps.items() if v],
        "required_evidence_note": labels.get("required_evidence", ""),
        "suggested_research_queries": [q for q in queries if q.strip()],
        "cannot_promote_reason": (
            "template complete — run validate then promote"
            if not any(gaps.values())
            else "missing: " + ", ".join(k for k, v in gaps.items() if v)
        ),
        "generated_at": _now_iso(now_iso),
        "doctrine": (
            "this pack lists requirements; it contains no evidence and "
            "counts for nothing until real citations are attached"
        ),
    }
    target_dir = Path(out_dir) if out_dir else REPO_ROOT / EVIDENCE_PACKS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{case.get('event_id')}.json"
    target.write_text(json.dumps(pack, indent=2), encoding="utf-8")
    return {"generated": True, "path": str(target), "pack": pack}


def validate_evidence_pack(
    template_id: str, *, db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Pack-completion check = the same promotion gate, pack-shaped."""
    check = validate_template(template_id, db_path)
    return {
        "template_id": template_id,
        "pack_complete": bool(check.get("valid")),
        "EQS10": check.get("EQS10"),
        "blockers": check.get("promotion_blockers", []),
        "calibration_would_be_eligible": check.get(
            "calibration_would_be_eligible", False
        ),
    }


def batch_status(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """All templates sorted closest-to-promote first."""
    return template_worklist(db_path, limit=1000)


def load_audit_trail(
    template_id: str, db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        case_id = _resolve_case_id(conn, template_id) or template_id
        rows = conn.execute(
            "SELECT * FROM nbi_template_audit WHERE case_id = ? "
            "ORDER BY audit_id", (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="NBI template workshop: audited TEMPLATE -> REAL upgrades."
    )
    parser.add_argument("--db", default=None)
    sub = parser.add_subparsers(dest="command")
    lst = sub.add_parser("list")
    lst.add_argument("--promotable-first", action="store_true",
                     help="(default ordering is already EQS-descending)")
    sub.add_parser("next", help="single highest-priority worklist item")
    es = sub.add_parser("evidence-status")
    es.add_argument("--template-id", required=True)
    sub.add_parser("batch-validate")
    bp = sub.add_parser("batch-promote")
    bp.add_argument("--ids", required=True, help="comma-separated template ids")
    bp.add_argument("--operator-confirmed", action="store_true")
    pr = sub.add_parser("promote-ready",
                        help="promote every fully-valid template (explicit "
                             "operator confirmation still required)")
    pr.add_argument("--operator-confirmed", action="store_true")
    pr.add_argument("--min-eqs", type=float, default=7.0)
    sub.add_parser("export-worklist")
    mep = sub.add_parser("make-evidence-pack")
    mep.add_argument("--template-id", required=True)
    orc = sub.add_parser("open-research-checklist",
                         help="alias of make-evidence-pack (prints the pack)")
    orc.add_argument("--template-id", required=True)
    vep = sub.add_parser("validate-evidence-pack")
    vep.add_argument("--template-id", required=True)
    sub.add_parser("batch-status")
    show = sub.add_parser("show")
    show.add_argument("--template-id", required=True)
    ev = sub.add_parser("attach-evidence")
    ev.add_argument("--template-id", required=True)
    ev.add_argument("--url", required=True)
    ev.add_argument("--source-type", default="")
    oc = sub.add_parser("attach-outcome")
    oc.add_argument("--template-id", required=True)
    for name in _BRANCH_KEYS:
        oc.add_argument(f"--{name}", type=int, choices=(0, 1), default=None)
    oc.add_argument("--label-confidence", type=float, default=0.9)
    pr = sub.add_parser("attach-price")
    pr.add_argument("--template-id", required=True)
    pr.add_argument("--ticker", default="")
    pr.add_argument("--return", dest="realized_return", type=float,
                    required=True)
    pr.add_argument("--benchmark-return", type=float, required=True)
    pr.add_argument("--initial-risk", type=float, default=None)
    pb = sub.add_parser("attach-probabilities")
    pb.add_argument("--template-id", required=True)
    for name in _BRANCH_KEYS:
        pb.add_argument(f"--p-{name}", type=float, default=None)
    pb.add_argument("--basis", required=True)
    va = sub.add_parser("validate")
    va.add_argument("--template-id", required=True)
    pm = sub.add_parser("promote")
    pm.add_argument("--template-id", required=True)
    pm.add_argument("--to-real", action="store_true")
    pm.add_argument("--operator-confirmed", action="store_true")

    args = parser.parse_args(argv)
    db = args.db
    if args.command == "list":
        print(json.dumps(template_worklist(db, limit=1000), indent=2))
    elif args.command == "next":
        items = template_worklist(db, limit=1)
        print(json.dumps(items[0] if items else {"empty": True}, indent=2))
    elif args.command == "evidence-status":
        items = [t for t in template_worklist(db, limit=1000)
                 if args.template_id in (t["template_id"], t["event_id"])]
        print(json.dumps(items[0] if items
                         else {"error": "template not found"}, indent=2))
    elif args.command == "batch-validate":
        print(json.dumps(batch_validate(db), indent=2))
    elif args.command == "batch-promote":
        ids = [t.strip() for t in args.ids.split(",") if t.strip()]
        out = batch_promote(ids, operator_confirmed=args.operator_confirmed,
                            db_path=db)
        print(json.dumps(out, indent=2, default=str))
        return 0 if out["refused"] == 0 else 1
    elif args.command == "promote-ready":
        ready = [
            v["case_id"] for v in batch_validate(db)
            if v.get("valid") and (v.get("EQS10") or 0) >= args.min_eqs
        ]
        out = batch_promote(ready, operator_confirmed=args.operator_confirmed,
                            db_path=db)
        print(json.dumps(out, indent=2, default=str))
    elif args.command == "export-worklist":
        print(json.dumps(export_worklist(db), indent=2))
    elif args.command in ("make-evidence-pack", "open-research-checklist"):
        print(json.dumps(
            make_evidence_pack(args.template_id, db_path=db),
            indent=2, default=str,
        ))
    elif args.command == "validate-evidence-pack":
        print(json.dumps(
            validate_evidence_pack(args.template_id, db_path=db), indent=2
        ))
    elif args.command == "batch-status":
        print(json.dumps(batch_status(db), indent=2))
    elif args.command == "show":
        print(json.dumps(validate_template(args.template_id, db), indent=2))
        print(json.dumps(load_audit_trail(args.template_id, db), indent=2))
    elif args.command == "attach-evidence":
        print(json.dumps(attach_evidence(
            args.template_id, url=args.url, source_type=args.source_type,
            db_path=db,
        ), indent=2))
    elif args.command == "attach-outcome":
        outcomes = {
            name: getattr(args, name) for name in _BRANCH_KEYS
            if getattr(args, name) is not None
        }
        print(json.dumps(attach_outcome(
            args.template_id, branch_outcomes=outcomes,
            label_confidence=args.label_confidence, db_path=db,
        ), indent=2))
    elif args.command == "attach-price":
        print(json.dumps(attach_price(
            args.template_id, realized_return=args.realized_return,
            benchmark_return=args.benchmark_return, ticker=args.ticker,
            initial_risk=args.initial_risk, db_path=db,
        ), indent=2))
    elif args.command == "attach-probabilities":
        probs = {
            name: getattr(args, f"p_{name}") for name in _BRANCH_KEYS
            if getattr(args, f"p_{name}") is not None
        }
        print(json.dumps(attach_probabilities(
            args.template_id, probabilities=probs, basis=args.basis,
            db_path=db,
        ), indent=2))
    elif args.command == "validate":
        print(json.dumps(validate_template(args.template_id, db), indent=2))
    elif args.command == "promote":
        out = promote_template(
            args.template_id, to_real=args.to_real,
            operator_confirmed=args.operator_confirmed, db_path=db,
        )
        print(json.dumps(out, indent=2, default=str))
        return 0 if out.get("promoted") else 1
    else:
        parser.print_help()
        return 2
    return 0


__all__ = [
    "WORKSHOP_VERSION",
    "list_templates", "attach_evidence", "attach_outcome", "attach_price",
    "attach_probabilities", "validate_template", "promote_template",
    "template_worklist", "export_worklist", "batch_validate",
    "batch_promote", "make_evidence_pack", "validate_evidence_pack",
    "batch_status", "load_audit_trail", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
