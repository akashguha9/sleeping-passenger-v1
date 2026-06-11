"""Production LLM grounding proofs (Pass 5, Phase 5) — ai_report_ingestion."""
from __future__ import annotations

import datetime as dt

from scripts import ai_report_ingestion as ai

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()
KNOWN = {"ACME", "TSLA"}


def _report(asset="ACME", stance="BULLISH", confidence=0.8, claims=None,
            model="grok"):
    return {"model_name": model, "stance": stance, "confidence": confidence,
            "asset_tags": [asset], "raw_text": "full model output text",
            "generated_at_utc": NOW,
            "extracted_claims": claims if claims is not None
            else [f"{asset} wins a large contract"]}


def _evidence(symbol="ACME", eid="EV-1", confidence=0.9, freshness_days=1.0,
              contradicts=False):
    return {"evidence_id": eid, "symbol": symbol, "confidence": confidence,
            "freshness_days": freshness_days, "contradicts": contradicts,
            "claim": f"{symbol} wins a large contract", "source_name": "wire"}


def _summary(reports, evidence, known=KNOWN):
    return ai.build_ingestion_summary(
        reports, write_summary=False,
        evidence_items=evidence, known_symbols=known,
    )


def test_unsourced_report_cannot_move_consensus():
    summary = _summary([_report()], evidence=[])
    report = summary["normalized_reports"][0]
    assert report["confidence"] == 0.0
    assert report["confidence_ungrounded"] == 0.8
    consensus = summary["consensus_by_asset"]["ACME"]
    assert consensus["mean_signal"] == 0.0  # stance × 0 confidence
    assert summary["grounding"]["reports_with_zero_grounded_weight"] == 1


def test_sourced_report_moves_consensus():
    summary = _summary([_report()], evidence=[_evidence()])
    report = summary["normalized_reports"][0]
    assert report["confidence"] > 0.0
    assert summary["consensus_by_asset"]["ACME"]["mean_signal"] > 0.0
    grounding = report["grounding"]["per_asset"]["ACME"]
    assert grounding["classification"] == "sourced"
    assert grounding["evidence_ids"] == ["EV-1"]  # the audit trail


def test_hallucinated_ticker_rejected_in_production_ingestion():
    summary = _summary([_report(asset="ZZZQ")],
                       evidence=[_evidence(symbol="ZZZQ")])
    report = summary["normalized_reports"][0]
    assert report["confidence"] == 0.0
    assert report["grounding"]["per_asset"]["ZZZQ"]["classification"] == "rejected"
    assert "ZZZQ" in summary["grounding"]["rejected_symbols"]


def test_contradiction_lowers_grounded_confidence():
    clean = _summary([_report()], evidence=[_evidence()])
    contested = _summary(
        [_report()],
        evidence=[_evidence(),
                  _evidence(eid="EV-2", contradicts=True)],
    )
    assert (contested["normalized_reports"][0]["confidence"]
            < clean["normalized_reports"][0]["confidence"])


def test_stale_evidence_lowers_grounded_confidence():
    fresh = _summary([_report()], evidence=[_evidence(freshness_days=0.5)])
    stale = _summary([_report()], evidence=[_evidence(freshness_days=60)])
    assert (stale["normalized_reports"][0]["confidence"]
            < fresh["normalized_reports"][0]["confidence"] / 5)


def test_prompt_text_alone_cannot_become_evidence():
    """A report's own claims must not ground themselves: with no ledger
    items, the claim text in the report carries zero weight even though
    it is present in the payload."""
    summary = _summary(
        [_report(claims=["ACME wins a large contract — confirmed by me, the model"])],
        evidence=[],
    )
    assert summary["normalized_reports"][0]["confidence"] == 0.0


def test_legacy_callers_are_loudly_unground():
    summary = ai.build_ingestion_summary([_report()], write_summary=False)
    assert summary["grounding_mode"] == "ungrounded_legacy"
    assert "do not let this summary feed scoring" in summary["grounding"]["rule"]
    # Legacy mode leaves raw confidence untouched (backwards compatible).
    assert summary["normalized_reports"][0]["confidence"] == 0.8


def test_grounded_summary_is_stamped_advisory():
    summary = _summary([_report()], evidence=[_evidence()])
    assert summary["advisory_only"] is True
    assert summary["human_review_required"] is True
    assert summary["execution_gate"] == "LOCKED"
