"""Tests — feature registry, PEG research framework, research ledger."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.quant_feature_registry import (
    FEATURE_REGISTRY,
    assemble_state_vector,
    registry_manifest,
)
from scripts.quant_peg_research_engine import (
    FIXTURE,
    build_peg_dataset,
    load_retrocast_corpus,
    peg_experiment,
    peg_value,
)
from scripts.quant_research_ledger import (
    ACCEPTED,
    BLOCKED_BY_DATA,
    record_experiment,
    verify_ledger,
)
from scripts.quant_statistics_engine import INSUFFICIENT_DATA, OK


class TestFeatureRegistry:
    def test_registry_has_core_features_with_contracts(self):
        for name in ("P", "P_dot", "Q", "CES", "PEG", "EXP", "TP", "WF"):
            spec = FEATURE_REGISTRY[name]
            assert spec.null_semantics.startswith("None == UNKNOWN")
            assert spec.epistemic_status in (
                "DERIVED", "ESTIMATED", "CALIBRATED", "HEURISTIC",
                "EXPERIMENTAL", "IDENTIFIED")

    def test_unknown_survives_never_zero(self):
        out = assemble_state_vector({"P": 0.4, "Q": None, "PEG": None})
        assert out["vector"]["Q"] is None
        assert "Q" in out["unknown_features"]
        assert out["coverage"] == pytest.approx(1 / 3, abs=1e-3)

    def test_bounds_violation_flagged_not_clipped(self):
        out = assemble_state_vector({"P": 1.4})
        assert out["status"] == "BOUNDS_VIOLATION"
        assert "P" not in out["vector"]

    def test_unregistered_feature_rejected(self):
        out = assemble_state_vector({"MAGIC_ALPHA": 9.0})
        assert out["status"] == "BOUNDS_VIOLATION"
        assert "unregistered feature: MAGIC_ALPHA" in out["violations"]

    def test_manifest_serializable(self):
        manifest = registry_manifest()
        assert len(manifest) == len(FEATURE_REGISTRY)
        json.dumps(manifest)  # must not raise


class TestPEG:
    def test_peg_zero_invariant(self):
        # If expected == observed then PEG == 0 (hackathon test contract).
        out = peg_value(delta_p=0.4, exposure=0.5, observed_move=0.2)
        assert out["peg"] == pytest.approx(0.0)

    def test_peg_sign_and_z(self):
        out = peg_value(delta_p=0.4, exposure=0.5, observed_move=0.0,
                        sigma_daily=0.02)
        assert out["peg"] == pytest.approx(0.2)
        assert out["peg_z"] == pytest.approx(0.2 / (0.02 + 1e-9), rel=1e-4)
        assert "HEURISTIC" in out["beta_status"]

    def test_corpus_loader_separates_fixture_from_real(self, tmp_path: Path):
        rows = [
            {"record_id": "r1", "market_id": "m", "ticker": "AAA",
             "delta_p": 0.1, "fwd_return_1": 0.0, "fwd_return_5": 0.01,
             "fwd_return_21": 0.02, "data_mode": FIXTURE},
            {"record_id": "r2", "market_id": "m", "ticker": "BBB",
             "delta_p": 0.1, "fwd_return_1": 0.0, "fwd_return_5": 0.01,
             "fwd_return_21": 0.02, "data_mode": "LIVE"},
            {"record_id": "bad"},  # missing fields -> dropped
        ]
        p = tmp_path / "corpus.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows),
                     encoding="utf-8")
        corpus = load_retrocast_corpus(p)
        assert corpus["n_fixture"] == 1
        assert corpus["n_real"] == 1
        assert corpus["dropped"] == 1

    def test_experiment_gates_small_n(self):
        out = peg_experiment([])
        assert out["status"] == INSUFFICIENT_DATA

    def test_experiment_runs_and_carries_data_mode(self):
        rows = [{"record_id": f"r{i}", "market_id": f"m{i % 5}",
                 "ticker": f"T{i}", "delta_p": 0.05 + 0.01 * i,
                 "fwd_return_1": 0.001 * i, "fwd_return_5": 0.002 * i,
                 "fwd_return_21": 0.001 * i, "data_mode": FIXTURE}
                for i in range(30)]
        samples = build_peg_dataset(rows)
        out = peg_experiment(samples)
        assert out["status"] == OK
        assert out["data_modes_present"] == [FIXTURE]
        assert "placebo_verdict" in out
        assert out["exposure_caveat"]
        assert out["signal_class"] == "RESEARCH_ONLY"

    def test_missing_corpus_blocked(self, tmp_path: Path):
        corpus = load_retrocast_corpus(tmp_path / "absent.jsonl")
        assert corpus["status"] == INSUFFICIENT_DATA


class TestResearchLedger:
    def _entry(self, path, i=1, verdict=ACCEPTED):
        return record_experiment(
            experiment_id=f"EXP-{i}", hypothesis="h", data_range="d",
            features=["f"], target="t", config={"a": 1},
            result={"x": i}, n=10, conclusion="c", verdict=verdict,
            run_date="2026-08-16", ledger_path=path)

    def test_append_and_verify_chain(self, tmp_path: Path):
        path = tmp_path / "ledger.jsonl"
        self._entry(path, 1)
        self._entry(path, 2, BLOCKED_BY_DATA)
        assert verify_ledger(path) == {"status": "INTACT", "entries": 2}

    def test_tamper_breaks_chain(self, tmp_path: Path):
        path = tmp_path / "ledger.jsonl"
        self._entry(path, 1)
        self._entry(path, 2)
        lines = path.read_text(encoding="utf-8").splitlines()
        doctored = json.loads(lines[0])
        doctored["n"] = 999   # hindsight rewrite
        lines[0] = json.dumps(doctored, default=str)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert verify_ledger(path)["status"] == "CHAIN_BROKEN"

    def test_invalid_verdict_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError):
            self._entry(tmp_path / "l.jsonl", 1, "TOTALLY_PROFITABLE")
