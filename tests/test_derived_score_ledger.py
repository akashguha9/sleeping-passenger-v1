"""Derived score ledger proofs (Pass 6, Phase 3)."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from scripts import derived_score_ledger as dsl
from scripts import verify_derived_score_ledger as vdsl

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "scores.jsonl"
    monkeypatch.setenv("MVP_DERIVED_SCORE_LEDGER_PATH", str(path))
    return path


def _score(**kw):
    base = dict(model_name="fcs", model_version="1.0", symbol="acme",
                raw_score=0.7, decision_time_utc=NOW,
                input_evidence_ids=["EV-1", "EV-2"], confidence=0.6,
                temporal_validity="valid", grounding_status="evidence_backed")
    base.update(kw)
    return dsl.append_score(**base)


def test_chain_appends_and_verifies(ledger):
    for i in range(4):
        _score(raw_score=0.5 + i / 10, path=ledger)
    result = dsl.verify_chain(ledger)
    assert result["valid"] is True and result["records"] == 4
    first = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert first["previous_hash"] == "0" * 64
    assert first["symbol"] == "ACME"
    assert first["score_id"].startswith("DS-")


def test_tamper_detected(ledger):
    for i in range(3):
        _score(raw_score=0.5 + i / 10, path=ledger)
    lines = ledger.read_text(encoding="utf-8").splitlines()
    middle = json.loads(lines[1])
    middle["raw_score"] = 0.99  # tamper
    lines[1] = dsl.canonical_json(middle)
    ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = dsl.verify_chain(ledger)
    assert result["valid"] is False
    assert any("modified" in e for e in result["errors"])


def test_score_without_evidence_becomes_abstain(ledger):
    record = _score(input_evidence_ids=[], abstain=False, path=ledger)
    assert record["abstain"] is True
    assert record["grounding_status"] == dsl.NO_EVIDENCE_ABSTAIN
    assert dsl.verify_chain(ledger)["valid"] is True


@pytest.mark.parametrize("field", ["order_id", "broker", "execution_status",
                                   "fill_price", "filled_quantity", "venue"])
def test_execution_shaped_fields_refused(ledger, field):
    with pytest.raises(dsl.ScoreLedgerError):
        _score(path=ledger, **{field: "evil"})
    with pytest.raises(dsl.ScoreLedgerError):
        _score(path=ledger, feature_values={field: 1.0})
    assert not ledger.exists()  # nothing written


def test_missing_temporal_validity_lowers_confidence(ledger):
    record = _score(temporal_validity="unknown", confidence=0.9, path=ledger)
    assert record["confidence"] <= 0.4
    valid = _score(temporal_validity="valid", confidence=0.9, path=ledger)
    assert valid["confidence"] == 0.9


def test_score_links_to_memo_and_explanation(ledger):
    record = _score(decision_memo_path="reports/decision_memos/ACME_x.md",
                    score_explanation_path="reports/score_change_explanations/ACME.md",
                    path=ledger)
    assert record["decision_memo_path"].endswith("ACME_x.md")
    assert record["score_explanation_path"].endswith("ACME.md")


def test_advisory_and_human_review_flags_required(ledger):
    record = _score(path=ledger)
    assert record["advisory_only"] is True
    assert record["human_review_required"] is True
    # Verifier rejects a forged record without the flags.
    row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    row["advisory_only"] = False
    row["event_hash"] = dsl.compute_hash(
        {k: v for k, v in row.items() if k != "event_hash"}, row["previous_hash"])
    ledger.write_text(dsl.canonical_json(row) + "\n", encoding="utf-8")
    result = dsl.verify_chain(ledger)
    assert result["valid"] is False
    assert any("advisory_only" in e for e in result["errors"])


def test_confidence_bounds(ledger):
    with pytest.raises(dsl.ScoreLedgerError):
        _score(confidence=1.5, path=ledger)
    with pytest.raises(dsl.ScoreLedgerError):
        _score(calibrated_probability=-0.1, path=ledger)


def test_verifier_cli(ledger, capsys):
    _score(path=ledger)
    assert vdsl.main(["--path", str(ledger)]) == 0
    lines = ledger.read_text(encoding="utf-8").splitlines()
    ledger.write_text(lines[0][:-5] + "}\n", encoding="utf-8")  # corrupt
    assert vdsl.main(["--path", str(ledger)]) == 1
