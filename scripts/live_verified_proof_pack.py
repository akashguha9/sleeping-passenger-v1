"""LIVE_VERIFIED proof pack — operator/investor-readable verification evidence.

KANTE_LIVE_VERIFIED_PROOF_PACK
==============================

Kanté Ceiling Push II, Workstream E.  The strict LIVE_VERIFIED gate already
lives in :mod:`scripts.source_health_maturity`.  This module *packages* that
verdict into a single proof pack an operator or investor can read: the per-
field evidence, a weighted ``live_verification_readiness_score``, and a coarse
label — without ever changing the safety posture.

Hard safety contract
--------------------
* Pure — wraps :func:`verify_live_source_readiness`; no I/O of its own.
* LIVE_VERIFIED is a *data-quality* verdict, NOT execution readiness.  The
  pack always carries ``execution_gate = LOCKED``, ``broker_api_called =
  False``, ``ai_execution_count = 0`` and ``real_money_sizing_impact =
  PROHIBITED``.  A mock / stub / stale / unstamped source can never be
  LIVE_VERIFIED.
* No execution-instruction wording is ever emitted.

Score (per the sprint spec)
---------------------------
    live_verification_readiness_score =
      clip(
          0.20 * configured_enabled_score
        + 0.20 * non_mock_score
        + 0.20 * freshness_score
        + 0.15 * canonical_write_score
        + 0.15 * safety_stamp_score
        + 0.10 * secret_redaction_score,
        0, 1)

    safety_stamp_score = 1 only if LOCKED / false / 0 / PROHIBITED all hold.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import source_health_maturity as _shm
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    import source_health_maturity as _shm  # type: ignore[no-redef]

LABEL_NOT_CONFIGURED = "NOT_CONFIGURED"
LABEL_MOCK_ONLY = "MOCK_ONLY"
LABEL_STALE = "STALE"
LABEL_DEGRADED = "DEGRADED"
LABEL_READY_TO_VERIFY = "READY_TO_VERIFY"
LABEL_LIVE_VERIFIED = "LIVE_VERIFIED"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"
_PROOF = "LIVE_VERIFIED_PROOF_PACK_PAPER_ONLY"


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _freshness_score(age: float | None, ttl: float | None, blockers: list[str]) -> float:
    if "stale_or_unknown_freshness" in blockers:
        return 0.0
    if "missing_last_fresh_signal_at_utc" in blockers:
        return 0.0
    if age is None or ttl is None or ttl <= 0:
        return 0.0
    return _clip(1.0 - (age / ttl), 0.0, 1.0)


def _proof_label(
    *,
    verdict: dict[str, Any],
    score: float,
) -> str:
    if verdict.get("live_verified") is True:
        return LABEL_LIVE_VERIFIED
    blockers = list(verdict.get("live_verified_blockers") or [])
    if "not_configured" in blockers:
        return LABEL_NOT_CONFIGURED
    if "mock_mode" in blockers:
        return LABEL_MOCK_ONLY
    if (
        "stale_or_unknown_freshness" in blockers
        or "missing_last_fresh_signal_at_utc" in blockers
    ):
        return LABEL_STALE
    # Everything structural passed but a residual blocker (e.g. secret
    # redaction) remains → close, but honestly not yet verified.
    if score >= 0.85:
        return LABEL_READY_TO_VERIFY
    return LABEL_DEGRADED


def build_live_verified_proof_pack(source_result: dict[str, Any]) -> dict[str, Any]:
    """Build a single-source LIVE_VERIFIED proof pack (pure).  Never raises."""
    verdict = _shm.verify_live_source_readiness(source_result or {})
    blockers = list(verdict.get("live_verified_blockers") or [])

    configured = bool(verdict.get("configured"))
    enabled = bool(verdict.get("enabled"))
    mock_mode = bool(verdict.get("mock_mode"))
    canonical_written = int(verdict.get("canonical_rows_written") or 0)
    age = verdict.get("freshness_age_hours")
    ttl = verdict.get("freshness_ttl_hours")
    secrets_redacted = bool(verdict.get("secrets_redacted"))

    # --- component scores
    configured_enabled_score = 1.0 if (configured and enabled) else 0.0
    non_mock_score = 0.0 if mock_mode else 1.0
    freshness_score = _freshness_score(age, ttl, blockers)
    canonical_write_score = 1.0 if canonical_written > 0 else 0.0
    safety_stamp_score = (
        1.0
        if (
            str(verdict.get("execution_gate")) == "LOCKED"
            and verdict.get("broker_api_called") is False
            and verdict.get("ai_execution_count") == 0
            and verdict.get("real_money_sizing_impact") == REAL_MONEY_SIZING_IMPACT
        )
        else 0.0
    )
    secret_redaction_score = 1.0 if secrets_redacted else 0.0

    live_verification_readiness_score = _clip(
        0.20 * configured_enabled_score
        + 0.20 * non_mock_score
        + 0.20 * freshness_score
        + 0.15 * canonical_write_score
        + 0.15 * safety_stamp_score
        + 0.10 * secret_redaction_score,
        0.0,
        1.0,
    )

    label = _proof_label(verdict=verdict, score=live_verification_readiness_score)

    out: dict[str, Any] = {
        "report": "live_verified_proof_pack",
        "source_name": verdict.get("source_name", "unknown"),
        "live_verified": bool(verdict.get("live_verified")),
        "proof_label": label,
        "blockers": blockers,
        "configured": configured,
        "enabled": enabled,
        "mock_mode": mock_mode,
        "rows_seen": int(verdict.get("rows_seen") or 0),
        "rows_accepted": int(verdict.get("rows_accepted") or 0),
        "canonical_rows_written": canonical_written,
        "freshness_age_hours": age,
        "freshness_ttl_hours": ttl,
        "secrets_redacted": secrets_redacted,
        "no_execution_language": bool(verdict.get("no_execution_language")),
        "decision_impact": verdict.get("decision_impact"),
        # --- component scores
        "configured_enabled_score": round(configured_enabled_score, 6),
        "non_mock_score": round(non_mock_score, 6),
        "freshness_score": round(freshness_score, 6),
        "canonical_write_score": round(canonical_write_score, 6),
        "safety_stamp_score": round(safety_stamp_score, 6),
        "secret_redaction_score": round(secret_redaction_score, 6),
        "live_verification_readiness_score": round(
            live_verification_readiness_score, 6
        ),
        # --- hard invariants
        "live_verified_is_execution_readiness": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["operator_execution_required"] = True
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    out["proof_status"] = _PROOF
    return out


def build_proof_pack_summary(
    source_results: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Aggregate proof packs across multiple sources (pure)."""
    packs = [build_live_verified_proof_pack(s) for s in (source_results or [])]
    live_verified = [p for p in packs if p["live_verified"]]
    out: dict[str, Any] = {
        "report": "live_verified_proof_pack_summary",
        "source_count": len(packs),
        "live_verified_count": len(live_verified),
        "packs": packs,
        "live_verified_is_execution_readiness": False,
        "real_money_sizing_impact": REAL_MONEY_SIZING_IMPACT,
        "real_money_weight_allowed": False,
        "proof_status": _PROOF,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="live_verified_proof_pack.py",
        description=(
            "Package the strict LIVE_VERIFIED gate into operator/investor-"
            "readable proof. LIVE_VERIFIED is a data-quality verdict, never "
            "execution readiness; real-money sizing PROHIBITED."
        ),
    )
    p.add_argument(
        "--source-json",
        default=None,
        help="JSON source-result object to verify (default = empty/unconfigured)",
    )
    p.add_argument("--json", action="store_true", help="print the JSON report")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    source: dict[str, Any] = {}
    if args.source_json:
        try:
            source = json.loads(args.source_json)
        except json.JSONDecodeError:
            print("[ERROR] --source-json is not valid JSON")
            return 1
    pack = build_live_verified_proof_pack(source)
    if args.json:
        print(json.dumps(pack, indent=2))
    else:
        print("live_verified_proof_pack")
        print(f"  source          : {pack['source_name']}")
        print(f"  proof_label     : {pack['proof_label']}")
        print(f"  live_verified   : {pack['live_verified']}")
        print(f"  readiness score : {pack['live_verification_readiness_score']}")
        if pack["blockers"]:
            print(f"  blockers        : {', '.join(pack['blockers'])}")
        print(f"  real-money      : {pack['real_money_sizing_impact']}")
    return 0


__all__ = [
    "LABEL_NOT_CONFIGURED",
    "LABEL_MOCK_ONLY",
    "LABEL_STALE",
    "LABEL_DEGRADED",
    "LABEL_READY_TO_VERIFY",
    "LABEL_LIVE_VERIFIED",
    "build_live_verified_proof_pack",
    "build_proof_pack_summary",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
