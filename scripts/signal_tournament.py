"""Signal tournament — compare advisory variants without trading (Pass 5).

Runs multiple scoring variants over the SAME temporally-valid sample
window and ranks them on the OUT-OF-SAMPLE period only. Observations go
to a shadow-paper ledger that is structurally incapable of describing an
order: rows carrying order/broker/execution-shaped keys are REFUSED, and
every row is stamped::

    NOT_AN_ORDER / ADVISORY_ONLY / HUMAN_REVIEW_REQUIRED

Built-in variants (callables score(features)->(score, act)):
  production (FCS weights), evidence_only, momentum_only, quality_only,
  equal_weight, abstention_heavy, contrarian, no_llm.

Ledger: ``runtime/shadow_paper_ledger.jsonl`` (gitignored;
``MVP_SHADOW_LEDGER_PATH`` override). Report:
``reports/signal_tournament_<timestamp>.md``.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import statistics
from pathlib import Path
from typing import Callable

try:
    from scripts.temporal_guard import filter_evaluation_samples, parse_utc
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from temporal_guard import filter_evaluation_samples, parse_utc  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[1]
ADVISORY_STAMPS = {
    "NOT_AN_ORDER": True,
    "ADVISORY_ONLY": True,
    "HUMAN_REVIEW_REQUIRED": True,
    "broker_api_called": False,
    "execution_gate": "LOCKED",
}
_FORBIDDEN_LEDGER_KEYS = (
    "order_id", "order", "broker", "broker_id", "execution_status",
    "fill_price", "filled", "order_type", "venue", "account_id",
    "position_size_live", "executed",
)
MIN_OOS_SAMPLES = 20


class LedgerContractError(ValueError):
    """Raised when a row smells like an order instead of an observation."""


def shadow_ledger_path() -> Path:
    raw = os.environ.get("MVP_SHADOW_LEDGER_PATH", "").strip()
    return Path(raw) if raw else _REPO_ROOT / "runtime" / "shadow_paper_ledger.jsonl"


def append_shadow_observation(row: dict, path: Path | None = None) -> dict:
    """Append one hypothetical observation. Refuses order-shaped rows."""
    for key in row:
        lk = str(key).lower()
        if any(f == lk or f in lk for f in _FORBIDDEN_LEDGER_KEYS):
            raise LedgerContractError(
                f"key {key!r} is order/broker/execution-shaped — the shadow "
                "ledger stores hypothetical observations, never orders"
            )
    record = {**row, **ADVISORY_STAMPS,
              "recorded_utc": _dt.datetime.now(_dt.timezone.utc).isoformat()}
    ledger = path or shadow_ledger_path()
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return record


# ---------------------------------------------------------------------------
# Variants — each maps a feature dict to (score, act: bool)
# ---------------------------------------------------------------------------


def _act(score: float, threshold: float = 0.6) -> bool:
    return score >= threshold


def variant_production(f: dict) -> tuple[float, bool]:
    try:
        from scripts.daily_scoring import FCS_WEIGHTS
    except ModuleNotFoundError:  # pragma: no cover
        from daily_scoring import FCS_WEIGHTS  # type: ignore[no-redef]
    score = sum(FCS_WEIGHTS.get(k, 0.0) * float(f.get(k, 0.0)) for k in FCS_WEIGHTS)
    return score, _act(score)


def variant_evidence_only(f: dict) -> tuple[float, bool]:
    score = float(f.get("data_quality", 0.0)) * 0.5 + float(f.get("freshness_score", 0.0)) * 0.5
    return score, _act(score)


def variant_llm_grounded(f: dict) -> tuple[float, bool]:
    base = float(f.get("mean_model_score", 0.0))
    grounding = float(f.get("grounded_weight", 0.0))
    score = base * grounding
    return score, _act(score)


def variant_no_llm(f: dict) -> tuple[float, bool]:
    keys = ("acqs", "why_today_score", "data_quality", "freshness_score")
    score = sum(float(f.get(k, 0.0)) for k in keys) / len(keys)
    return score, _act(score)


def variant_momentum_only(f: dict) -> tuple[float, bool]:
    score = float(f.get("price_momentum", f.get("acqs", 0.0)))
    return score, _act(score)


def variant_quality_only(f: dict) -> tuple[float, bool]:
    score = float(f.get("data_quality", 0.0))
    return score, _act(score)


def variant_equal_weight(f: dict) -> tuple[float, bool]:
    numeric = [float(v) for v in f.values() if isinstance(v, (int, float))]
    score = sum(numeric) / len(numeric) if numeric else 0.0
    return score, _act(score)


def variant_abstention_heavy(f: dict) -> tuple[float, bool]:
    score, _ = variant_production(f)
    return score, _act(score, threshold=0.75)


def variant_contrarian(f: dict) -> tuple[float, bool]:
    score, _ = variant_production(f)
    return 1.0 - score, _act(1.0 - score, threshold=0.7)


DEFAULT_VARIANTS: dict[str, Callable[[dict], tuple[float, bool]]] = {
    "production": variant_production,
    "evidence_only": variant_evidence_only,
    "llm_grounded": variant_llm_grounded,
    "no_llm": variant_no_llm,
    "momentum_only": variant_momentum_only,
    "quality_only": variant_quality_only,
    "equal_weight": variant_equal_weight,
    "abstention_heavy": variant_abstention_heavy,
    "contrarian": variant_contrarian,
}


def run_tournament(
    samples: list[dict],
    *,
    oos_start: str | _dt.datetime,
    variants: dict[str, Callable] | None = None,
    ledger_path: Path | None = None,
) -> dict:
    """Score every variant on the SAME guarded window; rank OOS only.

    ``samples``: {"signal_id", "symbol", "t_decision", "t_outcome",
    "features": {...}, "net_return": float, "benchmark_return": optional}.
    Every (variant, sample) observation is appended to the shadow ledger.
    Rankings come exclusively from samples with t_decision >= oos_start.
    """
    variants = variants or DEFAULT_VARIANTS
    boundary = parse_utc(oos_start, "oos_start")
    guard = filter_evaluation_samples(samples)
    usable = guard["usable"]

    per_variant: dict[str, dict] = {}
    for name, fn in variants.items():
        acted_oos, fp, fn_count, abstained_oos, in_sample_n = [], 0, 0, 0, 0
        for sample in usable:
            t_dec = parse_utc(sample["t_decision"], "t_decision")
            score, act = fn(sample.get("features", {}))
            is_oos = t_dec is not None and t_dec >= boundary
            append_shadow_observation({
                "variant": name,
                "signal_id": sample.get("signal_id", "?"),
                "symbol": sample.get("symbol", "?"),
                "t_decision": str(sample.get("t_decision")),
                "score": round(float(score), 6),
                "recommendation": "ACT_CANDIDATE" if act else "ABSTAIN",
                "oos": is_oos,
                "evidence_ids": list(sample.get("evidence_ids", []))[:10],
                "outcome_known": "net_return" in sample,
                "net_return_hypothetical": sample.get("net_return"),
            }, path=ledger_path)
            if not is_oos:
                in_sample_n += 1
                continue
            r = float(sample.get("net_return", 0.0))
            if act:
                acted_oos.append(r)
                if r <= 0:
                    fp += 1
            else:
                abstained_oos += 1
                if r > 0:
                    fn_count += 1
        n = len(acted_oos)
        per_variant[name] = {
            "oos_acted": n,
            "oos_abstained": abstained_oos,
            "in_sample_observations_excluded_from_ranking": in_sample_n,
            "hit_rate": (sum(1 for r in acted_oos if r > 0) / n) if n else None,
            "expectancy": statistics.fmean(acted_oos) if acted_oos else None,
            "false_positives": fp,
            "false_negatives": fn_count,
            "small_sample_warning": (n + abstained_oos) < MIN_OOS_SAMPLES,
        }

    ranked = sorted(
        (name for name, m in per_variant.items() if m["expectancy"] is not None),
        key=lambda name: per_variant[name]["expectancy"],
        reverse=True,
    )
    return {
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "samples_in": len(samples),
        "samples_rejected_by_temporal_guard": len(guard["rejected"]),
        "oos_start": str(oos_start),
        "variants": per_variant,
        "ranking_basis": "out_of_sample_only",
        "ranking": ranked,
        "note": ("Hypothetical advisory observations; nothing was or can be "
                 "executed. Rankings ignore the in-sample period entirely."),
        **ADVISORY_STAMPS,
    }


def write_report(result: dict, out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"signal_tournament_{stamp}.md"
    lines = [
        "# Signal tournament", "",
        f"Generated: {result['generated_utc']} · OOS start: {result['oos_start']}",
        "", "NOT_AN_ORDER · ADVISORY_ONLY · HUMAN_REVIEW_REQUIRED — "
        "hypothetical observations only; ranking is out-of-sample only.", "",
        f"Temporal-guard rejected: {result['samples_rejected_by_temporal_guard']}", "",
        "| Variant | OOS acted | Abstained | Hit rate | Expectancy | FP | FN | Small sample? |",
        "| ------- | --------: | --------: | -------: | ---------: | --: | --: | ------------- |",
    ]
    for name in result["ranking"] + [
        n for n in result["variants"] if n not in result["ranking"]
    ]:
        m = result["variants"][name]
        hit = f"{m['hit_rate']:.2f}" if m["hit_rate"] is not None else "—"
        exp = f"{m['expectancy']:+.4f}" if m["expectancy"] is not None else "—"
        lines.append(
            f"| {name} | {m['oos_acted']} | {m['oos_abstained']} | {hit} | {exp} "
            f"| {m['false_positives']} | {m['false_negatives']} | "
            f"{'⚠️ yes' if m['small_sample_warning'] else 'no'} |"
        )
    lines += ["", f"Ranking (OOS expectancy): {', '.join(result['ranking']) or '—'}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
