"""Canonical normalizer for multi-model AI report snippets — advisory-only, pure.

Grok / Claude / Codex / Gemini / Mistral / DeepSeek all emit free-form
"here is my read on TICKER" snippets in slightly different shapes.  This module
collapses any of them into ONE canonical advisory row::

    {
      run_date, model_name, ticker, direction_bias, confidence, catalysts,
      source_refs, invalidation, risk_flags, thesis, advisory_status,
      human_review_required, ai_execution_count
    }

Hard rules (Kanté "no uncontrolled model echo")
-----------------------------------------------
* ``direction_bias`` is a *bias* — ``net_long_bias`` / ``net_short_bias`` /
  ``no_clear_bias`` — **never** BUY / SELL / EXECUTE.  No normalized output can
  become an execution instruction.
* Missing catalysts lowers cross-model **source independence**.
* A catalyst repeated across models produces **echo risk** (five models echoing
  one public catalyst is not five independent confirmations).
* A report missing its ``invalidation`` is **promotion-blocked** — degrades to
  ``REVIEW``.
* Bad parse / no usable content degrades to ``INSUFFICIENT_DATA``.

Pure module: no DB, no network, no broker calls.  Secret-looking tokens in any
free text are redacted via :mod:`scripts.ai_output_schema`.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts.ai_output_schema import redact_secret_patterns, normalize_confidence_score
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from ai_output_schema import (  # type: ignore[no-redef]
        redact_secret_patterns,
        normalize_confidence_score,
    )

try:
    from scripts.complex_systems_diagnostics import compute_source_independence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from complex_systems_diagnostics import compute_source_independence  # type: ignore[no-redef]

# Advisory statuses (a strict subset of the contract's safe-degradation states).
REVIEW = "REVIEW"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

DIRECTION_LONG = "net_long_bias"
DIRECTION_SHORT = "net_short_bias"
DIRECTION_NONE = "no_clear_bias"


def _str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return redact_secret_patterns(str(value).strip())


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    elif isinstance(value, str):
        # split on common delimiters so "a; b, c" becomes three catalysts
        raw = value.replace(";", ",").replace("\n", ",")
        items = raw.split(",")
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        text = _str(item)
        if text:
            out.append(text)
    return out


def _direction_bias(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"up", "bull", "bullish", "long", "+", "1", "net_long_bias",
                "positive", "overweight"}:
        return DIRECTION_LONG
    if text in {"down", "bear", "bearish", "short", "-", "-1", "net_short_bias",
                "negative", "underweight"}:
        return DIRECTION_SHORT
    return DIRECTION_NONE


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def normalize_model_report(raw: Any, *, run_date: str | None = None) -> dict[str, Any]:
    """Normalize one model report snippet into the canonical advisory row.

    Never raises; bad input degrades to ``INSUFFICIENT_DATA``.
    """
    base_stamps = {
        "advisory_status": REVIEW,
        "human_review_required": True,
        "ai_execution_count": _contract.AI_EXECUTION_COUNT,
        "execution_gate": _contract.EXECUTION_GATE_LOCKED,
        "execution_permission": False,
        "can_execute": False,
        "broker_api_called": False,
    }

    if not isinstance(raw, dict):
        return {
            "run_date": _str(run_date),
            "model_name": None,
            "ticker": None,
            "direction_bias": DIRECTION_NONE,
            "confidence": None,
            "catalysts": [],
            "source_refs": [],
            "invalidation": None,
            "risk_flags": ["bad_parse"],
            "thesis": None,
            **base_stamps,
            "advisory_status": INSUFFICIENT_DATA,
            "promotion_blocked": True,
        }

    model_name = _str(_first(raw, "model_name", "model", "source_name")) or None
    ticker_raw = _first(raw, "ticker", "symbol")
    ticker = _str(ticker_raw).upper() or None
    catalysts = _str_list(_first(raw, "catalysts", "catalyst", "drivers"))
    source_refs = _str_list(
        _first(raw, "source_refs", "citations", "citation", "sources", "source_url")
    )
    invalidation = _str(_first(raw, "invalidation", "invalidation_level",
                               "invalidation_condition")) or None
    thesis = _str(_first(raw, "thesis", "summary", "narrative")) or None
    confidence, _conf_warn = normalize_confidence_score(
        _first(raw, "confidence", "conviction", "confidence_score")
    )
    direction_bias = _direction_bias(_first(raw, "direction_bias", "direction", "bias"))

    risk_flags: list[str] = []
    extra_flags = _str_list(_first(raw, "risk_flags"))
    risk_flags.extend(extra_flags)

    if not catalysts:
        risk_flags.append("missing_catalysts")
    if invalidation is None:
        risk_flags.append("missing_invalidation")

    # Status / promotion logic.
    has_content = bool(thesis or ticker or catalysts)
    promotion_blocked = invalidation is None
    if not has_content:
        advisory_status = INSUFFICIENT_DATA
        promotion_blocked = True
    elif not catalysts:
        # No catalyst evidence — cannot assess independence; degrade.
        advisory_status = INSUFFICIENT_DATA
        promotion_blocked = True
    else:
        advisory_status = REVIEW  # the strongest state — still human-reviewed

    out = {
        "run_date": _str(run_date) or _str(_first(raw, "run_date")),
        "model_name": model_name,
        "ticker": ticker,
        "direction_bias": direction_bias,
        "confidence": confidence,
        "catalysts": catalysts,
        "source_refs": source_refs,
        "invalidation": invalidation,
        "risk_flags": sorted(set(risk_flags)),
        "thesis": thesis,
        **base_stamps,
        "advisory_status": advisory_status,
        "promotion_blocked": bool(promotion_blocked),
    }
    return out


def _independence_cluster(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the cluster compute_source_independence expects from normalized rows."""
    cluster: list[dict[str, Any]] = []
    for r in reports:
        cats = r.get("catalysts") or []
        # A representative catalyst key: the joined, sorted catalyst text so
        # two models citing the same catalyst collapse to one.
        catalyst_blob = " | ".join(sorted(str(c).lower() for c in cats))
        cluster.append({
            "model": r.get("model_name") or "",
            "catalyst": catalyst_blob,
            "citation": r.get("source_refs") or [],
        })
    return cluster


def normalize_model_reports(
    raw_reports: Any, *, run_date: str | None = None
) -> dict[str, Any]:
    """Normalize a batch of model reports and assess cross-model echo risk.

    Returns the per-model normalized rows plus a ``consensus`` block carrying
    ``independence_score`` / ``echo_chamber_risk`` / ``repeated_catalyst_count``.
    """
    rows = raw_reports if isinstance(raw_reports, list) else [raw_reports]
    normalized = [normalize_model_report(r, run_date=run_date) for r in rows]

    cluster = _independence_cluster(
        [r for r in normalized if r["advisory_status"] != INSUFFICIENT_DATA]
    )
    independence = compute_source_independence(cluster) if cluster else None

    promotable = [
        r for r in normalized
        if not r["promotion_blocked"] and r["advisory_status"] == REVIEW
    ]

    consensus: dict[str, Any] = {
        "model_count": len(normalized),
        "promotable_count": len(promotable),
        "independence_score": (
            independence["independence_score"] if independence else 0.0
        ),
        "echo_chamber_risk": (
            independence["echo_chamber_risk"] if independence else 1.0
        ),
        "unique_catalyst_count": (
            independence["unique_catalyst_count"] if independence else 0
        ),
        "repeated_catalyst_count": (
            independence["repeated_catalyst_count"] if independence else 0
        ),
        "note": (
            independence["source_overlap_note"] if independence
            else "insufficient_data: no usable catalysts across models."
        ),
    }

    return {
        "run_date": _str(run_date),
        "reports": normalized,
        "consensus": consensus,
        # Semantic batch status (REVIEW / INSUFFICIENT_DATA) — never an order.
        "advisory_status": REVIEW if promotable else INSUFFICIENT_DATA,
        "human_review_required": True,
        # Execution-lock fields (no advisory_status key, so the semantic
        # status above is preserved).
        **_contract.execution_lock_stamp(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="model_signal_normalizer.py",
        description=(
            "Normalize multi-model AI report snippets into one advisory schema. "
            "Never emits BUY/SELL/EXECUTE; reads a JSON list from a file."
        ),
    )
    p.add_argument("--input", type=str, required=True,
                   help="Path to a JSON file containing a list of report dicts.")
    p.add_argument("--run-date", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    import pathlib

    args = _build_parser().parse_args(argv)
    raw = json.loads(pathlib.Path(args.input).read_text(encoding="utf-8-sig"))
    report = normalize_model_reports(raw, run_date=args.run_date)
    print(json.dumps(report, indent=2, default=str))
    return 0


__all__ = [
    "REVIEW",
    "INSUFFICIENT_DATA",
    "DIRECTION_LONG",
    "DIRECTION_SHORT",
    "DIRECTION_NONE",
    "normalize_model_report",
    "normalize_model_reports",
]


if __name__ == "__main__":
    raise SystemExit(main())
