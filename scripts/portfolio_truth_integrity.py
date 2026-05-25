"""Portfolio truth integrity — H = V \\ (C ∪ S ∪ D).

Integrated Sprint — Part 4 (Kanté defensive batch 2).  Computes the
*manageable* holdings set ``H`` by subtracting Closed / Stale / Disputed
position sets from the Verified-current-positions set ``V``.  Every
exclusion is recorded with a reason so the operator can audit why a
position isn't surfaced for review.

Pure module — operates on caller-supplied dict rows.  Optionally writes
the summary artifact the release gate consumes at
``runtime/release/portfolio_truth_summary.json``.

No broker.  No execution.  Advisory-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "portfolio_truth_summary.json"
)

# Valid lifecycle statuses for the dispute logic.
STATUS_VERIFIED = "VERIFIED"
STATUS_CLOSED = "CLOSED"
STATUS_STALE = "STALE"
STATUS_DISPUTED = "DISPUTED"
VALID_STATUSES: frozenset[str] = frozenset({
    STATUS_VERIFIED, STATUS_CLOSED, STATUS_STALE, STATUS_DISPUTED,
})


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload_hash(row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"),
                            default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def classify_positions(
    verified: Iterable[dict[str, Any]],
    closed: Iterable[dict[str, Any]],
    stale: Iterable[dict[str, Any]],
    disputed: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Apply ``H = V \\ (C ∪ S ∪ D)``.

    Each input row needs a ``symbol`` key.  ``reason`` / ``source`` /
    ``source_timestamp_utc`` are propagated to lineage rows when present.
    """
    def _symbols(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            sym = str(r.get("symbol") or "").strip().upper()
            if not sym:
                continue
            out.setdefault(sym, dict(r))
        return out

    V = _symbols(verified)
    C = _symbols(closed)
    S = _symbols(stale)
    D = _symbols(disputed)

    closed_syms = set(C)
    stale_syms = set(S)
    disputed_syms = set(D)
    excluded = closed_syms | stale_syms | disputed_syms
    manageable = {s: r for s, r in V.items() if s not in excluded}

    lineage: list[dict[str, Any]] = []
    for sym, row in V.items():
        excluded_by: list[str] = []
        if sym in closed_syms:
            excluded_by.append("C")
        if sym in stale_syms:
            excluded_by.append("S")
        if sym in disputed_syms:
            excluded_by.append("D")
        lineage.append({
            "symbol": sym,
            "source": str(row.get("source") or "verified_current_holdings"),
            "source_timestamp_utc": row.get("source_timestamp_utc"),
            "status": STATUS_VERIFIED if not excluded_by else "EXCLUDED",
            "reason": row.get("reason") or (
                "verified position included in H" if not excluded_by
                else "verified but appears in excluded set"
            ),
            "included_in_H": 1 if not excluded_by else 0,
            "excluded_by_set": ",".join(excluded_by) if excluded_by else "",
            "payload_hash": _payload_hash(row),
            "advisory_only": 1,
        })
    # Lineage entries for purely-excluded positions (those not in V).
    for sym, row in C.items():
        if sym in V:
            continue
        lineage.append({
            "symbol": sym, "source": str(row.get("source") or "closed_positions"),
            "source_timestamp_utc": row.get("source_timestamp_utc"),
            "status": STATUS_CLOSED, "reason": row.get("reason") or "closed",
            "included_in_H": 0, "excluded_by_set": "C",
            "payload_hash": _payload_hash(row), "advisory_only": 1,
        })
    for sym, row in S.items():
        if sym in V or sym in C:
            continue
        lineage.append({
            "symbol": sym, "source": str(row.get("source") or "stale_positions"),
            "source_timestamp_utc": row.get("source_timestamp_utc"),
            "status": STATUS_STALE, "reason": row.get("reason") or "stale",
            "included_in_H": 0, "excluded_by_set": "S",
            "payload_hash": _payload_hash(row), "advisory_only": 1,
        })
    for sym, row in D.items():
        if sym in V or sym in C or sym in S:
            continue
        lineage.append({
            "symbol": sym, "source": str(row.get("source") or "disputed_positions"),
            "source_timestamp_utc": row.get("source_timestamp_utc"),
            "status": STATUS_DISPUTED, "reason": row.get("reason") or "disputed",
            "included_in_H": 0, "excluded_by_set": "D",
            "payload_hash": _payload_hash(row), "advisory_only": 1,
        })

    return {
        "manageable": manageable,
        "verified": V,
        "closed": C,
        "stale": S,
        "disputed": D,
        "lineage": lineage,
        "excluded_symbols": sorted(excluded & set(V)),
    }


def _clamp01(value: float) -> float:
    if value < 0:
        return 0.0
    if value > 1:
        return 1.0
    return value


def portfolio_truth_score(
    *,
    no_phantom_positions_in_H: bool,
    all_H_have_verified_source: bool,
    closed_positions_excluded: bool,
    stale_positions_excluded: bool,
    disputed_positions_excluded: bool,
) -> float:
    raw = (
        0.30 * (1.0 if no_phantom_positions_in_H else 0.0)
        + 0.25 * (1.0 if all_H_have_verified_source else 0.0)
        + 0.20 * (1.0 if closed_positions_excluded else 0.0)
        + 0.15 * (1.0 if stale_positions_excluded else 0.0)
        + 0.10 * (1.0 if disputed_positions_excluded else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def build_summary(
    *,
    verified: Iterable[dict[str, Any]] | None = None,
    closed: Iterable[dict[str, Any]] | None = None,
    stale: Iterable[dict[str, Any]] | None = None,
    disputed: Iterable[dict[str, Any]] | None = None,
    fixture_mode: bool = True,
) -> dict[str, Any]:
    """Build the summary dict.

    With no inputs (the default fixture case) we use a deterministic 3-symbol
    panel that exercises every exclusion path so the score is reproducible
    in CI.
    """
    if verified is None and closed is None and stale is None and disputed is None:
        verified = [
            {"symbol": "AAA", "source": "broker_csv",
             "source_timestamp_utc": "2026-05-23T22:00:00Z"},
            {"symbol": "BBB", "source": "broker_csv",
             "source_timestamp_utc": "2026-05-23T22:00:00Z"},
            {"symbol": "CCC", "source": "broker_csv",
             "source_timestamp_utc": "2026-05-23T22:00:00Z"},
            {"symbol": "DDD", "source": "broker_csv",
             "source_timestamp_utc": "2026-05-23T22:00:00Z"},
        ]
        closed = [
            {"symbol": "BBB", "source": "closed_ledger",
             "reason": "closed 2026-05-22 — full exit"},
        ]
        stale = [
            {"symbol": "CCC", "source": "moltbook",
             "reason": "stale — no broker confirmation in 30d"},
        ]
        disputed = [
            {"symbol": "DDD", "source": "operator_dispute",
             "reason": "operator disputed the broker row"},
        ]
    classification = classify_positions(
        verified or [], closed or [], stale or [], disputed or [],
    )
    H = classification["manageable"]
    V = classification["verified"]
    C = classification["closed"]
    S = classification["stale"]
    D = classification["disputed"]

    closed_in_h = any(sym in C for sym in H)
    stale_in_h = any(sym in S for sym in H)
    disputed_in_h = any(sym in D for sym in H)
    all_h_verified = all(sym in V for sym in H)
    # A "phantom" is a manageable symbol with no verified source row.
    no_phantoms = all(
        bool(V.get(sym, {}).get("source"))
        for sym in H
    )

    score = portfolio_truth_score(
        no_phantom_positions_in_H=no_phantoms,
        all_H_have_verified_source=all_h_verified,
        closed_positions_excluded=not closed_in_h,
        stale_positions_excluded=not stale_in_h,
        disputed_positions_excluded=not disputed_in_h,
    )

    return {
        "report": "portfolio_truth_summary",
        "ok": score >= 9.5,
        "generated_at_utc": _utc_iso(),
        "fixture_mode": bool(fixture_mode),
        "verified_positions_count": len(V),
        "closed_positions_count": len(C),
        "stale_positions_count": len(S),
        "disputed_positions_count": len(D),
        "manageable_positions_count": len(H),
        "manageable_positions": sorted(H.keys()),
        "excluded_from_H": classification["excluded_symbols"],
        "lineage": classification["lineage"],
        "no_phantom_positions_in_H": bool(no_phantoms),
        "all_H_have_verified_source": bool(all_h_verified),
        "closed_positions_excluded": not closed_in_h,
        "stale_positions_excluded": not stale_in_h,
        "disputed_positions_excluded": not disputed_in_h,
        "portfolio_truth_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(
    path: Path | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(**kwargs)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="portfolio_truth_integrity.py",
        description=(
            "Build the H = V \\ (C ∪ S ∪ D) snapshot and write the "
            "portfolio_truth_summary.json artifact. Advisory-only; no broker."
        ),
    )
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"portfolio_truth_score = {summary['portfolio_truth_score']}")
        print(f"  manageable H = {summary['manageable_positions']}")
        print(f"  excluded    = {summary['excluded_from_H']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "STATUS_VERIFIED", "STATUS_CLOSED", "STATUS_STALE", "STATUS_DISPUTED",
    "classify_positions",
    "portfolio_truth_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
