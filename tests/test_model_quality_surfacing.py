"""Dashboard/report surfacing proofs (Pass 5, Phase 11)."""
from __future__ import annotations

from src.dashboard import streamlit_app as dash

BANNED = ("guaranteed", "sure profit", "must buy", "execute now",
          "place order", "automatic trade")


def test_model_quality_summary_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(tmp_path / "e.jsonl"))
    info = dash._model_quality_summary()
    assert "ADVISORY_ONLY" in info["advisory_label"]
    assert "human review required" in info["advisory_label"]
    assert "zero weight" in info["grounding_rule"]
    assert "t_published" in info["temporal_rule"]
    assert info["readiness_gate_cmd"].endswith("run_model_readiness_gate.py")
    assert info["evidence_items"] == 0  # empty ledger surfaces honestly


def test_summary_counts_real_ledger_items(monkeypatch, tmp_path):
    import datetime as dt

    from scripts import data_quality as dq

    path = tmp_path / "e.jsonl"
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(path))
    item = dq.build_evidence(
        source_type="api", source_name="s", claim="c", raw_evidence=b"r",
        observed_at=dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc),
    )
    dq.append_evidence(item, path)
    info = dash._model_quality_summary()
    assert info["evidence_items"] == 1
    assert info["evidence_ledger_valid"] is True


def test_no_banned_phrases_in_surfacing_text(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(tmp_path / "e.jsonl"))
    blob = str(dash._model_quality_summary()).lower()
    for phrase in BANNED:
        assert phrase not in blob, phrase


def test_scorecard_caps_visible_in_report(tmp_path):
    from scripts import model_scorecard as sc

    segments = [
        {"segment": name, "claimed_score": 9.5,
         "evidence": "x", "has_tests": True, "has_out_of_sample": False,
         "has_independent_validation": False}
        for name in sc.SEGMENT_WEIGHTS
    ]
    path = sc.write_scorecard(segments, out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "clamped to 9" in text  # caps are visible, not silent
    assert "never expected profit" in text
