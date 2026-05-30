"""CI / scope / safety invariants after the Kanté score-ceiling sprint (WS F/G)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import private_scope_guard as guard
from scripts import advisory_contract as contract
from scripts import external_advisory_evidence as eae
from scripts import fake_confidence_audit as fca
from scripts import veto_integrity_proof as vip
from scripts import source_health_maturity as shm
from scripts import external_evidence_operator_readiness as eor

_REPO_ROOT = Path(__file__).resolve().parents[1]

# New modules introduced by this sprint.
_NEW_MODULES = (
    "fake_confidence_audit.py",
    "veto_integrity_proof.py",
    "source_health_maturity.py",
    "external_evidence_operator_readiness.py",
)

_CARD = _REPO_ROOT / "frontend" / "src" / "components" / "ExternalEvidenceReliabilityCard.tsx"


# --- 23 ---------------------------------------------------------------------
def test_private_scope_guard_after_kante_sprint() -> None:
    report = guard.build_report()
    assert report["review_required"] == [], (
        f"new out-of-scope modules detected: {report['review_required']!r}"
    )
    for name in _NEW_MODULES:
        assert guard._classify(name) == "in_scope", f"{name} must be in scope"


# --- 24 ---------------------------------------------------------------------
def test_advisory_contract_after_kante_sprint() -> None:
    stamps = contract.advisory_safety_stamps()
    # Each new module's primary output must carry the canonical stamp values.
    outputs = [
        fca.build_fake_confidence_summary([]),
        vip.build_veto_integrity_proof({"base_score": 5.0, "veto_type": "DIABLO"}),
        shm.build_source_health_maturity_summary([]),
        eor.build_external_evidence_operator_readiness(
            {"external_evidence_status": "DISABLED", "external_evidence_enabled": False}
        ),
    ]
    for out in outputs:
        assert out["advisory_status"] == stamps["advisory_status"]
        assert out["execution_gate"] == "LOCKED"
        assert out["broker_api_called"] is False
        assert out["ai_execution_count"] == 0


# --- 25 ---------------------------------------------------------------------
def test_frontend_no_execution_language_after_kante_sprint() -> None:
    forbidden = [
        r"\bplace\s+order\b",
        r"\bexecute\s+trade\b",
        r"\btrade\s+now\b",
        r"\bauto[-\s]?trade\b",
        r"\bbroker\s+order\b",
        r"\bpermission\s+to\s+trade\b",
    ]
    text = _CARD.read_text(encoding="utf-8")
    for pat in forbidden:
        assert not re.search(pat, text, re.IGNORECASE), (
            f"forbidden execution phrase {pat!r} in reliability card"
        )
    # Positive safety posture present.
    assert "Real-money sizing prohibited" in text


# --- 26 ---------------------------------------------------------------------
def test_no_mock_live_claims() -> None:
    for kind in ("is_mock", "is_stub"):
        out = shm.compute_source_health_score(
            {
                "source_name": "x", "configured": True, "enabled": True,
                kind: True, "freshness_age_hours": 0.5, "freshness_ttl_hours": 24,
                "rows_seen": 100, "rows_accepted": 100, "canonical_rows_written": 100,
            }
        )
        assert out["maturity_label"] != shm.LIVE_VERIFIED
        assert out["maturity_label"] in {shm.MOCK_ONLY, shm.STUB_SAFE}


# --- 27 ---------------------------------------------------------------------
def test_no_broker_imports_in_new_modules() -> None:
    broker_tokens = (
        "import alpaca",
        "from alpaca",
        "import ib_insync",
        "ccxt",
        "place_order(",
        "submit_order(",
        "broker_execute",
        "create_order(",
    )
    for name in _NEW_MODULES:
        src = (_REPO_ROOT / "scripts" / name).read_text(encoding="utf-8").lower()
        for tok in broker_tokens:
            assert tok.lower() not in src, f"{name} contains broker token {tok!r}"


# --- 28 ---------------------------------------------------------------------
def test_full_external_evidence_loop_still_clamped() -> None:
    # Hard caps unchanged.
    assert eae.MAX_POSITIVE_SCORE_DELTA == 0.50
    assert eae.MAX_NEGATIVE_SCORE_DELTA == -1.00
    # Disabled default bundle contributes nothing.
    bundle = eae.build_external_evidence_bundle()
    delta = float(bundle.get("external_evidence_score_delta") or 0.0)
    assert eae.MAX_NEGATIVE_SCORE_DELTA <= delta <= eae.MAX_POSITIVE_SCORE_DELTA
    # Even a (tampered) over-cap delta keeps the final score inside [0, 10].
    over = {
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_score_delta": 0.9,  # above the +0.50 cap
        "external_evidence_decision_impact": "ADVISORY_CONTEXT_ONLY",
    }
    res = eae.apply_external_evidence_to_score(9.9, "WATCHLIST", over)
    assert 0.0 <= res["final_score"] <= 10.0


# --- 29 ---------------------------------------------------------------------
def test_external_only_positive_still_watchlist() -> None:
    bundle = {
        "external_evidence_status": "ACCEPTED_EVIDENCE_ONLY",
        "external_evidence_score_delta": 0.5,
        "external_evidence_decision_impact": "ADVISORY_CONTEXT_ONLY",
    }
    res = eae.apply_external_evidence_to_score(
        5.0, "RESEARCH_CANDIDATE", bundle, external_is_only_positive_evidence=True
    )
    assert res["final_signal_class"].upper() == "WATCHLIST"
    assert res["external_only_positive_capped"] is True


# --- 30 ---------------------------------------------------------------------
def test_real_money_sizing_still_prohibited_everywhere() -> None:
    outputs = [
        fca.compute_overconfidence(sample_count=10, advisory_weight=0.5),
        fca.build_fake_confidence_summary([]),
        vip.build_veto_integrity_proof({"base_score": 5.0}),
        shm.compute_source_health_score({"source_name": "x"}),
        shm.build_source_health_maturity_summary([]),
        eor.build_external_evidence_operator_readiness(
            {"external_evidence_status": "DISABLED", "external_evidence_enabled": False}
        ),
    ]
    for out in outputs:
        assert out.get("real_money_sizing_impact") == "PROHIBITED", out
