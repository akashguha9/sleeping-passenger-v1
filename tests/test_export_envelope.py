"""Tests for the auditable export envelope (Phase 12 items 22-23).

Schema metadata presence, deterministic checksum, lossless round-trip, and
tamper detection.
"""
from __future__ import annotations

import importlib
import json

import pytest

ee = importlib.import_module("scripts.export_envelope")


def _rows():
    return [{"trade_id": "T1", "pnl": 1.5}, {"trade_id": "T2", "pnl": -0.5}]


def test_envelope_has_required_metadata():
    env = ee.build_envelope(export_name="manual_trades", rows=_rows(),
                            provenance_type="LIVE_MANUAL")
    assert ee.envelope_has_required_metadata(env)
    meta = env["meta"]
    assert meta["schema_version"] == ee.SCHEMA_VERSION
    assert meta["provenance_type"] == "LIVE_MANUAL"
    assert meta["source_count"] == 2
    assert len(meta["content_checksum"]) == 64  # sha256 hex
    assert meta["advisory_only"] is True


def test_checksum_is_deterministic_and_order_independent():
    rows_a = [{"a": 1, "b": 2}]
    rows_b = [{"b": 2, "a": 1}]  # same content, different key order
    assert ee.content_checksum(rows_a) == ee.content_checksum(rows_b)


def test_round_trip_preserves_rows():
    env = ee.build_envelope(export_name="x", rows=_rows(), provenance_type="PAPER",
                            generated_at_utc="2026-01-01T00:00:00+00:00")
    parsed = ee.parse_envelope(ee.dump_envelope(env))
    assert parsed["rows"] == _rows()
    assert ee.round_trip_ok(env)


def test_tampered_rows_fail_checksum():
    env = ee.build_envelope(export_name="x", rows=_rows(), provenance_type="PAPER")
    text = ee.dump_envelope(env)
    obj = json.loads(text)
    obj["rows"].append({"trade_id": "INJECTED", "pnl": 999})
    with pytest.raises(ValueError):
        ee.parse_envelope(json.dumps(obj))


def test_bad_provenance_rejected():
    with pytest.raises(ValueError):
        ee.build_envelope(export_name="x", rows=[], provenance_type="NONSENSE")


def test_empty_export_is_valid_no_data():
    env = ee.build_envelope(export_name="empty", rows=[], provenance_type="NO_DATA")
    assert env["meta"]["source_count"] == 0
    assert ee.round_trip_ok(env)
