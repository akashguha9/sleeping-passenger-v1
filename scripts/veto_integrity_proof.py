"""DIABLO / chaos-veto integrity proof pack.

KANTE_VETO_INTEGRITY_PROOF
==========================

The tactical foul before disaster.  Kanté breaks up the counter-attack before
it reaches the box — here the "counter-attack" is any positive external-evidence
boost trying to slip past a safety veto.  This module produces a *proof* that
every positive signal remains strictly subordinate to a veto:

    if veto_present:  S_final = min(S_candidate, S_base)

A positive external-evidence delta that tries to raise the score under a veto is
recorded as an *attempted boost* and proven *blocked*: the final score is capped
at base and the veto class is preserved.  High fake-confidence evidence is also
neutralised before scoring (it can never add positive delta — see
:mod:`scripts.fake_confidence_audit`).

Veto vocabulary
---------------
    DIABLO        — hard narrative veto (scripts.diablo_narrative_veto)
    CHAOS_VETO    — chaos / regime instability veto
    NO_NEW_RISK   — operator-overload / capacity hold
    NONE          — no veto in effect

Hard safety contract
--------------------
Pure module.  No DB, no network, no broker calls.  The proof can only *cap* a
score; it never raises one, never sizes real money, never unlocks execution.
Every returned dict carries ``execution_gate = "LOCKED"``,
``human_review_required = True`` and ``real_money_sizing_impact = "PROHIBITED"``.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import fake_confidence_audit as _fca
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    import fake_confidence_audit as _fca  # type: ignore[no-redef]

VETO_DIABLO = "DIABLO"
VETO_CHAOS = "CHAOS_VETO"
VETO_NO_NEW_RISK = "NO_NEW_RISK"
VETO_NONE = "NONE"

# Classes that ARE a safety veto (recognised on the base/final class).
_VETO_CLASSES = {
    "DIABLO": VETO_DIABLO,
    "DIABLO_REVIEW": VETO_DIABLO,
    "CHAOS_VETO": VETO_CHAOS,
    "CHAOS": VETO_CHAOS,
    "NO_NEW_RISK": VETO_NO_NEW_RISK,
}

PROOF_BLOCKED = "VETO_BLOCKED_POSITIVE_BOOST"
PROOF_CAPPED = "VETO_CAPPED_NO_UPGRADE"
PROOF_CLEAR = "NO_VETO_IN_EFFECT"

REAL_MONEY_SIZING_IMPACT = "PROHIBITED"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return default if out != out else out  # NaN guard


def _clip(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _resolve_veto_type(payload: dict[str, Any]) -> str:
    """Determine the veto type from explicit fields or the base class."""
    explicit = str(payload.get("veto_type") or "").strip().upper()
    if explicit in (VETO_DIABLO, VETO_CHAOS, VETO_NO_NEW_RISK):
        return explicit
    base_class = str(payload.get("base_class") or payload.get("base_signal_class") or "")
    mapped = _VETO_CLASSES.get(base_class.strip().upper())
    if mapped:
        return mapped
    # Boolean flags (any true → DIABLO unless a more specific flag set).
    if payload.get("chaos_veto"):
        return VETO_CHAOS
    if payload.get("no_new_risk"):
        return VETO_NO_NEW_RISK
    if payload.get("diablo_veto") or payload.get("safety_veto") or payload.get("veto_present"):
        return VETO_DIABLO
    return VETO_NONE


def build_veto_integrity_proof(signal_or_payload: dict[str, Any]) -> dict[str, Any]:
    """Build the veto-integrity proof for one signal / advisory payload.

    Expected (all optional) input keys::

        base_score                  float  — S_base
        external_evidence_delta     float  — proposed external delta (+ = boost)
        veto_type / *_veto flags    str/bool
        base_class                  str    — the veto class (preserved on output)
        fake_confidence_label       str    — optional; HIGH neutralises a boost

    Proves ``S_final = min(S_candidate, S_base)`` under any veto and reports
    whether an attempted positive boost was blocked.
    """
    payload = dict(signal_or_payload or {})
    base_score = _clip(_f(payload.get("base_score"), 0.0), 0.0, 10.0)
    requested_delta = _f(payload.get("external_evidence_delta"), 0.0)

    veto_type = _resolve_veto_type(payload)
    veto_present = veto_type != VETO_NONE

    base_class = str(payload.get("base_class") or payload.get("base_signal_class") or veto_type)
    fc_label = str(payload.get("fake_confidence_label") or "").strip().upper()

    # Fake-confidence HIGH neutralises any positive delta *before* scoring.
    fake_confidence_blocked = fc_label == _fca.LABEL_HIGH and requested_delta > 0
    effective_delta = 0.0 if fake_confidence_blocked else requested_delta

    attempted_boost = requested_delta > 0

    candidate_before_veto = _clip(base_score + effective_delta, 0.0, 10.0)

    if veto_present:
        final_after_veto = min(candidate_before_veto, base_score)
        final_class = base_class  # the veto class is authoritative
    else:
        final_after_veto = candidate_before_veto
        final_class = str(payload.get("final_class") or base_class)

    score_capped = veto_present and final_after_veto <= base_score
    # A boost is "blocked" if the operator attempted to raise the score but the
    # final score did not exceed base (either the veto capped it, or
    # fake-confidence neutralised it).
    boost_blocked = attempted_boost and final_after_veto <= base_score
    class_preserved = (not veto_present) or (final_class == base_class)

    if veto_present and boost_blocked:
        proof_status = PROOF_BLOCKED
    elif veto_present:
        proof_status = PROOF_CAPPED
    else:
        proof_status = PROOF_CLEAR

    out: dict[str, Any] = {
        "report": "veto_integrity_proof",
        "veto_present": veto_present,
        "veto_type": veto_type,
        "base_score": round(base_score, 6),
        "external_evidence_delta_requested": round(requested_delta, 6),
        "external_evidence_delta_effective": round(effective_delta, 6),
        "candidate_score_before_veto": round(candidate_before_veto, 6),
        "final_score_after_veto": round(final_after_veto, 6),
        "score_capped": bool(score_capped),
        "class_preserved": bool(class_preserved),
        "base_class": base_class,
        "final_class": final_class,
        "external_evidence_attempted_boost": bool(attempted_boost),
        "boost_blocked": bool(boost_blocked),
        "fake_confidence_label": fc_label or None,
        "fake_confidence_boost_blocked": bool(fake_confidence_blocked),
        "human_review_required": True,
        "proof_status": proof_status,
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["real_money_sizing_impact"] = REAL_MONEY_SIZING_IMPACT
    out["real_money_weight_allowed"] = False
    return out


__all__ = [
    "VETO_DIABLO",
    "VETO_CHAOS",
    "VETO_NO_NEW_RISK",
    "VETO_NONE",
    "PROOF_BLOCKED",
    "PROOF_CAPPED",
    "PROOF_CLEAR",
    "REAL_MONEY_SIZING_IMPACT",
    "build_veto_integrity_proof",
]
