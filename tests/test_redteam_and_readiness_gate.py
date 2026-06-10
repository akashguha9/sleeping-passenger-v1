"""Red-team suite (Phase 8) + model readiness gate (Phase 12) proofs."""
from __future__ import annotations

from scripts import redteam_model as rt
from scripts import run_model_readiness_gate as gate


def test_all_redteam_cases_safe():
    cases = rt.run_cases()
    assert len(cases) == 20
    failed = [c["name"] for c in cases if not c["ok"]]
    assert failed == [], f"red-team failures: {failed}"


def test_no_case_produces_confident_recommendation_without_evidence():
    """Every grounding-flavored case must land at weight 0 / reject /
    abstain — the behaviors recorded in the case table."""
    cases = {c["name"]: c for c in rt.run_cases()}
    for name in ("fake_ticker", "hallucinated_catalyst", "insider_rumor",
                 "pump_language", "private_company", "ambiguous_ticker",
                 "dual_listing"):
        assert cases[name]["ok"], name
        assert any(token in cases[name]["behavior"].lower()
                   for token in ("zero", "reject", "fail closed", "note-only",
                                 "does not ground"))


def test_redteam_report_written_with_safe_language(tmp_path):
    cases = rt.run_cases()
    path = rt.write_report(cases, out_dir=tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "20/20 adversarial cases safe" in text
    assert "Advisory-only" in text
    for banned in ("guaranteed", "sure profit", "execute now"):
        assert banned not in text.lower()


def test_redteam_cli_exit_codes(tmp_path, monkeypatch):
    original_write = rt.write_report
    monkeypatch.setattr(rt, "write_report",
                        lambda cases, out_dir=None: original_write(cases, tmp_path))
    assert rt.main() == 0


# ---------------------------------------------------------------------------
# Readiness gate
# ---------------------------------------------------------------------------


def test_every_individual_gate_passes():
    for name, fn in gate.GATES:
        gname, ok, detail = gate._check(name, fn)
        assert ok, f"gate {gname} failed: {detail}"


def test_gate_main_exits_zero(capsys):
    assert gate.main() == 0
    out = capsys.readouterr().out
    assert "result: PASS" in out
    assert out.count("[PASS]") == len(gate.GATES)


def test_gate_fails_closed_on_violation(monkeypatch, capsys):
    """Sabotage one gate → non-zero exit; a crashing gate also fails."""
    bad_gates = (("sabotaged", lambda: (False, "injected failure")),) + gate.GATES[1:]
    monkeypatch.setattr(gate, "GATES", bad_gates)
    assert gate.main() == 1

    def crasher():
        raise RuntimeError("boom")

    monkeypatch.setattr(gate, "GATES", (("crashing", crasher),))
    assert gate.main() == 1
    assert "exception" in capsys.readouterr().out


def test_gate_registry_detects_execution_capable(monkeypatch, tmp_path):
    import json

    registry = {"advisory_only": True, "execution_capable_models_allowed": False,
                "owner": "Akash Guha",
                "models": [{"name": "evil", "owner": "Akash Guha",
                            "execution_capable": True, "human_required": True,
                            "uses_future_data": False}]}
    path = tmp_path / "model_registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(gate, "_REPO_ROOT", tmp_path)
    ok, detail = gate.gate_registry()
    assert ok is False and "evil" in detail
