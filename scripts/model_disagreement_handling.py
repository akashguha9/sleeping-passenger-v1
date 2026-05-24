"""Model disagreement handling — weighted variance, contradiction pairs,
DIABLO veto, CQS adjustment.

Integrated Sprint — Part 9 (Kanté defensive batch 2).  Each asset receives:

* a weighted-by-reliability mean stance ``μ_a``,
* a weighted variance ``σ²_a`` and disagreement ``D_a``,
* a contradiction-pair count + score,
* a final disagreement risk that combines them with the DIABLO veto flag,
* a CQS adjustment that shrinks the candidate's score in proportion to risk.

Routing:

  any DIABLO        -> DIABLO_REVIEW    may_promote=False
  risk >= 0.65      -> RESEARCH_CANDIDATE
  0.40..0.65        -> WATCHLIST_UNCERTAIN
  else              -> PASS_THROUGH

Writes ``runtime/release/model_disagreement_summary.json``.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "model_disagreement_summary.json"
)

EPS = 1e-9
CONTRADICTION_MAGNITUDE = 0.75

STANCE_NUMERIC: dict[str, float] = {
    "BULLISH": 1.0,
    "NEUTRAL": 0.0,
    "WAIT": 0.0,
    "BEARISH": -1.0,
    "AVOID": -0.5,
    "NO_NEW_RISK": -0.75,
    "DIABLO": -1.0,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp01(v: float) -> float:
    if v < 0:
        return 0.0
    if v > 1:
        return 1.0
    return v


def stance_numeric(stance: str) -> float:
    return STANCE_NUMERIC.get(str(stance).upper(), 0.0)


def evaluate_asset(
    asset_id: str,
    models: Iterable[dict[str, Any]],
    *,
    cqs_base: float = 0.7,
) -> dict[str, Any]:
    """Compute disagreement metrics + routing decision for one asset.

    Each ``models`` row needs:
      * model_name           — string
      * stance               — string (one of STANCE_NUMERIC keys)
      * confidence           — float in [0,1]
      * reliability          — float in [0,1] (model reliability weight)
      * diablo               — bool (optional)
    """
    rows = list(models)
    if not rows:
        return {
            "asset_id": asset_id,
            "model_count": 0,
            "mu": 0.0, "sigma2": 0.0, "D": 0.0,
            "contradiction_pair_count": 0,
            "contradiction_score": 0.0,
            "any_DIABLO": False,
            "model_disagreement_risk": 0.0,
            "state": "PASS_THROUGH",
            "may_promote": True,
            "downgrade_reasons": [],
            "cqs_base": cqs_base, "cqs_adjusted": round(cqs_base, 6),
        }
    # Stance * confidence per model.
    s_values: list[float] = []
    weights: list[float] = []
    any_diablo = False
    for r in rows:
        s_m = stance_numeric(r.get("stance", "")) * float(
            r.get("confidence") or 0.0
        )
        s_values.append(s_m)
        weights.append(max(0.0, float(r.get("reliability") or 0.0)))
        if str(r.get("stance", "")).upper() == "DIABLO" or bool(r.get("diablo")):
            any_diablo = True
    weight_sum = max(sum(weights), EPS)
    mu = sum(w * s for w, s in zip(weights, s_values)) / weight_sum
    var = sum(w * (s - mu) ** 2 for w, s in zip(weights, s_values)) / weight_sum
    D = _clamp01(math.sqrt(max(0.0, var)))

    # Contradiction pairs.
    M = len(rows)
    pair_total = max(1, M * (M - 1) // 2)
    contradictions = 0
    for i in range(M):
        for j in range(i + 1, M):
            si, sj = s_values[i], s_values[j]
            same_sign = (si == 0 and sj == 0) or (
                (si > 0 and sj > 0) or (si < 0 and sj < 0)
            )
            if not same_sign and abs(si - sj) >= CONTRADICTION_MAGNITUDE:
                contradictions += 1
    contradiction_score = _clamp01(contradictions / pair_total)

    risk = _clamp01(
        0.60 * D + 0.25 * contradiction_score + 0.15 * (1.0 if any_diablo else 0.0)
    )

    downgrade: list[str] = []
    if any_diablo:
        state = "DIABLO_REVIEW"
        may_promote = False
        downgrade.append("DIABLO_MODEL_VETO")
    elif risk >= 0.65:
        state = "RESEARCH_CANDIDATE"
        may_promote = False
        downgrade.append("MODEL_DISAGREEMENT_HIGH")
    elif risk >= 0.40:
        state = "WATCHLIST_UNCERTAIN"
        may_promote = False
        downgrade.append("MODEL_DISAGREEMENT_MODERATE")
    else:
        state = "PASS_THROUGH"
        may_promote = True

    cqs_adjusted = round(_clamp01(cqs_base) * max(0.0, 1.0 - 0.30 * risk), 6)

    return {
        "asset_id": asset_id,
        "model_count": M,
        "mu": round(mu, 6),
        "sigma2": round(var, 6),
        "D": round(D, 6),
        "contradiction_pair_count": contradictions,
        "contradiction_score": round(contradiction_score, 6),
        "any_DIABLO": any_diablo,
        "model_disagreement_risk": round(risk, 6),
        "state": state,
        "may_promote": may_promote,
        "downgrade_reasons": downgrade,
        "cqs_base": round(cqs_base, 6),
        "cqs_adjusted": cqs_adjusted,
    }


def _model_disagreement_handling_score(assets: list[dict[str, Any]]) -> float:
    weighted_variance_works = all(
        a["sigma2"] >= 0.0 and a["model_count"] > 0 for a in assets
    )
    contradiction_pairs_work = any(
        a["contradiction_pair_count"] > 0 for a in assets
    )
    diablo_blocks = all(
        not a["may_promote"] for a in assets if a["any_DIABLO"]
    ) and any(a["any_DIABLO"] for a in assets)
    high_routes_research = any(
        a["state"] == "RESEARCH_CANDIDATE" for a in assets
    )
    cqs_visible = all(
        a["cqs_base"] >= a["cqs_adjusted"] for a in assets
    ) and any(a["cqs_base"] > a["cqs_adjusted"] for a in assets)

    raw = (
        0.30 * (1.0 if weighted_variance_works else 0.0)
        + 0.25 * (1.0 if contradiction_pairs_work else 0.0)
        + 0.20 * (1.0 if diablo_blocks else 0.0)
        + 0.15 * (1.0 if high_routes_research else 0.0)
        + 0.10 * (1.0 if cqs_visible else 0.0)
    )
    return round(10.0 * _clamp01(raw), 4)


def _fixture_assets() -> list[dict[str, Any]]:
    return [
        {
            "id": "AGREE_BULL",
            "models": [
                {"model_name": "grok", "stance": "BULLISH",
                 "confidence": 0.85, "reliability": 0.8},
                {"model_name": "claude", "stance": "BULLISH",
                 "confidence": 0.80, "reliability": 0.85},
                {"model_name": "codex", "stance": "BULLISH",
                 "confidence": 0.75, "reliability": 0.75},
                {"model_name": "gemini", "stance": "BULLISH",
                 "confidence": 0.70, "reliability": 0.7},
                {"model_name": "mistral", "stance": "NEUTRAL",
                 "confidence": 0.50, "reliability": 0.7},
            ],
            "cqs_base": 0.78,
        },
        {
            "id": "HIGH_DISAGREE",
            "models": [
                {"model_name": "grok", "stance": "BULLISH",
                 "confidence": 1.0, "reliability": 0.8},
                {"model_name": "claude", "stance": "BEARISH",
                 "confidence": 1.0, "reliability": 0.85},
                {"model_name": "codex", "stance": "BULLISH",
                 "confidence": 1.0, "reliability": 0.8},
                {"model_name": "gemini", "stance": "BEARISH",
                 "confidence": 1.0, "reliability": 0.8},
                {"model_name": "mistral", "stance": "BEARISH",
                 "confidence": 1.0, "reliability": 0.75},
            ],
            "cqs_base": 0.74,
        },
        {
            "id": "DIABLO_OVERRIDE",
            "models": [
                {"model_name": "grok", "stance": "BULLISH",
                 "confidence": 0.85, "reliability": 0.8},
                {"model_name": "claude", "stance": "DIABLO",
                 "confidence": 0.95, "reliability": 0.95},
                {"model_name": "codex", "stance": "BULLISH",
                 "confidence": 0.80, "reliability": 0.7},
                {"model_name": "gemini", "stance": "NEUTRAL",
                 "confidence": 0.50, "reliability": 0.7},
                {"model_name": "mistral", "stance": "BULLISH",
                 "confidence": 0.60, "reliability": 0.7},
            ],
            "cqs_base": 0.82,
        },
        {
            "id": "MODERATE",
            "models": [
                {"model_name": "grok", "stance": "BULLISH",
                 "confidence": 0.60, "reliability": 0.8},
                {"model_name": "claude", "stance": "NEUTRAL",
                 "confidence": 0.55, "reliability": 0.8},
                {"model_name": "codex", "stance": "BULLISH",
                 "confidence": 0.55, "reliability": 0.75},
                {"model_name": "gemini", "stance": "AVOID",
                 "confidence": 0.50, "reliability": 0.75},
                {"model_name": "mistral", "stance": "NEUTRAL",
                 "confidence": 0.45, "reliability": 0.7},
            ],
            "cqs_base": 0.66,
        },
    ]


def build_summary(
    assets: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if assets is None:
        assets = _fixture_assets()
    evaluated = []
    for a in assets:
        evaluated.append(
            evaluate_asset(a["id"], a["models"],
                           cqs_base=float(a.get("cqs_base") or 0.7))
        )
    seg = _model_disagreement_handling_score(evaluated)
    return {
        "report": "model_disagreement_summary",
        "ok": seg >= 9.5,
        "generated_at_utc": _utc_iso(),
        "asset_count": len(evaluated),
        "diablo_veto_count": sum(1 for a in evaluated if a["any_DIABLO"]),
        "high_disagreement_count": sum(
            1 for a in evaluated if a["state"] == "RESEARCH_CANDIDATE"
        ),
        "moderate_disagreement_count": sum(
            1 for a in evaluated if a["state"] == "WATCHLIST_UNCERTAIN"
        ),
        "assets": evaluated,
        "model_disagreement_score": seg,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None,
                  assets: Iterable[dict[str, Any]] | None = None,
                  ) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary(assets)
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
    p = argparse.ArgumentParser(prog="model_disagreement_handling.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"model_disagreement_score = {summary['model_disagreement_score']}")
        for a in summary["assets"]:
            print(f"  {a['asset_id']:18s} risk={a['model_disagreement_risk']:.3f} "
                  f"state={a['state']:22s} cqs={a['cqs_base']:.3f}->"
                  f"{a['cqs_adjusted']:.3f}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "STANCE_NUMERIC", "CONTRADICTION_MAGNITUDE",
    "stance_numeric", "evaluate_asset",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
