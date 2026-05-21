"""Source independence + ant-mill audit — five masks, one face.

Operationalises the doctrine: *five models repeating one catalyst is one
signal wearing five masks*, not five confirmations.  Pure, deterministic,
advisory-only.

Reflection formulas (implemented exactly)

    source_independence_score = 1 - duplicate_catalysts / max(total_catalysts, 1)
    ant_mill_risk             = model_agreement_score * (1 - source_independence_score)

The richer classification (forced contradiction search, invalidation question,
promotion-block reasoning) is delegated to the already-tested
``scripts.complex_systems_diagnostics.detect_ant_mill`` so the two never drift.

Input rows (one per model mention) may carry:

    model_name, ticker, catalyst_text, catalyst_fingerprint,
    source_urls_or_refs, source_family, timestamp_utc, model_agreement

Either ``catalyst_fingerprint`` or ``catalyst_text`` identifies the catalyst.

Safety
------
Read-only.  No DB writes, no broker calls, no execution state.  ant-mill risk
causes an *advisory downgrade* (promotion_downgrade_recommendation), never an
execution block — there is no execution path to block.

Usage
-----
    python scripts/source_independence_audit.py           # DB fingerprints
    python scripts/source_independence_audit.py --json
    python scripts/source_independence_audit.py --input model_reports.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from runtime_common import utc_timestamp  # type: ignore[no-redef]

try:
    from scripts.complex_systems_diagnostics import detect_ant_mill
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from complex_systems_diagnostics import detect_ant_mill  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO_ROOT / "runtime" / "mvp_local.db"

ADVISORY_DISCLAIMER = (
    "Advisory-only source-independence diagnostic. High ant-mill risk triggers "
    "an advisory DOWNGRADE and a human-review flag - never an execution block, "
    "because no execution path exists. No broker calls."
)


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return lo
    if x != x:
        return lo
    return max(lo, min(hi, x))


def _catalyst_fingerprint(row: dict[str, Any]) -> str:
    fp = str(row.get("catalyst_fingerprint") or "").strip().lower()
    if fp:
        return fp
    text = str(row.get("catalyst_text") or "").strip().lower()
    if not text:
        return ""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def analyze_catalysts(rows: Any) -> dict[str, Any]:
    """Pure analysis of a catalyst corpus across models for one cohort.

    ``rows`` is a list of per-model mention dicts.  Returns the reflection's
    independence/ant-mill metrics plus the richer ant-mill classification.
    """
    items = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    catalysts = [(_catalyst_fingerprint(r), r) for r in items]
    catalysts = [(fp, r) for fp, r in catalysts if fp]

    total_catalysts = len(catalysts)
    base: dict[str, Any] = {
        "model_count": len({str(r.get("model_name") or "").lower() for r in items if r.get("model_name")}),
        "total_catalysts": total_catalysts,
        "unique_catalyst_count": 0,
        "duplicate_catalyst_count": 0,
        "source_family_count": len({str(r.get("source_family") or "").lower() for r in items if r.get("source_family")}),
        "source_independence_score": 1.0,
        "model_agreement_score": 0.0,
        "ant_mill_risk": 0.0,
        "single_source_consensus": False,
        "ai_echo_risk": False,
        "high_agreement_low_independence": False,
        "promotion_downgrade_recommendation": "no_change",
        "human_review_required": True,
    }
    if total_catalysts == 0:
        base["source_overlap_note"] = "insufficient_data: no catalysts supplied."
        return _stamp(base)

    fingerprints = [fp for fp, _ in catalysts]
    unique = len(set(fingerprints))
    duplicate_catalyst_count = total_catalysts - unique

    # Reflection formula 1.
    source_independence_score = round(
        1.0 - duplicate_catalyst_count / max(total_catalysts, 1), 4
    )

    # model_agreement_score: prefer explicit values; else derive from how
    # concentrated the corpus is on its most-repeated catalyst.
    explicit = [
        _clamp(r.get("model_agreement"))
        for _, r in catalysts
        if r.get("model_agreement") is not None
    ]
    if explicit:
        model_agreement_score = round(sum(explicit) / len(explicit), 4)
    else:
        freq: dict[str, int] = {}
        for fp in fingerprints:
            freq[fp] = freq.get(fp, 0) + 1
        model_agreement_score = round(max(freq.values()) / max(total_catalysts, 1), 4)

    # Reflection formula 2.
    ant_mill_risk = round(
        model_agreement_score * (1.0 - source_independence_score), 4
    )

    model_count = base["model_count"] or total_catalysts
    single_source_consensus = bool(unique <= 1 and model_count >= 2)
    high_agreement_low_independence = bool(
        model_agreement_score >= 0.7 and source_independence_score < 0.4
    )
    ai_echo_risk = bool(high_agreement_low_independence or single_source_consensus)

    if ant_mill_risk >= 0.5 or single_source_consensus or high_agreement_low_independence:
        downgrade = "downgrade"
    elif ant_mill_risk >= 0.25:
        downgrade = "watch"
    else:
        downgrade = "no_change"

    # Richer classification from the shared engine (kept consistent).
    engine = detect_ant_mill(
        {"model_agreement": model_agreement_score},
        independence_score=source_independence_score,
    )

    base.update({
        "unique_catalyst_count": unique,
        "duplicate_catalyst_count": duplicate_catalyst_count,
        "source_independence_score": source_independence_score,
        "model_agreement_score": model_agreement_score,
        "ant_mill_risk": ant_mill_risk,
        "single_source_consensus": single_source_consensus,
        "ai_echo_risk": ai_echo_risk,
        "high_agreement_low_independence": high_agreement_low_independence,
        "promotion_downgrade_recommendation": downgrade,
        "forced_contradiction_required": bool(engine.get("forced_contradiction_required")),
        "invalidation_question": engine.get("invalidation_question"),
        "source_overlap_note": (
            f"{model_count} models -> {unique} distinct catalyst(s); "
            f"{duplicate_catalyst_count} duplicate mention(s)."
        ),
    })
    return _stamp(base)


def _stamp(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    out.update(_contract.advisory_safety_stamps())
    return out


def _readonly_connect(db_path: Path) -> sqlite3.Connection | None:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        try:
            conn = sqlite3.connect(str(db_path))
        except sqlite3.Error:
            return None
    conn.row_factory = sqlite3.Row
    return conn


def _rows_from_fingerprints(db_path: Path) -> list[dict[str, Any]]:
    """Expand duplicate_fingerprints into per-mention catalyst rows.

    A fingerprint seen N times is N model mentions of the same catalyst —
    exactly the echo the audit must surface.
    """
    conn = _readonly_connect(db_path)
    if conn is None:
        return []
    rows: list[dict[str, Any]] = []
    try:
        for r in conn.execute(
            "SELECT fingerprint, ticker, event_id, seen_count, thesis_excerpt,"
            " source_type FROM duplicate_fingerprints"
        ).fetchall():
            d = dict(r)
            seen = max(int(d.get("seen_count") or 1), 1)
            for i in range(seen):
                rows.append({
                    "model_name": f"mention_{i}",
                    "ticker": d.get("ticker"),
                    "catalyst_fingerprint": d.get("fingerprint"),
                    "catalyst_text": d.get("thesis_excerpt"),
                    "source_family": d.get("source_type"),
                })
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return rows


def build_report(
    rows: list[dict[str, Any]] | None = None,
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Build the per-cohort source-independence report (read-only)."""
    db = Path(db_path) if db_path is not None else DEFAULT_DB
    if rows is None:
        rows = _rows_from_fingerprints(db)
        source = "duplicate_fingerprints"
    else:
        source = "provided_rows"

    # Group by ticker so each cohort is analysed independently.
    cohorts: dict[str, list[dict[str, Any]]] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        key = str(r.get("ticker") or "_GLOBAL").upper()
        cohorts.setdefault(key, []).append(r)

    per_ticker = {tkr: analyze_catalysts(rs) for tkr, rs in cohorts.items()}
    flagged = sorted(
        tkr for tkr, a in per_ticker.items()
        if a["promotion_downgrade_recommendation"] in {"downgrade", "watch"}
    )
    return {
        "report": "source_independence_audit",
        "source": source,
        "db_path": str(db),
        "advisory_disclaimer": ADVISORY_DISCLAIMER,
        "cohort_count": len(per_ticker),
        "flagged_cohorts": flagged,
        "per_ticker": per_ticker,
        "human_review_required": True,
        **_contract.advisory_safety_stamps(),
        "generated_at": utc_timestamp(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="source_independence_audit.py",
        description=(
            "Detect catalyst echo across models (five masks, one face). "
            "Advisory downgrade only — never an execution block. No broker calls."
        ),
    )
    p.add_argument("--db-path", type=Path, default=None)
    p.add_argument("--input", type=Path, default=None,
                   help="JSON file: list of per-model mention rows.")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rows = None
    if args.input is not None:
        try:
            rows = json.loads(Path(args.input).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ERROR] could not read --input: {exc}")
            return 1
        if not isinstance(rows, list):
            print("[ERROR] --input must be a JSON list of mention rows.")
            return 1
    rep = build_report(rows, db_path=args.db_path)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print("Source Independence + Ant-Mill Audit (advisory-only)")
        print("=" * 52)
        print(f"  source         : {rep['source']}")
        print(f"  cohorts        : {rep['cohort_count']}")
        print(f"  flagged        : {rep['flagged_cohorts']}")
        for tkr, a in sorted(rep["per_ticker"].items()):
            print(f"  [{tkr}] independence={a['source_independence_score']} "
                  f"agreement={a['model_agreement_score']} "
                  f"ant_mill={a['ant_mill_risk']} "
                  f"-> {a['promotion_downgrade_recommendation']}")
        print(f"\n  {rep['advisory_disclaimer']}")
    return 0


__all__ = ["ADVISORY_DISCLAIMER", "analyze_catalysts", "build_report"]


if __name__ == "__main__":
    raise SystemExit(main())
