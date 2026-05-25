"""Tests for ``scripts.portfolio_truth_integrity``."""
from __future__ import annotations

import json

from scripts import portfolio_truth_integrity as pti


def test_closed_position_cannot_enter_H():
    out = pti.classify_positions(
        verified=[{"symbol": "A", "source": "x"}],
        closed=[{"symbol": "A", "reason": "closed"}],
        stale=[],
        disputed=[],
    )
    assert "A" not in out["manageable"]


def test_stale_position_cannot_enter_H():
    out = pti.classify_positions(
        verified=[{"symbol": "B", "source": "x"}],
        closed=[],
        stale=[{"symbol": "B", "reason": "stale"}],
        disputed=[],
    )
    assert "B" not in out["manageable"]


def test_disputed_position_cannot_enter_H():
    out = pti.classify_positions(
        verified=[{"symbol": "C", "source": "x"}],
        closed=[],
        stale=[],
        disputed=[{"symbol": "C", "reason": "operator dispute"}],
    )
    assert "C" not in out["manageable"]


def test_verified_open_position_enters_H():
    out = pti.classify_positions(
        verified=[{"symbol": "OK", "source": "broker_csv"}],
        closed=[], stale=[], disputed=[],
    )
    assert "OK" in out["manageable"]


def test_snapshot_explains_exclusions():
    summary = pti.build_summary()
    by_symbol = {row["symbol"]: row for row in summary["lineage"]}
    assert by_symbol["BBB"]["excluded_by_set"] == "C"
    assert by_symbol["CCC"]["excluded_by_set"] == "S"
    assert by_symbol["DDD"]["excluded_by_set"] == "D"
    assert by_symbol["AAA"]["included_in_H"] == 1


def test_score_reaches_target_in_fixture_mode():
    summary = pti.build_summary()
    assert summary["portfolio_truth_score"] >= 9.7
    assert summary["ok"] is True
    assert summary["manageable_positions"] == ["AAA"]


def test_summary_safety_invariants_preserved():
    summary = pti.build_summary()
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0


def test_no_broker_call_during_summary(monkeypatch):
    # The module must be pure — no socket / urllib usage.
    import urllib.request
    called = {"hits": 0}

    def _no(*a, **k):
        called["hits"] += 1
        raise RuntimeError("broker/network call attempted")

    monkeypatch.setattr(urllib.request, "urlopen", _no, raising=False)
    pti.build_summary()
    assert called["hits"] == 0


def test_write_summary_persists(tmp_path):
    target = tmp_path / "snap.json"
    out = pti.write_summary(target)
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["portfolio_truth_score"] >= 9.7
    assert out["summary_path"] == str(target)
