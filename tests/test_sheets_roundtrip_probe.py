"""Tests: Sheets round-trip probe (Open-the-Gate sprint, spec Item 4)."""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.sheets_roundtrip_probe import (
    PROBE_HEADERS,
    FixtureWorksheet,
    main,
    row_hash,
    run_roundtrip_probe,
)

NOW = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)


def test_fixture_roundtrip_passes() -> None:
    ws = FixtureWorksheet()
    result = run_roundtrip_probe(ws, now_utc=NOW)
    assert result["status"] == "PASS"
    assert result["checks"]["schema"]["ok"] is True
    assert result["checks"]["idempotency"]["ok"] is True
    assert result["checks"]["readback"]["ok"] is True
    assert (
        result["checks"]["readback"]["write_hash"]
        == result["checks"]["readback"]["read_back_hash"]
    )


def test_duplicate_write_does_not_duplicate() -> None:
    ws = FixtureWorksheet()
    first = run_roundtrip_probe(ws, now_utc=NOW, probe_id="probe_x")
    second = run_roundtrip_probe(ws, now_utc=NOW, probe_id="probe_x")
    assert first["status"] == "PASS"
    assert second["status"] == "PASS"
    assert second["wrote_row"] is False
    # exactly one logical row for the shared dedupe key
    keys = [r[1] for r in ws.all_rows()]
    assert len(keys) == len(set(keys)) == 1


def test_schema_drift_aborts_before_write() -> None:
    ws = FixtureWorksheet(headers=["a", "b", "c"])
    result = run_roundtrip_probe(ws, now_utc=NOW)
    assert result["status"] == "SCHEMA_DRIFT"
    assert ws.all_rows() == [], "nothing may be written after drift detection"


def test_row_hash_mismatch_fails() -> None:
    ws = FixtureWorksheet()
    result = run_roundtrip_probe(ws, now_utc=NOW, probe_id="probe_tamper")
    assert result["status"] == "PASS"
    # tamper with the stored payload -> read-back hash must mismatch
    ws._rows[0][3] = "tampered-payload"  # noqa: SLF001 - test tampering
    tampered = run_roundtrip_probe(ws, now_utc=NOW, probe_id="probe_tamper")
    assert tampered["status"] == "FAIL"
    assert tampered["checks"]["readback"]["ok"] is False


def test_missing_credentials_degraded_not_false_pass(
    capsys, monkeypatch,
) -> None:
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "definitely/absent.json")
    monkeypatch.delenv("SHEETS_PROBE_SHEET_ID", raising=False)
    rc = main(["--live-safe"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"status": "DEGRADED"' in out
    assert "false" in out.lower() or "DEGRADED" in out


def test_hash_ignores_transport_metadata() -> None:
    base = {"probe_id": "p", "dedupe_key": "k", "created_at": "t",
            "payload": "x"}
    with_meta = {**base, "row_hash": "whatever", "transport_ts": "now"}
    assert row_hash(base) == row_hash(with_meta)
    assert PROBE_HEADERS[0] == "probe_id"
