"""KronosAdapter integration tests — proves Kronos is wired, not orphaned.

The adapter is the single canonical Kronos runtime path:
config -> registry -> KronosAdapter -> kronos_price_path_evidence helper ->
ExternalEvidence(CANDLESTICK_FORECAST) -> ExternalEvidenceRouter.

Covers required tests 1-7 plus the no-parallel-paths guard.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import kronos_price_path_evidence as kpe
from scripts.core.external_evidence_router import ExternalEvidenceRouter
from scripts.external_adapters.base import ExternalAdapterStatus
from scripts.external_adapters.kronos_adapter import KronosAdapter

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
FIXTURE_PATH = Path("tests/fixtures/external_adapters/kronos/sample_ohlcv.csv")


# --------------------------------------------------------------------------- helpers
def _ohlcv_rows(closes):
    return [
        {"open": c, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": 1000.0}
        for c in closes
    ]


def _flat_rows(n=130, level=100.0):
    return _ohlcv_rows([level] * n)


def _up_forecast():
    return [100.0 + (5.0 * h / 20.0) for h in range(1, 21)]


def _down_forecast():
    return [100.0 - (5.0 * h / 20.0) for h in range(1, 21)]


# --------------------------------------------------------------------------- legacy
def test_kronos_optional_import_and_technical_only_evidence() -> None:
    adapter = KronosAdapter({"enabled": True, "lazy_import": True, "mock_mode": True})
    evidence = adapter.collect({"path": str(FIXTURE_PATH)})[0]
    assert evidence.normalized_payload["technical_evidence_only"] is True
    assert evidence.real_execution_allowed is False
    assert evidence.execution_permission.value == "WATCH_ONLY"


def test_kronos_action_sanitization() -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    evidence = adapter.collect(
        {"path": str(FIXTURE_PATH), "action": "BUY", "validation_flags": True}
    )[0]
    assert evidence.normalized_payload["sanitized_action"] == "WATCH"


# ------------------------------------------------- 1. adapter uses the math helper
def test_kronos_adapter_uses_price_path_evidence_math() -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    ev = adapter.collect(
        {
            "ohlcv": _flat_rows(130),
            "forecast_closes": _up_forecast(),
            "existing_signal_score": 5.0,
            "existing_signal_class": "WATCHLIST",
        }
    )[0]
    p = ev.normalized_payload
    # The rich metrics only exist if the adapter called the math helper.
    for key in (
        "KRONOS_STATUS",
        "KRONOS_FORECAST_RETURN_PCT",
        "KRONOS_FORECAST_VOLATILITY_PCT",
        "KRONOS_DOWNSIDE_PATH_RISK",
        "KRONOS_UPSIDE_PATH_SCORE",
        "KRONOS_DIRECTIONAL_AGREEMENT",
        "KRONOS_CONFIDENCE_RAW",
        "KRONOS_CONFIDENCE_CALIBRATED",
        "KRONOS_ALIGNMENT_BONUS",
        "KRONOS_DOWNSIDE_PENALTY",
        "KRONOS_NOISE_PENALTY",
        "KRONOS_FINAL_SCORE_DELTA",
        "KRONOS_PROOF_STATUS",
    ):
        assert key in p, f"missing {key} — adapter not using math helper"
    assert p["KRONOS_STATUS"] == "SUPPORTIVE"
    assert p["KRONOS_FORECAST_RETURN_PCT"] == pytest.approx(5.0, abs=1e-6)
    assert 0 < p["KRONOS_FINAL_SCORE_DELTA"] <= 0.50
    assert p["KRONOS_USED_IN_DECISION"] == "EVIDENCE_ONLY"
    # Safety stamps carried through.
    assert p["advisory_only"] is True
    assert p["execution_gate"] == "LOCKED"
    assert p["broker_api_called"] is False
    assert p["ai_execution_count"] == 0
    assert ev.execution_permission.value == "WATCH_ONLY"
    assert ev.adapter_status == ExternalAdapterStatus.AVAILABLE


# ------------------------------------- 2. evidence routes through the real router
def test_kronos_adapter_routes_through_external_evidence_router() -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    ev = adapter.collect(
        {"ohlcv": _flat_rows(130), "forecast_closes": _up_forecast()}
    )[0]
    route = ExternalEvidenceRouter().route(ev, pipeline_context={})
    assert route["evidence_type"] == "CANDLESTICK_FORECAST"
    assert "TechnicalEvidence" in route["recommended_pipeline_path"]
    assert "Murcielago Durability" in route["recommended_pipeline_path"]
    assert route["max_allowed_action"] == "WATCH"
    assert route["real_execution_allowed"] is False
    assert any("cannot paper trade" in note.lower() for note in route["notes"])


# ------------------------------------------------- 3. only ONE Kronos truth path
def test_no_parallel_kronos_truth_paths() -> None:
    # The removed orphan modules must not reappear.
    for gone in (
        "kronos_persistence.py",
        "kronos_moltbook_learning.py",
        "kronos_source_health.py",
    ):
        assert not (_SCRIPTS / gone).exists(), f"orphan module re-created: {gone}"

    # The math helper may only be *imported* by the canonical adapter.
    importers: list[str] = []
    for py in _SCRIPTS.rglob("*.py"):
        if py.name == "kronos_price_path_evidence.py":
            continue
        for line in py.read_text(encoding="utf-8").splitlines():
            if "kronos_price_path_evidence" in line and "import" in line:
                importers.append(py.relative_to(_REPO_ROOT).as_posix())
                break
    assert importers == ["scripts/external_adapters/kronos_adapter.py"], (
        f"unexpected importers of the Kronos math helper: {importers}"
    )


# --------------------------------------------- 4. supportive evidence != a trade
def test_kronos_adapter_cannot_create_trade() -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    ev = adapter.collect(
        {
            "ohlcv": _flat_rows(130),
            "forecast_closes": _up_forecast(),
            "existing_signal_score": 5.0,
            "existing_signal_class": "WATCHLIST",
            "kronos_is_only_positive_evidence": True,
        }
    )[0]
    p = ev.normalized_payload
    assert p["KRONOS_STATUS"] == "SUPPORTIVE"
    # Kronos alone can never exceed WATCHLIST.
    assert p["KRONOS_FINAL_SIGNAL_CLASS"] == "WATCHLIST"
    # The router caps candlestick evidence at WATCH and blocks real execution.
    route = ExternalEvidenceRouter().route(ev, pipeline_context={})
    assert route["max_allowed_action"] == "WATCH"
    assert "REAL_EXECUTION" in route["blocked_actions"]
    assert ev.real_execution_allowed is False


# ------------------------------------------------ 5. cannot override a chaos veto
@pytest.mark.parametrize("veto_class", ["DIABLO", "NO_NEW_RISK", "CHAOS_VETO"])
def test_kronos_adapter_cannot_override_diablo(veto_class) -> None:
    adapter = KronosAdapter({"enabled": True, "mock_mode": True})
    ev = adapter.collect(
        {
            "ohlcv": _flat_rows(130),
            "forecast_closes": _up_forecast(),
            "existing_signal_score": 4.0,
            "existing_signal_class": veto_class,
        }
    )[0]
    p = ev.normalized_payload
    assert p["KRONOS_STATUS"] == "SUPPORTIVE"  # positive evidence
    assert p["KRONOS_FINAL_SIGNAL_CLASS"] == veto_class  # not upgraded
    assert p["KRONOS_SAFETY_VETO_PRESERVED"] is True
    assert p["KRONOS_CANDIDATE_FINAL_SCORE"] <= p["KRONOS_BASE_SCORE"]
    # And at the router, a DIABLO chaos state forces REJECT.
    route = ExternalEvidenceRouter().route(ev, pipeline_context={"chaos_state": "DIABLO"})
    assert route["max_allowed_action"] == "REJECT"
    assert "PAPER_TRADE" in route["blocked_actions"]


# --------------------------------------------------- 6. disabled by default (yaml)
def test_kronos_adapter_disabled_by_default() -> None:
    import yaml

    cfg = yaml.safe_load(
        (_REPO_ROOT / "config" / "external_adapters.yaml").read_text(encoding="utf-8")
    )
    kronos_cfg = cfg["external_adapters"]["kronos"]
    assert kronos_cfg["enabled"] is False
    assert kronos_cfg["real_execution_allowed"] is False
    # Code-level: an unconfigured adapter is disabled and emits nothing.
    adapter = KronosAdapter({})
    assert adapter.status() == ExternalAdapterStatus.DISABLED
    assert adapter.collect({"ohlcv": _flat_rows(130)}) == []


# ----------------------------------------- 7. no model download / network in CI
def test_kronos_adapter_no_model_download_in_ci() -> None:
    # Even when live is requested, absent local Kronos weights it stays stub.
    adapter = KronosAdapter({"enabled": True, "mock_mode": True, "live_advisory": True})
    ev = adapter.collect(
        {"ohlcv": _flat_rows(130), "forecast_closes": _up_forecast()}
    )[0]
    p = ev.normalized_payload
    if not kpe.live_available():
        assert p["KRONOS_MODE"] == "stub_safe"
        assert ev.data_truth_origin == "stub_forecast"
    # A stub/disabled read never claims a live model forecast origin falsely.
    assert ev.real_execution_allowed is False


# ------------------------------------------------------- healthcheck folds health
def test_kronos_adapter_healthcheck_is_advisory_only() -> None:
    disabled = KronosAdapter({"enabled": False}).healthcheck()
    assert disabled["health_state"] == "DISABLED"
    assert disabled["is_execution_provider"] is False
    assert disabled["broker_connected"] is False
    assert disabled["real_execution_allowed"] is False
    assert "not an execution provider" in disabled["advisory_notice"].lower()

    stub = KronosAdapter({"enabled": True}).healthcheck()
    assert stub["health_state"] == "STUB_SAFE"

    live_req = KronosAdapter({"enabled": True, "live_advisory": True}).healthcheck()
    assert live_req["health_state"] in {"MODEL_UNAVAILABLE", "LIVE_ADVISORY"}
