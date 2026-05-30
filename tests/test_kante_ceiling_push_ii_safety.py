"""Safety / scope / no-execution invariants after Kanté Ceiling Push II.

Locks the global non-negotiables for the WS-A..WS-F modules: every new output
is advisory-only / LOCKED / broker-free / AI-execution-free with real-money
sizing PROHIBITED, no new module imports a broker, the scope guard stays clean,
and the reliability card emits no execution language.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import private_scope_guard as guard
from scripts import advisory_contract as contract
from scripts import paper_outcome_intake as poi
from scripts import calibration_corpus_quality as ccq
from scripts import operator_readiness_checklist as orc
from scripts import live_verified_proof_pack as lvp
from scripts import runtime_artifact_hygiene as rah

_REPO_ROOT = Path(__file__).resolve().parents[1]

_NEW_MODULES = (
    "paper_outcome_intake.py",
    "calibration_corpus_quality.py",
    "operator_readiness_checklist.py",
    "live_verified_proof_pack.py",
    "runtime_artifact_hygiene.py",
)

_CARD = _REPO_ROOT / "frontend" / "src" / "components" / "ExternalEvidenceReliabilityCard.tsx"


def _primary_outputs():
    return [
        poi.build_intake_report([]),
        poi.validate_outcome({"trade_id": "T", "ticker": "X"}),
        ccq.build_corpus_quality(n_closed=0),
        orc.build_operator_checklist({}),
        lvp.build_live_verified_proof_pack({}),
        rah.evaluate_artifact({"execution_gate": "LOCKED"}, age_hours=1.0),
    ]


# --- 31 ---------------------------------------------------------------------
def test_private_scope_guard_after_ceiling_push_ii() -> None:
    report = guard.build_report()
    assert report["review_required"] == [], (
        f"new out-of-scope modules detected: {report['review_required']!r}"
    )
    for name in _NEW_MODULES:
        assert guard._classify(name) == "in_scope", f"{name} must be in scope"


# --- 32 ---------------------------------------------------------------------
def test_advisory_contract_after_ceiling_push_ii() -> None:
    stamps = contract.advisory_safety_stamps()
    for out in _primary_outputs():
        assert out["advisory_status"] == stamps["advisory_status"]
        assert out["execution_gate"] == "LOCKED"
        assert out["broker_api_called"] is False
        assert out["ai_execution_count"] == 0
        assert out["advisory_only"] is True
        assert out["human_execution_required"] is True


# --- 33 ---------------------------------------------------------------------
def test_frontend_no_execution_language_after_ceiling_push_ii() -> None:
    forbidden = [
        r"\bplace\s+order\b",
        r"\bexecute\s+trade\b",
        r"\btrade\s+now\b",
        r"\bauto[-\s]?trade\b",
        r"\bbroker\s+order\b",
        r"\benable\s+live\b",
        r"\breal\s+money\s+ready\b",
        r"\bpermission\s+to\s+trade\b",
    ]
    text = _CARD.read_text(encoding="utf-8")
    for pat in forbidden:
        assert not re.search(pat, text, re.IGNORECASE), (
            f"forbidden execution phrase {pat!r} in reliability card"
        )
    # Positive safety posture present.
    assert "Real-money sizing prohibited" in text
    assert "LOW BY DESIGN" in text
    assert "cold-start" in text


# --- 34 ---------------------------------------------------------------------
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


# --- 35 ---------------------------------------------------------------------
def test_no_real_money_sizing_enabled() -> None:
    for out in _primary_outputs():
        assert out.get("real_money_sizing_impact") == "PROHIBITED", out
        assert out.get("real_money_weight_allowed") is False, out
    # Even a STRONG_PAPER_ONLY corpus and a LIVE_VERIFIED source stay prohibited.
    strong = ccq.build_corpus_quality(
        n_closed=100, n_valid=100, n_linked=100, n_bucketed=100
    )
    assert strong["corpus_label"] == ccq.LABEL_STRONG_PAPER_ONLY
    assert strong["real_money_sizing_impact"] == "PROHIBITED"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
