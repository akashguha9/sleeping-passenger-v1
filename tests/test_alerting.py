"""S4-A2 regression: degraded-state push alerting with cooldown.

Contract: alert fires exactly once on the degraded False→True transition;
steady degraded inside the cooldown is suppressed; after the cooldown it
re-fires; sink failures are counted+logged, never crash; messages are
secret-redacted; alerting observability is stamped on /health/full.
"""
from __future__ import annotations

import logging

import pytest

from scripts import alerting


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MVP_ALERT_STATE_PATH", str(tmp_path / "alert_state.json"))
    monkeypatch.delenv("MVP_ALERT_COOLDOWN_SECONDS", raising=False)
    alerting._reset_for_tests()
    yield
    alerting._reset_for_tests()


class _DryRunSink:
    def __init__(self, fail: bool = False):
        self.messages: list[tuple[str, str]] = []
        self.fail = fail
        self.__name__ = "dryrun_sink"

    def __call__(self, subject: str, body: str) -> None:
        if self.fail:
            raise RuntimeError("sink unavailable")
        self.messages.append((subject, body))


def _health(degraded: bool, *, db_failures: int = 0, recoverable: int = 0,
            wal: int = 0) -> dict:
    return {
        "degraded": degraded,
        "db_write_failures_total": db_failures,
        "write_journal_recoverable_total": recoverable,
        "wal_verification_failures": wal,
    }


def test_transition_false_to_true_sends_one_alert():
    sink = _DryRunSink()
    r1 = alerting.evaluate_and_alert(_health(False), sinks=(sink,), now_epoch=1000)
    assert r1["sent"] is False
    r2 = alerting.evaluate_and_alert(
        _health(True, db_failures=2), sinks=(sink,), now_epoch=1010
    )
    assert r2["sent"] is True
    assert r2["severity"] == "CRITICAL"
    assert len(sink.messages) == 1
    # stamps on the result
    assert r2["execution_gate"] == "LOCKED"
    assert r2["broker_api_called"] is False


def test_steady_degraded_suppressed_inside_cooldown():
    sink = _DryRunSink()
    alerting.evaluate_and_alert(_health(True, recoverable=1), sinks=(sink,), now_epoch=1000)
    r = alerting.evaluate_and_alert(_health(True, recoverable=1), sinks=(sink,), now_epoch=1000 + 60)
    assert r["sent"] is False
    assert r["suppressed_by_cooldown"] is True
    assert len(sink.messages) == 1


def test_resends_after_cooldown():
    sink = _DryRunSink()
    alerting.evaluate_and_alert(_health(True, wal=1), sinks=(sink,), now_epoch=1000)
    r = alerting.evaluate_and_alert(
        _health(True, wal=1), sinks=(sink,),
        now_epoch=1000 + alerting.DEFAULT_COOLDOWN_SECONDS + 1,
    )
    assert r["sent"] is True
    assert len(sink.messages) == 2


def test_severity_matrix():
    assert alerting.classify_severity(_health(True, db_failures=1)) == "CRITICAL"
    assert alerting.classify_severity(_health(True, recoverable=1)) == "HIGH"
    assert alerting.classify_severity(_health(True, wal=1)) == "HIGH"
    assert alerting.classify_severity(_health(True)) == "LOW"


def test_sink_failure_is_counted_logged_and_does_not_crash(caplog):
    bad = _DryRunSink(fail=True)
    good = _DryRunSink()
    with caplog.at_level(logging.ERROR, logger="scripts.alerting"):
        r = alerting.evaluate_and_alert(
            _health(True, db_failures=1), sinks=(bad, good), now_epoch=1000
        )
    assert r["sent"] is True
    assert r["delivery_failures"] == 1
    assert alerting.alert_delivery_failure_count() == 1
    assert len(good.messages) == 1  # other sinks still delivered
    assert any("sink" in rec.message for rec in caplog.records)


def test_secret_redaction_in_alert_body():
    assert "<redacted>" in alerting.redact("token=sk-abcdef1234567890")
    assert "sk-abcdef1234567890" not in alerting.redact(
        "failure Bearer sk-abcdef1234567890 occurred"
    )


def test_health_full_carries_alerting_fields():
    from fastapi.testclient import TestClient

    import scripts.api_server as srv

    client = TestClient(srv.app, raise_server_exceptions=False)
    h = client.get("/health/full")
    assert h.status_code == 200
    body = h.json()
    assert "alert_delivery_failures_total" in body
    assert "last_alert_at" in body
    assert body["execution_gate"] == "LOCKED"


def test_flapping_inside_cooldown_cannot_spam():
    """True→False→True inside the cooldown stays suppressed (flap-proof);
    a re-degradation after the cooldown alerts again."""
    sink = _DryRunSink()
    alerting.evaluate_and_alert(_health(True, wal=1), sinks=(sink,), now_epoch=1000)
    alerting.evaluate_and_alert(_health(False), sinks=(sink,), now_epoch=1100)
    r = alerting.evaluate_and_alert(_health(True, wal=1), sinks=(sink,), now_epoch=1200)
    assert r["sent"] is False
    assert r["suppressed_by_cooldown"] is True
    r2 = alerting.evaluate_and_alert(
        _health(True, wal=1), sinks=(sink,),
        now_epoch=1000 + alerting.DEFAULT_COOLDOWN_SECONDS + 1,
    )
    assert r2["sent"] is True
    assert len(sink.messages) == 2
