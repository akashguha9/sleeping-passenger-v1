"""Score-diff explainer — "why did this score move?" (Pass 5, Phase 9).

For a linear advisory score S_t = Σ_j w_j·x_{j,t}, the change between
two snapshots decomposes EXACTLY:

    ΔS = Σ_j w_{j,t1}·Δx_j  (feature drift)
       + Σ_j x_{j,t1}·Δw_j  (weight/model change)
       + Σ_j Δw_j·Δx_j      (interaction)

Nonlinear scorers get a local ablation approximation, loudly labeled
``approximate`` with a residual term — never a faked linear story.

Each explanation also reconciles the EVIDENCE diff (added / removed /
gone-stale evidence ids), highlights manual edits and model-version
changes, and flags the suspicious case: score moved but no evidence
changed. Output: reports/score_change_explanations/ (gitignored).
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = _REPO_ROOT / "reports" / "score_change_explanations"
_STALE_DAYS = 14.0


class ExplainError(ValueError):
    """Raised on malformed snapshots."""


def _snapshot_ok(s: dict, name: str) -> None:
    for field in ("weights", "features"):
        if not isinstance(s.get(field), dict) or not s[field]:
            raise ExplainError(f"{name}: missing/empty {field!r}")
    if set(s["weights"]) != set(s["features"]):
        raise ExplainError(f"{name}: weight/feature key mismatch")


def linear_decomposition(snap1: dict, snap2: dict) -> dict:
    """Exact ΔS decomposition for linear scores."""
    _snapshot_ok(snap1, "t1")
    _snapshot_ok(snap2, "t2")
    keys = sorted(set(snap1["weights"]) | set(snap2["weights"]))
    w1 = {k: float(snap1["weights"].get(k, 0.0)) for k in keys}
    w2 = {k: float(snap2["weights"].get(k, 0.0)) for k in keys}
    x1 = {k: float(snap1["features"].get(k, 0.0)) for k in keys}
    x2 = {k: float(snap2["features"].get(k, 0.0)) for k in keys}
    s1 = sum(w1[k] * x1[k] for k in keys)
    s2 = sum(w2[k] * x2[k] for k in keys)
    feature_term = {k: w1[k] * (x2[k] - x1[k]) for k in keys}
    weight_term = {k: x1[k] * (w2[k] - w1[k]) for k in keys}
    interaction = {k: (w2[k] - w1[k]) * (x2[k] - x1[k]) for k in keys}
    total = (sum(feature_term.values()) + sum(weight_term.values())
             + sum(interaction.values()))
    assert abs(total - (s2 - s1)) < 1e-9, "linear decomposition must be exact"
    return {
        "mode": "exact_linear",
        "score_t1": s1, "score_t2": s2, "delta": s2 - s1,
        "feature_contributions": feature_term,
        "weight_contributions": weight_term,
        "interaction_terms": interaction,
    }


def ablation_decomposition(score_fn, snap1: dict, snap2: dict) -> dict:
    """Local one-at-a-time ablation for nonlinear scorers (approximate)."""
    _snapshot_ok(snap1, "t1")
    _snapshot_ok(snap2, "t2")
    x1, x2 = snap1["features"], snap2["features"]
    s1, s2 = float(score_fn(x1)), float(score_fn(x2))
    contributions = {}
    for k in x1:
        hybrid = dict(x1)
        hybrid[k] = x2.get(k, x1[k])
        contributions[k] = float(score_fn(hybrid)) - s1
    residual = (s2 - s1) - sum(contributions.values())
    return {
        "mode": "approximate_ablation",
        "warning": ("nonlinear scorer — one-at-a-time ablation is an "
                    "APPROXIMATION; residual interaction term reported, "
                    "not hidden"),
        "score_t1": s1, "score_t2": s2, "delta": s2 - s1,
        "feature_contributions": contributions,
        "residual_interaction": residual,
    }


def _evidence_diff(snap1: dict, snap2: dict) -> dict:
    e1 = {e["evidence_id"]: e for e in snap1.get("evidence", [])}
    e2 = {e["evidence_id"]: e for e in snap2.get("evidence", [])}
    added = sorted(set(e2) - set(e1))
    removed = sorted(set(e1) - set(e2))
    stale = sorted(
        eid for eid, e in e2.items()
        if isinstance(e.get("freshness_days"), (int, float))
        and e["freshness_days"] > _STALE_DAYS
    )
    return {"added": added, "removed": removed, "now_stale": stale,
            "unchanged": sorted(set(e1) & set(e2))}


def explain(
    snap1: dict,
    snap2: dict,
    *,
    score_fn=None,
    recommendation_threshold: float = 0.6,
) -> dict:
    """Full explanation between two signal snapshots.

    Snapshot fields: ``weights``, ``features``, optional ``evidence``
    (ledger dicts), ``model_version``, ``manual_edits`` (list of field
    names a human changed), ``timestamp``.
    """
    decomposition = (
        ablation_decomposition(score_fn, snap1, snap2)
        if score_fn is not None
        else linear_decomposition(snap1, snap2)
    )
    evidence = _evidence_diff(snap1, snap2)
    flags: list[str] = []
    causes: list[str] = []

    if snap1.get("model_version") != snap2.get("model_version"):
        causes.append(
            f"model version changed {snap1.get('model_version')!r} → "
            f"{snap2.get('model_version')!r}"
        )
    manual = sorted(set(snap2.get("manual_edits", [])))
    if manual:
        causes.append(f"MANUAL EDIT of {manual} — human-attributed change")
        flags.append("manual_edit")
    if evidence["added"]:
        causes.append(f"fresh evidence added: {evidence['added'][:5]}")
    if evidence["removed"]:
        causes.append(f"evidence removed: {evidence['removed'][:5]}")
    if evidence["now_stale"]:
        causes.append(
            f"evidence went STALE (> {_STALE_DAYS:.0f}d): {evidence['now_stale'][:5]}"
        )
        flags.append("staleness_driven")

    moved = abs(decomposition["delta"]) > 1e-9
    evidence_changed = bool(evidence["added"] or evidence["removed"]
                            or evidence["now_stale"] or manual
                            or snap1.get("model_version") != snap2.get("model_version"))
    if moved and not evidence_changed:
        flags.append("score_moved_without_evidence_change")
        causes.append(
            "SCORE MOVED WITHOUT ANY EVIDENCE/WEIGHT/MANUAL CHANGE ON "
            "RECORD — investigate before trusting the new value"
        )

    # Reliability direction: more fresh evidence → more reliable; staleness
    # or unexplained movement → less.
    if evidence["added"] and not evidence["now_stale"]:
        reliability = "more_reliable"
    elif evidence["now_stale"] or "score_moved_without_evidence_change" in flags:
        reliability = "less_reliable"
    else:
        reliability = "unchanged"

    rec1 = decomposition["score_t1"] >= recommendation_threshold
    rec2 = decomposition["score_t2"] >= recommendation_threshold
    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "decomposition": decomposition,
        "evidence_diff": evidence,
        "causes": causes,
        "flags": flags,
        "reliability_direction": reliability,
        "recommendation_changed": rec1 != rec2,
        "recommendation_t1": "ACT_CANDIDATE" if rec1 else "ABSTAIN",
        "recommendation_t2": "ACT_CANDIDATE" if rec2 else "ABSTAIN",
        "human_review_required": True,
        "advisory_only": True,
    }


def write_explanation(result: dict, signal_id: str = "signal",
                      out_dir: Path | None = None) -> Path:
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{signal_id}_{stamp}.md"
    d = result["decomposition"]
    lines = [
        f"# Why did {signal_id} move?", "",
        f"Generated: {result['generated_utc']} · advisory-only · human review required", "",
        f"Score: {d['score_t1']:.4f} → {d['score_t2']:.4f} (Δ {d['delta']:+.4f}) "
        f"· mode: {d['mode']}",
        f"Recommendation: {result['recommendation_t1']} → {result['recommendation_t2']}"
        + (" **(CHANGED)**" if result["recommendation_changed"] else ""),
        f"Reliability direction: {result['reliability_direction']}", "",
        "## Causes",
    ]
    lines += [f"- {c}" for c in result["causes"]] or ["- no attributed cause"]
    lines += ["", "## Top contributions", ""]
    contribs = sorted(d["feature_contributions"].items(),
                      key=lambda kv: abs(kv[1]), reverse=True)[:8]
    for k, v in contribs:
        lines.append(f"- {k}: {v:+.4f}")
    if "warning" in d:
        lines += ["", f"> ⚠️ {d['warning']} (residual {d['residual_interaction']:+.4f})"]
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
