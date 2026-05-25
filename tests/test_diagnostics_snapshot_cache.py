"""Tests for the derived, non-canonical diagnostics snapshot cache (Task 1D).

Proves the cache: (a) is stamped derived/non-canonical, (b) records a failing
subreport as DEGRADED rather than fake-clean zeros, (c) round-trips through
disk, and (d) invalidates on TTL expiry, DB change, corruption, and absence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts import diagnostics_snapshot_cache as cache
from scripts import persistence


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """Redirect the cache file into a temp dir so tests never touch the repo."""
    cache_dir = tmp_path / "diagnostics_cache"
    monkeypatch.setattr(cache, "CACHE_DIR", cache_dir, raising=True)
    monkeypatch.setattr(cache, "CACHE_FILE", cache_dir / "diagnostics_snapshot.json",
                        raising=True)
    return cache_dir


def _ok_collector(_db_path):
    return {"truth_purity": {"status": "OK", "data": {"truth_purity_score": 1.0}}}


def _failing_collector(db_path):
    # One healthy subreport, one that raised — exactly what collect_subreports
    # produces on a real failure.
    return {
        "truth_purity": {"status": "OK", "data": {"truth_purity_score": 1.0}},
        "broken_windows": {
            "status": "DEGRADED",
            "error_type": "OperationalError",
            "recovery_command": "python scripts/broken_windows_report.py",
            "data": None,
        },
    }


# ---------------------------------------------------------------------------
# Stamps: derived / non-canonical
# ---------------------------------------------------------------------------

def test_snapshot_is_derived_non_canonical(isolated_cache):
    snap = cache.build_snapshot(Path("nonexistent.db"), collector=_ok_collector)
    assert snap["canonical_truth_source"] == "sqlite"
    assert snap["cache_role"] == "derived_non_canonical"
    # Carries the advisory safety stamps.
    assert snap["advisory_status"] == "ADVISORY_ONLY"
    assert snap["execution_gate"] == "LOCKED"
    assert snap["broker_api_called"] is False
    assert snap["ai_execution_count"] == 0


# ---------------------------------------------------------------------------
# Partial failure: DEGRADED, never fake-clean zeros
# ---------------------------------------------------------------------------

def test_failed_subreport_is_degraded_not_fake_clean(isolated_cache):
    snap = cache.build_snapshot(Path("x.db"), collector=_failing_collector)
    assert snap["degraded_subreports"] == ["broken_windows"]
    bw = snap["subreports"]["broken_windows"]
    assert bw["status"] == "DEGRADED"
    assert bw["data"] is None  # not silently zeroed
    assert bw["error_type"] == "OperationalError"
    assert bw["recovery_command"]


# ---------------------------------------------------------------------------
# Disk round-trip
# ---------------------------------------------------------------------------

def test_write_read_roundtrip(isolated_cache):
    snap = cache.build_snapshot(Path("x.db"), collector=_ok_collector)
    path = cache.write_snapshot(snap)
    assert path.exists()
    loaded = cache.read_snapshot()
    assert loaded is not None
    assert loaded["cache_role"] == "derived_non_canonical"
    assert loaded["subreports"] == snap["subreports"]


def test_read_missing_returns_none(isolated_cache):
    assert cache.read_snapshot() is None


def test_read_corrupt_returns_none(isolated_cache):
    isolated_cache.mkdir(parents=True, exist_ok=True)
    (isolated_cache / "diagnostics_snapshot.json").write_text("{not json",
                                                              encoding="utf-8")
    assert cache.read_snapshot() is None


# ---------------------------------------------------------------------------
# Validity
# ---------------------------------------------------------------------------

def test_fresh_snapshot_is_valid(isolated_cache, monkeypatch):
    monkeypatch.setattr(cache, "db_mtime", lambda *a, **k: None)
    snap = cache.build_snapshot(Path("x.db"), collector=_ok_collector, ttl_seconds=300)
    v = cache.cache_validity(snap, now_epoch=snap["generated_at_epoch"] + 1)
    assert v["valid"] is True
    assert v["reason"] == "fresh"


def test_ttl_expiry_invalidates(isolated_cache, monkeypatch):
    monkeypatch.setattr(cache, "db_mtime", lambda *a, **k: None)
    snap = cache.build_snapshot(Path("x.db"), collector=_ok_collector, ttl_seconds=60)
    v = cache.cache_validity(snap, now_epoch=snap["generated_at_epoch"] + 61)
    assert v["valid"] is False
    assert v["reason"] == "ttl_expired"


def test_db_change_invalidates(isolated_cache, monkeypatch):
    snap = cache.build_snapshot(Path("x.db"), collector=_ok_collector, ttl_seconds=300)
    snap["snapshot_db_mtime"] = 1000.0
    # Current DB mtime is newer than when the snapshot was built.
    monkeypatch.setattr(cache, "db_mtime", lambda *a, **k: 2000.0)
    v = cache.cache_validity(snap, now_epoch=snap["generated_at_epoch"] + 1)
    assert v["valid"] is False
    assert v["reason"] == "db_changed"


def test_no_snapshot_invalid():
    v = cache.cache_validity(None)
    assert v["valid"] is False
    assert v["reason"] == "no_snapshot"


def test_non_cache_payload_invalid():
    v = cache.cache_validity({"cache_role": "something_else",
                              "generated_at_epoch": 0})
    assert v["valid"] is False
    assert v["reason"] == "not_a_diagnostics_cache"


# ---------------------------------------------------------------------------
# Real diagnostics on an empty schema DB (missing-data safety)
# ---------------------------------------------------------------------------

def test_collect_subreports_on_empty_db(isolated_cache, tmp_path):
    db = tmp_path / "mvp_local.db"
    persistence.init_schema(db)
    subs = cache.collect_subreports(db)
    # All five heavy diagnostics must build (status OK) against an empty schema
    # rather than raising — proves missing-data safety end-to-end.
    assert set(subs) == {"truth_purity", "broken_windows", "closed_loop",
                         "defensive_alpha", "source_independence"}
    assert all(s["status"] == "OK" for s in subs.values()), subs
