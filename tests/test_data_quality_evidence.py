"""Evidence ledger / data-quality proofs (Pass 4, Phase 3)."""
from __future__ import annotations

import datetime as dt

import pytest

from scripts import data_quality as dq

UTC = dt.timezone.utc
T0 = dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _item(**kw):
    base = dict(
        source_type="api", source_name="sec_edgar",
        claim="ACME filed a 10-K", raw_evidence=b"raw filing bytes",
        observed_at=T0, published_at=T0 - dt.timedelta(hours=2),
        symbol="acme", confidence=0.8, provenance="https://sec.gov/x",
    )
    base.update(kw)
    return dq.build_evidence(**base)


def test_valid_item_builds_and_normalizes():
    e = _item()
    assert e.symbol == "ACME"
    assert e.advisory_only is True
    assert e.evidence_id.startswith("EV-")
    assert e.raw_hash == dq.hash_raw(b"raw filing bytes")
    assert e.freshness_days is not None and e.freshness_days >= 0


def test_evidence_ids_deterministic_and_collision_resistant():
    a, b = _item(), _item()
    assert a.evidence_id == b.evidence_id  # identical evidence → same id
    c = _item(claim="ACME filed a 10-Q")
    d = _item(raw_evidence=b"different raw bytes")
    assert len({a.evidence_id, c.evidence_id, d.evidence_id}) == 3


def test_raw_hash_changes_with_raw_evidence():
    assert _item().raw_hash != _item(raw_evidence=b"raw filing bytes!").raw_hash


@pytest.mark.parametrize("conf", [-0.1, 1.01, 5, float("nan")])
def test_confidence_bounds_enforced(conf):
    with pytest.raises(dq.EvidenceError):
        _item(confidence=conf)


def test_source_and_timestamp_mandatory():
    with pytest.raises(dq.EvidenceError):
        _item(source_name="")
    with pytest.raises(dq.EvidenceError):
        dq.build_evidence(
            source_type="api", source_name="x", claim="c",
            raw_evidence=b"r", observed_at=None,  # type: ignore[arg-type]
        )


def test_observed_before_published_rejected():
    with pytest.raises(dq.EvidenceError) as ei:
        _item(observed_at=T0, published_at=T0 + dt.timedelta(hours=1))
    assert "time travel" in str(ei.value) or "timezone" in str(ei.value)


def test_naive_timestamps_rejected():
    with pytest.raises(dq.EvidenceError):
        _item(observed_at=dt.datetime(2026, 6, 1, 12, 0))  # no tzinfo


@pytest.mark.parametrize("secret", [
    "api_key=abcd1234efgh5678", "Bearer abcdefghijklmnop1234",
    "sk-aaaaaaaaaaaaaaaaaaaa", "password: hunter2hunter2",
])
def test_secret_looking_values_refused(secret):
    with pytest.raises(dq.EvidenceError):
        _item(claim=f"the config says {secret}")


def test_long_bodies_truncated_not_stored():
    body = "word " * 500
    e = _item(claim=body)
    assert len(e.claim) <= 281
    assert e.claim.endswith("…")


def test_ledger_roundtrip_and_verification(tmp_path):
    ledger = tmp_path / "evidence.jsonl"
    for i in range(3):
        dq.append_evidence(_item(claim=f"claim #{i}"), ledger)
    rows = dq.read_ledger(ledger)
    assert len(rows) == 3
    assert all(r["advisory_only"] is True for r in rows)
    assert dq.verify_ledger(ledger) == []


def test_verify_ledger_catches_tampering(tmp_path):
    ledger = tmp_path / "evidence.jsonl"
    dq.append_evidence(_item(), ledger)
    import json

    row = json.loads(ledger.read_text(encoding="utf-8"))
    row["advisory_only"] = False
    row["confidence"] = 1.5
    row["source_name"] = ""
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")
    violations = dq.verify_ledger(ledger)
    assert any("advisory_only" in v for v in violations)
    assert any("confidence" in v for v in violations)
    assert any("source" in v for v in violations)


def test_env_override_for_ledger_path(monkeypatch, tmp_path):
    monkeypatch.setenv("MVP_EVIDENCE_LEDGER_PATH", str(tmp_path / "alt.jsonl"))
    assert dq.evidence_ledger_path() == tmp_path / "alt.jsonl"
