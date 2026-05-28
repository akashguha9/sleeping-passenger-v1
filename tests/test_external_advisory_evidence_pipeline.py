"""External advisory-evidence enrichment stage — wiring + safety proofs.

These tests prove the canonical external-adapter framework is now actually
*invoked* by the daily synthesis runtime (not orphaned), while remaining
read-only, advisory-only, watch-only, disabled-by-default, and incapable of
creating a trade or overriding a chaos/safety veto.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import private_scope_guard as guard
from scripts.build_daily_payloads import build_all_daily_payloads
from scripts.daily_synthesis_pipeline import run_daily_synthesis
from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalEvidenceType,
)
from scripts.external_adapters.kronos_adapter import KronosAdapter
from scripts.external_adapters.registry import ExternalAdapterRegistry
from scripts.external_advisory_evidence import (
    IMPACT_ADVISORY_CONTEXT_ONLY,
    IMPACT_NONE,
    MAX_NEGATIVE_SCORE_DELTA,
    MAX_POSITIVE_SCORE_DELTA,
    STATUS_ACCEPTED,
    STATUS_DISABLED,
    STATUS_ERROR_SAFE,
    STATUS_ROUTER_REJECTED,
    apply_external_evidence_to_score,
    build_external_evidence_bundle,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config" / "external_adapters.yaml"
RUN_DATE = "2026-05-22"


# --------------------------------------------------------------------------- fakes
class FakeAdapter(ExternalAdapter):
    """A configurable, in-test external adapter."""

    license_boundary = "test_boundary"

    def __init__(
        self,
        config=None,
        *,
        source_name="fake",
        evidence_type=ExternalEvidenceType.CANDLESTICK_FORECAST,
        alignment=1.0,
        n=1,
        w=1.0,
        q=1.0,
        raise_on_collect=False,
        unsafe_permission=False,
    ) -> None:
        super().__init__(config)
        self.source_name = source_name
        self.evidence_type = evidence_type
        self._alignment = alignment
        self._n = n
        self._w = w
        self._q = q
        self._raise = raise_on_collect
        self._unsafe = unsafe_permission
        self.collect_calls = 0

    def collect(self, context=None):
        self.collect_calls += 1
        if self._raise:
            raise RuntimeError("boom — adapter crashed")
        out = []
        for _ in range(self._n):
            ev = self.build_evidence(
                normalized_payload={"alignment": self._alignment, "note": "fake"},
                data_truth_origin="test_origin",
                confidence_proxy=self._w,
                evidence_quality_score=self._q,
            )
            if self._unsafe:
                # Simulate an adapter trying to claim real execution.
                ev.real_execution_allowed = True
            out.append(ev)
        return out


def _isolated_registry(*adapters: ExternalAdapter) -> ExternalAdapterRegistry:
    """A registry with only the given adapters and Apollo disabled.

    Isolating Apollo (the always-on MISSION_SAFETY reference) keeps the
    bundle status deterministic for these unit tests.
    """
    reg = ExternalAdapterRegistry(config_path=_CONFIG_PATH)
    reg.config.setdefault("external_adapters", {}).setdefault("apollo", {})
    reg.config["external_adapters"]["apollo"]["enabled"] = False
    reg.adapters.clear()
    for adapter in adapters:
        reg.register(adapter)
    return reg


def _flat_ohlcv(n=130, level=100.0):
    return [
        {"open": level, "high": level * 1.01, "low": level * 0.99, "close": level, "volume": 1000.0}
        for _ in range(n)
    ]


def _up_forecast():
    return [100.0 + (5.0 * h / 20.0) for h in range(1, 21)]


def _seed_payload(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "verified_current_holdings.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": []}), encoding="utf-8"
    )
    (base / "do_not_treat_as_open.json").write_text(
        json.dumps(
            {
                "run_date": RUN_DATE,
                "not_owned_do_not_manage": ["UNG"],
                "closed_or_sold_positions": ["GLD"],
                "operator_note": "test",
            }
        ),
        encoding="utf-8",
    )
    (base / "closed_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "positions": [{"ticker": "GLD", "status": "CLOSED"}]}),
        encoding="utf-8",
    )
    (base / "sold_positions.json").write_text(
        json.dumps({"run_date": RUN_DATE, "tickers": ["GLD"]}), encoding="utf-8"
    )


# ----------------------------------------------------------------------- test 1
def test_daily_synthesis_invokes_external_adapter_registry_when_enabled() -> None:
    fake = FakeAdapter({"enabled": True})
    reg = _isolated_registry(fake)
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=reg
    )
    assert fake.collect_calls == 1, "enabled framework must invoke adapter.collect"
    assert bundle["external_evidence_enabled"] is True
    assert bundle["external_evidence_status"] == STATUS_ACCEPTED
    assert bundle["external_evidence_accepted_count"] == 1


# ----------------------------------------------------------------------- test 2
def test_daily_synthesis_external_adapters_disabled_by_default(monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("registry must not be called when disabled")

    monkeypatch.setattr(
        ExternalAdapterRegistry, "collect_external_evidence", _boom
    )
    # Default config (config/external_adapters.yaml) has the framework disabled.
    bundle = build_external_evidence_bundle()
    assert bundle["external_evidence_enabled"] is False
    assert bundle["external_evidence_status"] == STATUS_DISABLED
    assert bundle["external_evidence_decision_impact"] == IMPACT_NONE
    assert bundle["external_evidence_items"] == []


# ----------------------------------------------------------------------- test 3
def test_external_evidence_attached_to_daily_payload(tmp_path: Path) -> None:
    base = tmp_path / "payload"
    _seed_payload(base)
    build_all_daily_payloads(run_date=RUN_DATE, payload_dir=base)
    result = run_daily_synthesis(payload_dir=base)

    assert "external_evidence" in result, "stage output must attach to the result"
    bundle = result["external_evidence"]
    assert bundle["stage"] == "EXTERNAL_ADVISORY_EVIDENCE_ENRICHMENT"
    assert "external_evidence_status" in bundle
    assert "external_evidence_score_delta" in bundle
    assert bundle["external_evidence_decision_impact"] in {
        IMPACT_NONE,
        IMPACT_ADVISORY_CONTEXT_ONLY,
    }
    # Disabled by default => zero decision impact even inside the live pipeline.
    assert bundle["external_evidence_status"] == STATUS_DISABLED
    assert bundle["external_evidence_decision_impact"] == IMPACT_NONE


# ----------------------------------------------------------------------- test 4
def test_external_evidence_score_delta_clamped() -> None:
    # Large positive evidence -> capped at +0.50.
    pos = FakeAdapter(
        {"enabled": True},
        evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
        alignment=1.0,
        n=3,
    )
    bundle_pos = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(pos)
    )
    assert bundle_pos["external_evidence_score_delta_raw"] > MAX_POSITIVE_SCORE_DELTA
    assert bundle_pos["external_evidence_score_delta"] == MAX_POSITIVE_SCORE_DELTA

    # Large negative evidence -> capped at -1.00.
    neg = FakeAdapter(
        {"enabled": True},
        evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
        alignment=-1.0,
        n=3,
    )
    bundle_neg = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(neg)
    )
    assert bundle_neg["external_evidence_score_delta_raw"] < MAX_NEGATIVE_SCORE_DELTA
    assert bundle_neg["external_evidence_score_delta"] == MAX_NEGATIVE_SCORE_DELTA


# ----------------------------------------------------------------------- test 5
def test_external_evidence_cannot_override_diablo() -> None:
    pos = FakeAdapter(
        {"enabled": True},
        evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
        alignment=1.0,
        n=2,
    )
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(pos)
    )
    # Supportive evidence with positive delta...
    assert bundle["external_evidence_score_delta"] > 0

    # ...still cannot upgrade a DIABLO base signal.
    applied = apply_external_evidence_to_score(4.0, "DIABLO", bundle, safety_veto=True)
    assert applied["final_signal_class"] == "DIABLO"
    assert applied["final_score"] <= 4.0
    assert applied["safety_veto_preserved"] is True

    # And at the router, a DIABLO chaos state forces every item to REJECT.
    chaos = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(
            FakeAdapter(
                {"enabled": True},
                evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
                alignment=1.0,
                n=2,
            )
        ),
        pipeline_context={"chaos_state": "DIABLO"},
    )
    assert chaos["external_evidence_score_delta"] == 0.0
    assert chaos["external_evidence_status"] == STATUS_ROUTER_REJECTED
    assert all(it["route_decision"] == "REJECT" for it in chaos["external_evidence_items"])


# ----------------------------------------------------------------------- test 6
def test_external_evidence_only_positive_stays_watchlist() -> None:
    pos = FakeAdapter(
        {"enabled": True},
        evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
        alignment=1.0,
        n=2,
    )
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(pos)
    )
    applied = apply_external_evidence_to_score(
        2.0, "BUY-CANDIDATE", bundle, external_is_only_positive_evidence=True
    )
    assert applied["final_signal_class"] == "WATCHLIST"
    assert applied["external_only_positive_capped"] is True
    # The score may rise, but the class is hard-capped at WATCHLIST.
    assert applied["final_score"] >= applied["base_score"]


# ----------------------------------------------------------------------- test 7
def test_external_adapter_error_safe_no_decision_impact() -> None:
    crasher = FakeAdapter({"enabled": True}, raise_on_collect=True)
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(crasher)
    )
    assert bundle["external_evidence_status"] == STATUS_ERROR_SAFE
    assert bundle["external_evidence_error_count"] >= 1
    assert bundle["external_evidence_score_delta"] == 0.0
    assert bundle["external_evidence_decision_impact"] == IMPACT_NONE

    applied = apply_external_evidence_to_score(6.0, "WATCHLIST", bundle)
    assert applied["final_score"] == 6.0  # base score unchanged


# ----------------------------------------------------------------------- test 8
def test_external_adapter_watch_only_enforced() -> None:
    unsafe = FakeAdapter({"enabled": True}, unsafe_permission=True)
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True}, registry=_isolated_registry(unsafe)
    )
    assert bundle["external_evidence_items"], "expected one routed item"
    for item in bundle["external_evidence_items"]:
        assert item["execution_permission"] in {"WATCH_ONLY", "REJECT_ONLY"}
        assert item["watch_only"] is True
        assert item["broker_api_called"] is False
        assert item["ai_execution_count"] == 0
    # The unsafe permission claim was downgraded (not honoured).
    assert any(
        it["proof_status"] == "EXECUTION_PERMISSION_DOWNGRADED_OR_REJECTED"
        for it in bundle["external_evidence_items"]
    )


# ----------------------------------------------------------------------- test 9
def test_kronos_remains_disabled_by_default() -> None:
    import yaml

    cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["external_adapters"]["kronos"]["enabled"] is False
    assert cfg["external_advisory_evidence"]["enabled"] is False

    # Default pipeline never touches Kronos.
    bundle = build_external_evidence_bundle()
    assert bundle["external_evidence_status"] == STATUS_DISABLED
    assert bundle["external_evidence_items"] == []

    # Even with the framework enabled, a disabled Kronos is not collected.
    reg = ExternalAdapterRegistry(config_path=_CONFIG_PATH)
    reg.config["external_adapters"]["apollo"]["enabled"] = False  # isolate
    enabled = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=reg,
        adapter_context={
            "ohlcv": _flat_ohlcv(130),
            "forecast_closes": _up_forecast(),
        },
    )
    assert all(it["source_name"] != "kronos" for it in enabled["external_evidence_items"])


# ---------------------------------------------------------------------- test 10
def test_kronos_adapter_can_flow_when_explicitly_enabled_in_test() -> None:
    reg = _isolated_registry(KronosAdapter({"enabled": True, "mock_mode": True}))
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=reg,
        adapter_context={
            "ohlcv": _flat_ohlcv(130),
            "forecast_closes": _up_forecast(),
            "existing_signal_score": 5.0,
            "existing_signal_class": "WATCHLIST",
        },
    )
    kron = [it for it in bundle["external_evidence_items"] if it["source_name"] == "kronos"]
    assert len(kron) == 1, "Kronos must flow when explicitly enabled"
    summary = kron[0]["payload_summary"]
    assert "KRONOS_STATUS" in summary
    assert summary["KRONOS_USED_IN_DECISION"] == "EVIDENCE_ONLY"
    assert kron[0]["execution_permission"] == "WATCH_ONLY"
    assert kron[0]["route_decision"] == "WATCH"
    assert bundle["external_evidence_status"] == STATUS_ACCEPTED


# ---------------------------------------------------------------------- test 11
def test_no_broker_or_execution_language_in_external_evidence_output() -> None:
    reg = _isolated_registry(
        KronosAdapter({"enabled": True, "mock_mode": True}),
        FakeAdapter(
            {"enabled": True},
            source_name="fake2",
            evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
        ),
    )
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=reg,
        adapter_context={
            "ohlcv": _flat_ohlcv(130),
            "forecast_closes": _up_forecast(),
        },
    )
    blob = json.dumps(bundle, default=str).lower()
    forbidden = (
        "buy now",
        "sell now",
        "enter now",
        "exit now",
        "place order",
        "place_order",
        "submit order",
        "submit_order",
        "execute trade",
        "execute_trade",
        "broker connected",
        "auto trade",
        "auto-trade",
        "autonomous trading",
    )
    for phrase in forbidden:
        assert phrase not in blob, f"forbidden execution phrase in output: {phrase!r}"


# ---------------------------------------------------------------------- test 12
def test_private_scope_guard_after_adapter_sprint() -> None:
    report = guard.build_report()
    assert report["review_required"] == [], (
        "adapter sprint must not introduce review_required modules: "
        f"{report['review_required']!r}"
    )
    assert report["quarantine_leaks"] == []


# ---------------------------------------------------------------------- test 13
def test_runtime_truth_purity_external_adapters() -> None:
    # Disabled is stated explicitly — never silently "live".
    disabled = build_external_evidence_bundle()
    assert disabled["external_evidence_status"] == STATUS_DISABLED
    assert disabled["external_evidence_decision_impact"] == IMPACT_NONE
    assert disabled["safety"]["broker_api_called"] is False
    assert disabled["safety"]["ai_execution_count"] == 0

    # An enabled Kronos stub never claims a live model forecast in CI, and the
    # mock/stub state is explicit (not mock-pretending-to-be-live).
    reg = _isolated_registry(KronosAdapter({"enabled": True, "mock_mode": True}))
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=reg,
        adapter_context={
            "ohlcv": _flat_ohlcv(130),
            "forecast_closes": _up_forecast(),
        },
    )
    assert bundle["external_evidence_decision_impact"] == IMPACT_ADVISORY_CONTEXT_ONLY
    for item in bundle["external_evidence_items"]:
        assert item["watch_only"] is True
        assert item["broker_api_called"] is False
        assert item["ai_execution_count"] == 0
        mode = item["payload_summary"].get("KRONOS_MODE")
        if mode is not None:
            assert mode in {"stub_safe", "disabled"}, "stub must not masquerade as live"
