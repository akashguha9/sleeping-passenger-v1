"""Signal-card annotation proofs (Pass 6, Phase 4) — inbox + surfacing."""
from __future__ import annotations

import datetime as dt

import pytest

from scripts import data_quality as dq
from scripts import derived_score_ledger as dsl
from scripts import signal_annotation as ann

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
BANNED = ("guaranteed", "sure profit", "must buy", "execute now",
          "place order", "automatic trade")


@pytest.fixture
def ledgers(tmp_path, monkeypatch):
    ev = tmp_path / "evidence.jsonl"
    sc = tmp_path / "scores.jsonl"
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(ev))
    monkeypatch.setenv("MVP_DERIVED_SCORE_LEDGER_PATH", str(sc))
    return ev, sc


def _seed_evidence(path, symbol="ACME", n=2):
    for i in range(n):
        dq.append_evidence(dq.build_evidence(
            source_type="api", source_name=f"src{i}",
            claim=f"{symbol} filing event number {i}",
            raw_evidence=f"raw-{i}".encode(), observed_at=NOW, symbol=symbol,
        ), path)


def _item(ticker="ACME", observed=NOW.isoformat()):
    return {"event_id": "EV1", "ticker": ticker, "observed_at": observed}


def test_annotation_carries_mandatory_advisory_labels(ledgers):
    item = ann.annotate_items([_item()])[0]
    mq = item["model_quality"]
    assert mq["advisory_status"] == "ADVISORY ONLY"
    assert mq["human_review"] == "HUMAN REVIEW REQUIRED"
    for field in ("evidence_coverage", "temporal_validity", "llm_grounding",
                  "score_changed_because", "sensitivity_warning", "memo",
                  "what_would_change_my_mind", "post_outcome_review_date"):
        assert field in mq, field


def test_no_banned_phrases_in_annotations(ledgers):
    blob = str(ann.annotate_items([_item()])[0]["model_quality"]).lower()
    for phrase in BANNED:
        assert phrase not in blob, phrase


def test_missing_evidence_surfaces_as_warning(ledgers):
    mq = ann.annotate_items([_item()])[0]["model_quality"]
    assert "NO EVIDENCE" in mq["evidence_coverage"]
    assert "warning" in mq["evidence_coverage"]
    assert "abstain" in mq["llm_grounding"]


def test_grounded_evidence_ids_visible(ledgers):
    ev, _ = ledgers
    _seed_evidence(ev)
    mq = ann.annotate_items([_item()])[0]["model_quality"]
    assert "2 evidence item(s)" in mq["evidence_coverage"]
    assert "EV-" in mq["evidence_coverage"]  # the actual ids
    assert "evidence-backed" in mq["llm_grounding"]


def test_invalid_temporal_status_surfaces_as_warning(ledgers):
    naive = ann.annotate_items([_item(observed="2026-06-01T12:00:00")])[0]
    assert "NAIVE TIMESTAMP" in naive["model_quality"]["temporal_validity"]
    missing = ann.annotate_items([_item(observed="")])[0]
    assert "MISSING" in missing["model_quality"]["temporal_validity"]
    aware = ann.annotate_items([_item()])[0]
    assert aware["model_quality"]["temporal_validity"] == "valid (aware UTC)"


def test_score_movement_explanation_appears(ledgers):
    ev, sc = ledgers
    _seed_evidence(ev)
    dsl.append_score(model_name="m", model_version="1", symbol="ACME",
                     raw_score=0.5, decision_time_utc=NOW.isoformat(),
                     input_evidence_ids=["EV-a"], path=sc)
    dsl.append_score(model_name="m", model_version="1", symbol="ACME",
                     raw_score=0.7, decision_time_utc=NOW.isoformat(),
                     input_evidence_ids=["EV-a", "EV-b"], path=sc)
    mq = ann.annotate_items([_item()])[0]["model_quality"]
    assert "Δ +0.2" in mq["score_changed_because"]
    assert "evidence set changed" in mq["score_changed_because"]


def test_score_moved_without_evidence_is_flagged(ledgers):
    ev, sc = ledgers
    for score in (0.5, 0.8):
        dsl.append_score(model_name="m", model_version="1", symbol="ACME",
                         raw_score=score, decision_time_utc=NOW.isoformat(),
                         input_evidence_ids=["EV-a"], path=sc)
    mq = ann.annotate_items([_item()])[0]["model_quality"]
    assert "WARNING: score moved without recorded evidence change" in \
        mq["score_changed_because"]


def test_memo_pointer_and_review_date(ledgers):
    ev, sc = ledgers
    dsl.append_score(model_name="m", model_version="1", symbol="ACME",
                     raw_score=0.5, decision_time_utc=NOW.isoformat(),
                     input_evidence_ids=["EV-a"],
                     decision_memo_path="reports/decision_memos/ACME_x.md",
                     path=sc)
    mq = ann.annotate_items([_item()])[0]["model_quality"]
    assert mq["memo"].endswith("ACME_x.md")
    assert mq["what_would_change_my_mind"] == "see memo falsifiers"
    assert mq["post_outcome_review_date"] == "2026-07-01"


def test_no_secrets_visible(ledgers, monkeypatch):
    monkeypatch.setenv("MVP_API_TOKEN", "super-secret-token-zq9")
    blob = str(ann.annotate_items([_item()])[0])
    assert "super-secret-token-zq9" not in blob


def test_inbox_endpoint_carries_annotations(ledgers):
    """End-to-end: the live signal inbox response includes model_quality."""
    from scripts.signal_inbox_api import list_inbox_items

    result = list_inbox_items()
    assert result["operation"] == "list_inbox_items"
    for item in result["items"]:
        assert item["model_quality"]["advisory_status"] == "ADVISORY ONLY"
