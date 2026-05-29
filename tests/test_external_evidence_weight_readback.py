"""Paper-only calibrated-weight readback — math, integration, and safety proofs.

Proves that the Moltbook-learned per-bucket advisory weight ``w_b`` is now read
back into the external-evidence score-delta for PAPER analysis only, with
conservative cold-start / error-safe defaults, sample-size gating, and
harm-sensitive damping — and that nothing here can ever touch real-money
sizing, override a DIABLO/CHAOS veto, or let external evidence alone create a
trade.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import private_scope_guard as guard
import scripts.external_evidence_persistence as eep
from scripts.external_evidence_moltbook_calibration import compute_bucket_weights
from scripts.external_adapters.base import ExternalAdapter, ExternalEvidenceType
from scripts.external_adapters.registry import ExternalAdapterRegistry
from scripts.external_advisory_evidence import (
    MAX_NEGATIVE_SCORE_DELTA,
    MAX_POSITIVE_SCORE_DELTA,
    STATUS_ACCEPTED,
    apply_external_evidence_to_score,
    build_external_evidence_bundle,
    render_external_evidence_markdown,
    render_external_evidence_reliability_block,
)
import scripts.external_evidence_weight_readback as wr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _REPO_ROOT / "config" / "external_adapters.yaml"


# --------------------------------------------------------------------------- fakes
class FakeAdapter(ExternalAdapter):
    """A configurable, in-test external adapter (mirrors the pipeline fake)."""

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
        confidence_calibrated=None,
    ) -> None:
        super().__init__(config)
        self.source_name = source_name
        self.evidence_type = evidence_type
        self._alignment = alignment
        self._n = n
        self._w = w
        self._q = q
        self._conf = confidence_calibrated

    def collect(self, context=None):
        out = []
        payload = {"alignment": self._alignment, "note": "fake"}
        if self._conf is not None:
            payload["KRONOS_CONFIDENCE_CALIBRATED"] = self._conf
        for _ in range(self._n):
            out.append(
                self.build_evidence(
                    normalized_payload=dict(payload),
                    data_truth_origin="test_origin",
                    confidence_proxy=self._w,
                    evidence_quality_score=self._q,
                )
            )
        return out


def _isolated_registry(*adapters: ExternalAdapter) -> ExternalAdapterRegistry:
    reg = ExternalAdapterRegistry(config_path=_CONFIG_PATH)
    reg.config.setdefault("external_adapters", {}).setdefault("apollo", {})
    reg.config["external_adapters"]["apollo"]["enabled"] = False
    reg.adapters.clear()
    for adapter in adapters:
        reg.register(adapter)
    return reg


_BUCKET_COLS = (
    "bucket_id", "source_name", "evidence_type", "route_decision",
    "confidence_band", "sample_count", "help_count", "harm_count",
    "false_confidence_count", "help_rate", "harm_rate",
    "false_confidence_rate", "raw_reliability", "sample_multiplier",
    "advisory_weight", "real_money_weight_allowed", "real_money_sizing_impact",
    "last_updated_utc", "proof_status",
)


def _seed_bucket(conn, *, source_name, evidence_type, route_decision, band, n, h, x, f):
    """Insert one calibration bucket with counts (n, h, x, f)."""
    bucket_id = "|".join([source_name, evidence_type, route_decision, band])
    weights = compute_bucket_weights(n, h, x, f)
    row = {
        "bucket_id": bucket_id,
        "source_name": source_name,
        "evidence_type": evidence_type,
        "route_decision": route_decision,
        "confidence_band": band,
        "sample_count": n,
        "help_count": h,
        "harm_count": x,
        "false_confidence_count": f,
        "help_rate": weights["help_rate"],
        "harm_rate": weights["harm_rate"],
        "false_confidence_rate": weights["false_confidence_rate"],
        "raw_reliability": weights["raw_reliability"],
        "sample_multiplier": weights["sample_multiplier"],
        "advisory_weight": weights["advisory_weight"],
        "real_money_weight_allowed": 0,
        "real_money_sizing_impact": "PROHIBITED",
        "last_updated_utc": "2026-05-29T00:00Z",
        "proof_status": "ADVISORY_WEIGHT_PAPER_ONLY_NO_REAL_MONEY",
    }
    placeholders = ", ".join(["?"] * len(_BUCKET_COLS))
    conn.execute(
        f"INSERT OR REPLACE INTO external_evidence_calibration_buckets "
        f"({', '.join(_BUCKET_COLS)}) VALUES ({placeholders})",
        tuple(row[c] for c in _BUCKET_COLS),
    )
    conn.commit()
    return bucket_id, weights


# ============================================================ Section 11 test 1
def test_confidence_band_boundaries() -> None:
    assert wr.confidence_band(None) == "COLD"
    assert wr.confidence_band(0.34) == "LOW"
    assert wr.confidence_band(0.35) == "MID"
    assert wr.confidence_band(0.64) == "MID"
    assert wr.confidence_band(0.65) == "HIGH"


# ============================================================ Section 11 test 2
def test_make_calibration_bucket_id_deterministic() -> None:
    a = wr.make_calibration_bucket_id("kronos", "CANDLESTICK_FORECAST", "WATCH", "MID")
    b = wr.make_calibration_bucket_id("kronos", "CANDLESTICK_FORECAST", "WATCH", "MID")
    assert a == b == "kronos|CANDLESTICK_FORECAST|WATCH|MID"
    assert wr.make_calibration_bucket_id("x", "CANDLESTICK_FORECAST", "WATCH", "MID") != a
    assert wr.make_calibration_bucket_id("kronos", "NARRATIVE", "WATCH", "MID") != a
    assert wr.make_calibration_bucket_id("kronos", "CANDLESTICK_FORECAST", "REJECT", "MID") != a
    assert wr.make_calibration_bucket_id("kronos", "CANDLESTICK_FORECAST", "WATCH", "HIGH") != a


# ============================================================ Section 11 test 3
def test_missing_bucket_uses_cold_start_default(tmp_path) -> None:
    conn = eep._open(tmp_path / "db.sqlite")
    try:
        out = wr.calibrated_weight_for_item(
            conn,
            {"source_name": "kronos", "evidence_type": "CANDLESTICK_FORECAST",
             "route_decision": "WATCH"},
        )
    finally:
        conn.close()
    assert out["advisory_weight"] == 0.25
    assert out["weight_source"] == "COLD_START_DEFAULT"
    assert out["real_money_sizing_impact"] == "PROHIBITED"
    assert out["real_money_weight_allowed"] is False
    assert out["proof_status"] == "COLD_START_NO_BUCKET_PAPER_ONLY"


# ============================================================ Section 11 test 4
def test_calibration_readback_db_error_safe() -> None:
    class BrokenConn:
        def execute(self, *_a, **_k):
            raise RuntimeError("db is down")

    out = wr.calibrated_weight_for_item(
        BrokenConn(), {"source_name": "kronos", "evidence_type": "X", "route_decision": "WATCH"}
    )
    assert out["advisory_weight"] == 0.25
    assert out["weight_source"] == "ERROR_SAFE_DEFAULT"
    assert out["real_money_sizing_impact"] == "PROHIBITED"
    assert out["proof_status"] == "CALIBRATION_READBACK_FAILED_SAFE_DEFAULT"
    # conn=None must also degrade safe (no crash).
    out_none = wr.calibrated_weight_for_item(None, {"source_name": "k"})
    assert out_none["weight_source"] == "ERROR_SAFE_DEFAULT"


# ============================================================ Section 11 test 5
def test_sample_size_gates(tmp_path) -> None:
    conn = eep._open(tmp_path / "db.sqlite")
    try:
        # n < 5 -> cap 0.25 (cold start). All-help bucket has advisory > 0.25,
        # so the cap must bind.
        _seed_bucket(conn, source_name="s", evidence_type="T", route_decision="WATCH",
                     band="MID", n=1, h=1, x=0, f=0)
        cold = wr.calibrated_weight_for_item(
            conn, {"source_name": "s", "evidence_type": "T", "route_decision": "WATCH",
                   "confidence_calibrated": 0.5})
        assert cold["sample_count"] == 1
        assert cold["effective_weight"] <= 0.25
        assert cold["reliability_label"] == "COLD_START"
        assert cold["real_money_weight_allowed"] is False

        # 5 <= n < 30 -> cap 0.50 (early sample).
        _seed_bucket(conn, source_name="s2", evidence_type="T", route_decision="WATCH",
                     band="MID", n=10, h=8, x=0, f=0)
        early = wr.calibrated_weight_for_item(
            conn, {"source_name": "s2", "evidence_type": "T", "route_decision": "WATCH",
                   "confidence_calibrated": 0.5})
        assert early["effective_weight"] <= 0.50
        assert early["reliability_label"] == "EARLY_SAMPLE"

        # 30 <= n < 50 -> cap 0.75 (provisional).
        _seed_bucket(conn, source_name="s3", evidence_type="T", route_decision="WATCH",
                     band="MID", n=40, h=30, x=0, f=0)
        prov = wr.calibrated_weight_for_item(
            conn, {"source_name": "s3", "evidence_type": "T", "route_decision": "WATCH",
                   "confidence_calibrated": 0.5})
        assert prov["effective_weight"] <= 0.75
        assert prov["reliability_label"] == "PROVISIONAL"

        # n >= 50 -> mature, advisory weight allowed (cap does not reduce it).
        _seed_bucket(conn, source_name="s4", evidence_type="T", route_decision="WATCH",
                     band="MID", n=60, h=40, x=0, f=0)
        mature = wr.calibrated_weight_for_item(
            conn, {"source_name": "s4", "evidence_type": "T", "route_decision": "WATCH",
                   "confidence_calibrated": 0.5})
        assert mature["reliability_label"] == "MATURE_PAPER_ONLY"
        assert mature["effective_weight"] == pytest.approx(mature["advisory_weight"])
        assert mature["real_money_weight_allowed"] is False
    finally:
        conn.close()


# ============================================================ Section 11 test 6
def test_harm_sensitive_damping(tmp_path) -> None:
    # Pure damping function.
    assert wr.harm_damping(0.0, 0.0) == 1.00
    assert wr.harm_damping(None, None) == 1.00
    assert wr.harm_damping(0.5, 0.5) == pytest.approx(0.375)
    # Clipped at the 0.25 floor for extreme harm.
    assert wr.harm_damping(1.0, 1.0) == 0.25

    # Integration: a high-harm bucket has effective < advisory (damping bites).
    conn = eep._open(tmp_path / "db.sqlite")
    try:
        _seed_bucket(conn, source_name="h", evidence_type="T", route_decision="WATCH",
                     band="MID", n=60, h=40, x=15, f=5)
        out = wr.calibrated_weight_for_item(
            conn, {"source_name": "h", "evidence_type": "T", "route_decision": "WATCH",
                   "confidence_calibrated": 0.5})
        assert out["harm_damping"] < 1.0
        assert out["effective_weight"] < out["advisory_weight"]
    finally:
        conn.close()


# ============================================================ Section 11 test 7
def test_external_evidence_applies_paper_only_weight(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    # Mature, all-help bucket for the fake's COLD-band WATCH item.
    _, weights = _seed_bucket(
        conn, source_name="fake", evidence_type="CANDLESTICK_FORECAST",
        route_decision="WATCH", band="COLD", n=60, h=40, x=0, f=0)
    conn.close()

    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=db,
    )
    assert bundle["external_evidence_status"] == STATUS_ACCEPTED
    item = bundle["external_evidence_items"][0]
    assert item["paper_only_weight_applied"] is True
    assert item["calibration_weight_source"] == "BUCKET"
    # delta_raw = a*r*q = 1.0 * 0.25 (WATCH) * 1.0 = 0.25
    assert item["score_delta_raw_uncalibrated"] == pytest.approx(0.25)
    c_final = item["calibration_effective_weight"]
    assert item["score_delta"] == pytest.approx(0.25 * c_final)
    assert c_final == pytest.approx(weights["advisory_weight"])
    assert item["real_money_weight_allowed"] is False
    assert item["real_money_sizing_impact"] == "PROHIBITED"


# ============================================================ Section 11 test 8
def test_external_evidence_score_delta_uses_calibrated_sum(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    _seed_bucket(conn, source_name="fake", evidence_type="CANDLESTICK_FORECAST",
                 route_decision="WATCH", band="COLD", n=60, h=40, x=0, f=0)
    conn.close()

    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=2)),
        calibration_db_path=db,
    )
    items = bundle["external_evidence_items"]
    expected = round(sum(i["score_delta"] for i in items), 6)
    assert bundle["external_evidence_score_delta_paper_calibrated"] == pytest.approx(expected)
    assert bundle["external_evidence_score_delta"] == pytest.approx(expected)
    # Each item contribution is delta_raw * c_final * p_i (p_i = 1).
    for i in items:
        assert i["score_delta"] == pytest.approx(
            i["score_delta_raw_uncalibrated"] * i["calibration_effective_weight"]
        )


# ============================================================ Section 11 test 9
def test_external_evidence_score_delta_clamps_after_calibration(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    # Mature high-weight bucket so the calibrated sum can exceed the caps.
    _seed_bucket(conn, source_name="fake", evidence_type="AGENT_COMMITTEE",
                 route_decision="PAPER_TRADE", band="COLD", n=60, h=55, x=0, f=0)
    conn.close()

    pos = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(
            FakeAdapter({"enabled": True}, evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
                        alignment=1.0, n=8)),
        calibration_db_path=db,
    )
    assert pos["external_evidence_score_delta"] == MAX_POSITIVE_SCORE_DELTA

    neg = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(
            FakeAdapter({"enabled": True}, evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
                        alignment=-1.0, n=20)),
        calibration_db_path=db,
    )
    assert neg["external_evidence_score_delta"] == MAX_NEGATIVE_SCORE_DELTA


# =========================================================== Section 11 test 10
def test_external_evidence_calibration_disabled_or_missing_no_crash(tmp_path) -> None:
    # Empty DB (no buckets) -> cold-start, still returns a bundle.
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=tmp_path / "empty.sqlite",
    )
    assert bundle["external_evidence_status"] == STATUS_ACCEPTED
    assert bundle["external_evidence_items"][0]["calibration_weight_source"] == "COLD_START_DEFAULT"

    # Broken connection -> error-safe weights, no crash, bundle still returned.
    class BrokenConn:
        def execute(self, *_a, **_k):
            raise RuntimeError("down")

    bundle2 = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_conn=BrokenConn(),
    )
    assert bundle2["external_evidence_status"] == STATUS_ACCEPTED
    item = bundle2["external_evidence_items"][0]
    assert item["calibration_weight_source"] == "ERROR_SAFE_DEFAULT"
    assert item["calibration_advisory_weight"] == 0.25


# =========================================================== Section 11 test 11
def test_external_evidence_calibration_never_real_money(tmp_path) -> None:
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=2)),
        calibration_db_path=tmp_path / "db.sqlite",
    )
    cal = bundle["external_evidence_calibration"]
    assert cal["real_money_weight_allowed"] is False
    assert cal["real_money_sizing_impact"] == "PROHIBITED"
    assert cal["mode"] == "PAPER_ONLY"
    for item in bundle["external_evidence_items"]:
        assert item["real_money_weight_allowed"] is False
        assert item["real_money_sizing_impact"] == "PROHIBITED"


# =========================================================== Section 11 test 12
def test_diablo_veto_still_overrides_calibrated_positive_evidence(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    _seed_bucket(conn, source_name="fake", evidence_type="AGENT_COMMITTEE",
                 route_decision="PAPER_TRADE", band="COLD", n=60, h=55, x=0, f=0)
    conn.close()
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(
            FakeAdapter({"enabled": True}, evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
                        alignment=1.0, n=4)),
        calibration_db_path=db,
    )
    assert bundle["external_evidence_score_delta"] > 0  # mature, positive
    applied = apply_external_evidence_to_score(4.0, "DIABLO", bundle, safety_veto=True)
    assert applied["final_signal_class"] == "DIABLO"
    assert applied["final_score"] <= 4.0
    assert applied["safety_veto_preserved"] is True


# =========================================================== Section 11 test 13
def test_external_evidence_only_positive_stays_watchlist_even_with_mature_weight(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    _seed_bucket(conn, source_name="fake", evidence_type="AGENT_COMMITTEE",
                 route_decision="PAPER_TRADE", band="COLD", n=60, h=55, x=0, f=0)
    conn.close()
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(
            FakeAdapter({"enabled": True}, evidence_type=ExternalEvidenceType.AGENT_COMMITTEE,
                        alignment=1.0, n=4)),
        calibration_db_path=db,
    )
    applied = apply_external_evidence_to_score(
        2.0, "BUY-CANDIDATE", bundle, external_is_only_positive_evidence=True
    )
    assert applied["final_signal_class"] == "WATCHLIST"
    assert applied["external_only_positive_capped"] is True


# =========================================================== Section 11 test 14
def test_external_evidence_snapshot_persists_calibration_fields(tmp_path) -> None:
    db = tmp_path / "db.sqlite"
    conn = eep._open(db)
    _seed_bucket(conn, source_name="fake", evidence_type="CANDLESTICK_FORECAST",
                 route_decision="WATCH", band="COLD", n=60, h=40, x=0, f=0)
    conn.close()
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=db,
    )
    summary = eep.persist_external_evidence_bundle(
        bundle, {"daily_run_id": "2026-05-29", "signal_id": "SIG1", "ticker": "AAPL"},
        db_path=db,
    )
    assert summary["status"] == "PERSISTED"
    conn = eep._open(db)
    try:
        row = conn.execute(
            "SELECT * FROM external_evidence_snapshots WHERE signal_id='SIG1'"
        ).fetchone()
    finally:
        conn.close()
    d = dict(row)
    assert d["calibration_bucket_id"] == "fake|CANDLESTICK_FORECAST|WATCH|COLD"
    assert d["calibration_effective_weight"] is not None
    assert d["calibration_reliability_label"] == "MATURE_PAPER_ONLY"
    assert d["score_delta_raw_uncalibrated"] == pytest.approx(0.25)
    assert d["score_delta_paper_calibrated"] is not None
    assert d["paper_only_weight_applied"] == 1
    assert d["real_money_weight_allowed"] == 0
    assert d["real_money_sizing_impact"] == "PROHIBITED"


# =========================================================== Section 11 test 15
def test_external_evidence_schema_migration_idempotent_with_calibration_columns(tmp_path) -> None:
    db = tmp_path / "legacy.sqlite"
    conn = eep._persistence._get_conn(db)
    # Pre-sprint snapshot table: has the indexed columns but NOT the calibration
    # columns added by this sprint.
    conn.executescript(
        """
        CREATE TABLE external_evidence_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id TEXT UNIQUE NOT NULL,
            signal_id TEXT, daily_run_id TEXT, ticker TEXT, source_name TEXT,
            outcome_known INTEGER DEFAULT 0, generated_at_utc TEXT,
            score_delta REAL
        );
        INSERT INTO external_evidence_snapshots (snapshot_id, signal_id, score_delta)
        VALUES ('old-row-1', 'OLDSIG', 0.1);
        """
    )
    conn.commit()

    # Run the full schema-ensure twice — idempotent, additive, non-destructive.
    eep.ensure_external_evidence_schema(conn)
    eep.ensure_external_evidence_schema(conn)

    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(external_evidence_snapshots)").fetchall()}
    for c in (
        "calibration_bucket_id", "calibration_effective_weight",
        "score_delta_raw_uncalibrated", "score_delta_paper_calibrated",
        "paper_only_weight_applied", "real_money_weight_allowed",
    ):
        assert c in cols, f"missing migrated column {c}"

    # Old row still loads, with new columns defaulting safely.
    old = conn.execute(
        "SELECT * FROM external_evidence_snapshots WHERE snapshot_id='old-row-1'"
    ).fetchone()
    conn.close()
    assert old is not None
    od = dict(old)
    assert od["signal_id"] == "OLDSIG"
    assert od["score_delta"] == 0.1
    assert od["paper_only_weight_applied"] == 0
    assert od["real_money_weight_allowed"] == 0


# =========================================================== Section 11 test 22
def test_daily_artifact_includes_external_evidence_reliability_block(tmp_path) -> None:
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=tmp_path / "db.sqlite",
    )
    block = render_external_evidence_reliability_block(bundle)
    assert "EXTERNAL EVIDENCE RELIABILITY" in block
    assert "Mode: PAPER_ONLY" in block
    assert "Real-money sizing: PROHIBITED" in block
    assert "Max boost/penalty: +0.5 / -1.0" in block
    # No unsafe execution language.
    low = block.lower()
    for phrase in ("buy now", "sell now", "place order", "execute trade", "broker connected"):
        assert phrase not in low
    # The full markdown render embeds the block.
    assert "EXTERNAL EVIDENCE RELIABILITY" in render_external_evidence_markdown(bundle)

    # Disabled bundle -> compact disabled block, no decision impact.
    disabled = render_external_evidence_reliability_block(build_external_evidence_bundle())
    assert "Disabled" in disabled
    assert "No decision impact" in disabled


# =========================================================== Section 11 test 23
def test_private_scope_guard_weight_readback_modules() -> None:
    report = guard.build_report()
    assert report["review_required"] == [], (
        "weight readback sprint must not introduce review_required modules: "
        f"{report['review_required']!r}"
    )
    assert report["quarantine_leaks"] == []


# =========================================================== Section 11 test 25
def test_advisory_contract_external_evidence_calibration(tmp_path) -> None:
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=tmp_path / "db.sqlite",
    )
    assert bundle["safety"]["broker_api_called"] is False
    assert bundle["safety"]["execution_gate"] == "LOCKED"
    assert bundle["safety"]["ai_execution_count"] == 0
    applied = apply_external_evidence_to_score(5.0, "WATCHLIST", bundle)
    assert applied["execution_gate"] == "LOCKED"
    assert applied["broker_api_called"] is False
    assert applied["ai_execution_count"] == 0
    for item in bundle["external_evidence_items"]:
        assert item["broker_api_called"] is False
        assert item["ai_execution_count"] == 0


# =========================================================== Section 11 test 26
def test_runtime_truth_no_mock_live_reliability(tmp_path) -> None:
    # An empty calibration store must produce explicitly COLD_START labels —
    # never a silently "live/verified" reliability.
    bundle = build_external_evidence_bundle(
        framework_config={"enabled": True},
        registry=_isolated_registry(FakeAdapter({"enabled": True}, alignment=1.0, n=1)),
        calibration_db_path=tmp_path / "empty.sqlite",
    )
    item = bundle["external_evidence_items"][0]
    assert item["calibration_reliability_label"] == "COLD_START"
    assert item["calibration_weight_source"] == "COLD_START_DEFAULT"
    assert "LIVE_VERIFIED" not in str(item)
    assert item["calibration_sample_count"] == 0
