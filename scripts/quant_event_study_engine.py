"""Quant hackathon — reusable event-study engine (mission 11).

For events j = 1..N with per-event abnormal returns AR_{j,h}:

    AAR_h  = (1/N) Σ_j AR_{j,h}
    CAAR_h = Σ_{τ≤h} AAR_τ

Contract: every statistic carries its sample count N; below ``n_min`` the
study reports INSUFFICIENT_DATA rather than a number.  Confidence comes
from both normal theory and seeded bootstrap.  Pure/deterministic.
"""
from __future__ import annotations

from typing import Any

from scripts.quant_statistics_engine import (
    INSUFFICIENT_DATA,
    OK,
    bootstrap_ci,
    mean_with_ci,
)


def event_study(ar_by_event: dict[str, dict[int, float]], *,
                horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
                n_min: int = 8) -> dict[str, Any]:
    """Run an event study over per-event AR ladders.

    ``ar_by_event`` maps event_id -> {horizon: AR}.  Missing horizons for
    an event simply reduce that horizon's N (reported); they are never
    imputed as zero.
    """
    out: dict[str, Any] = {"n_events": len(ar_by_event),
                           "horizons": {}, "n_min": n_min}
    caar = 0.0
    prev_h = 0
    for h in sorted(horizons):
        ars = [lad[h] for lad in ar_by_event.values()
               if h in lad and lad[h] is not None]
        stats = mean_with_ci(ars, n_min=n_min)
        row: dict[str, Any] = {"h": h, "n": len(ars), "stats": stats}
        if stats["status"] == OK:
            row["hit_rate"] = sum(1 for a in ars if a > 0) / len(ars)
            row["bootstrap"] = bootstrap_ci(ars, n_min=n_min)
            row["tails"] = {"min": min(ars), "max": max(ars)}
            # Incremental AAR for the CAAR curve (per-horizon step).
            caar += stats["mean"] - (0.0 if prev_h == 0 else 0.0)
            row["aar"] = stats["mean"]
            row["caar_proxy"] = stats["mean"]  # window ARs already cumulative
            prev_h = h
        else:
            row["hit_rate"] = None
        out["horizons"][h] = row
    usable = [h for h, r in out["horizons"].items()
              if r["stats"].get("status") == OK]
    out["status"] = OK if usable else INSUFFICIENT_DATA
    out["usable_horizons"] = usable
    out["note"] = ("window ARs are cumulative from t by construction; "
                   "the horizon ladder IS the CAAR curve")
    return out


def compare_to_baseline(study: dict[str, Any],
                        baseline_study: dict[str, Any]) -> dict[str, Any]:
    """Signal-vs-baseline AAR comparison per horizon (mission 31).

    Both inputs are ``event_study`` outputs.  A horizon only compares when
    BOTH sides have sufficient N.
    """
    rows = {}
    for h, row in study.get("horizons", {}).items():
        base = baseline_study.get("horizons", {}).get(h)
        if (row["stats"].get("status") == OK and base
                and base["stats"].get("status") == OK):
            rows[h] = {
                "h": h,
                "signal_aar": row["stats"]["mean"], "signal_n": row["n"],
                "baseline_aar": base["stats"]["mean"], "baseline_n": base["n"],
                "edge_vs_baseline": row["stats"]["mean"] - base["stats"]["mean"],
            }
        else:
            rows[h] = {"h": h, "status": INSUFFICIENT_DATA}
    usable = [r for r in rows.values() if "edge_vs_baseline" in r]
    return {"status": OK if usable else INSUFFICIENT_DATA,
            "horizons": rows,
            "beats_baseline_horizons": [r["h"] for r in usable
                                        if r["edge_vs_baseline"] > 0]}
