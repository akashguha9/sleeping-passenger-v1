"""Tests for the read-only Kalshi live integration.

Covers:
- Config loader: redacted repr, sanitized dict has no secrets, safety
  assertion rejects unsafe flag combinations, .env.local parser, no
  printing of secrets.
- Auth signing: PSS signature recipe, query string excluded, supports
  PKCS#8 PEMs, parse failures don't echo key contents.
- Read-only enforcement: forbidden endpoints raise
  ReadOnlyKalshiViolation before any HTTP request is issued.
- Live loader: mocked HTTP, governance applied, sports/esports
  quarantined and never mapped to crypto.
- Source-health emitted with mode/env/auth_used but no secrets.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.ingestion import kalshi_live_client as live_client_module
from src.ingestion.kalshi_live_client import (
    KalshiLiveClient,
    ReadOnlyKalshiViolation,
    build_signing_string,
    load_private_key,
    sign_request,
)
from src.ingestion.kalshi_live_config import (
    KalshiConfigError,
    KalshiLiveConfig,
    load_env_local,
    load_kalshi_live_config,
)
from src.ingestion.kalshi_live_loader import run_live_kalshi_smoke


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


SECRET_API_KEY_ID = "11111111-2222-3333-4444-555555555555"
SECRET_KEY_PATH = "secrets/test_only.key"


@pytest.fixture
def generated_private_key_pem(tmp_path: Path) -> Path:
    """Generate a temporary PKCS#8 RSA key for tests.

    Never reads the operator's real key.
    """
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    out = tmp_path / "tmp_private.key"
    out.write_bytes(pem)
    return out


def _make_env(private_key_path: Path) -> dict[str, str]:
    return {
        "KALSHI_ENV": "demo",
        "KALSHI_API_BASE_URL": "https://external-api.demo.kalshi.co/trade-api/v2",
        "KALSHI_WS_BASE_URL": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
        "KALSHI_API_KEY_ID": SECRET_API_KEY_ID,
        "KALSHI_PRIVATE_KEY_PATH": str(private_key_path),
        "KALSHI_ENABLE_AUTH": "true",
        "KALSHI_READ_ONLY": "true",
        "KALSHI_ENABLE_TRADING": "false",
        "KALSHI_ORDER_PLACEMENT_ENABLED": "false",
        "KALSHI_BROKER_API_CALLED": "false",
        "KALSHI_USE_MOCK_FIXTURES": "false",
        "KALSHI_LIVE_VERIFY": "true",
        "KALSHI_FRESHNESS_TTL_SECONDS": "21600",
        "KALSHI_ALLOWED_CATEGORIES": (
            "elections,politics,crypto,commodities,economics,finance,tech_science"
        ),
    }


# ---------------------------------------------------------------------------
# Config loader tests
# ---------------------------------------------------------------------------


def test_load_env_local_parses_keys_without_printing(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    p = tmp_path / ".env.local"
    p.write_text(
        "# header\nKALSHI_TEST_TOKEN=abc123\nKALSHI_EMPTY=\n",
        encoding="utf-8",
    )
    parsed = load_env_local(p, override=True)
    assert parsed["KALSHI_TEST_TOKEN"] == "abc123"
    out = capsys.readouterr().out + capsys.readouterr().err
    # The parser must never print the value to stdout/stderr.
    assert "abc123" not in out


def test_config_repr_redacts_secrets(generated_private_key_pem: Path):
    cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
    text = repr(cfg)
    # The API key ID and private-key path must be redacted.
    assert SECRET_API_KEY_ID not in text
    assert str(generated_private_key_pem) not in text
    assert "<redacted>" in text


def test_sanitized_dict_excludes_secrets(generated_private_key_pem: Path):
    cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
    pub = cfg.sanitized_dict()
    blob = json.dumps(pub)
    assert SECRET_API_KEY_ID not in blob
    assert str(generated_private_key_pem) not in blob
    # The fields the frontend / source-health need ARE present.
    assert pub["env"] == "demo"
    assert pub["read_only"] is True
    assert pub["enable_trading"] is False
    assert pub["order_placement_enabled"] is False
    assert pub["broker_api_called"] is False
    assert pub["auth_used"] is True


def test_config_rejects_unsafe_flags(generated_private_key_pem: Path):
    env = _make_env(generated_private_key_pem)
    env["KALSHI_ENABLE_TRADING"] = "true"
    with pytest.raises(KalshiConfigError):
        load_kalshi_live_config(environ=env)


def test_config_logging_does_not_emit_api_key_id(
    caplog: pytest.LogCaptureFixture, generated_private_key_pem: Path
):
    with caplog.at_level(logging.DEBUG):
        cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
        logging.getLogger("kalshi_test").debug("cfg=%r", cfg)
    for record in caplog.records:
        msg = record.getMessage()
        assert SECRET_API_KEY_ID not in msg


# ---------------------------------------------------------------------------
# Signing tests
# ---------------------------------------------------------------------------


def test_build_signing_string_excludes_query_params():
    s1 = build_signing_string(1700000000000, "GET", "/markets?limit=20&status=open")
    s2 = build_signing_string(1700000000000, "GET", "/markets")
    assert s1 == s2 == "1700000000000GET/markets"


def test_sign_request_produces_verifiable_pss_signature(
    generated_private_key_pem: Path,
):
    cryptography = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    key = load_private_key(generated_private_key_pem.read_bytes())
    timestamp_ms = 1700000000000
    sig_b64 = sign_request(key, timestamp_ms, "GET", "/markets?limit=20")
    sig = base64.b64decode(sig_b64)
    public_key = key.public_key()
    # Verify against the canonical signing string (query stripped).
    public_key.verify(
        sig,
        b"1700000000000GET/markets",
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )


def test_load_private_key_parse_failure_does_not_echo_pem(tmp_path: Path):
    junk = tmp_path / "junk.key"
    junk.write_bytes(b"-----BEGIN GARBAGE-----\nNOT_A_REAL_PEM\n-----END GARBAGE-----")
    try:
        load_private_key(junk.read_bytes())
    except KalshiConfigError as exc:
        assert "NOT_A_REAL_PEM" not in str(exc)
    else:  # pragma: no cover - should always raise
        pytest.fail("Expected KalshiConfigError")


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------


@pytest.fixture
def live_client(
    monkeypatch: pytest.MonkeyPatch, generated_private_key_pem: Path
) -> KalshiLiveClient:
    cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
    session = MagicMock(spec=["get"])
    # Default response if any HTTP is actually issued — but the
    # read-only tests below MUST raise BEFORE calling .get(), so we
    # also assert .get.called == False where relevant.
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"markets": [], "cursor": None}
    response.raise_for_status.return_value = None
    session.get.return_value = response
    return KalshiLiveClient(cfg, session=session, timeout=1)


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/markets"),
        ("DELETE", "/markets"),
        ("PUT", "/markets"),
        ("PATCH", "/markets"),
    ],
)
def test_non_get_methods_are_blocked(live_client, method: str, path: str):
    with pytest.raises(ReadOnlyKalshiViolation):
        live_client.request(method, path)
    assert live_client._session.get.called is False  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "path",
    [
        "/portfolio/orders",
        "/portfolio/fills",
        "/portfolio/positions",
        "/portfolio/balance",
        "/portfolio/trades",
        "/portfolio/deposits",
        "/portfolio/withdrawals",
        "/api_keys",
        "/api-keys",
        "/exchange/login",
        "/exchange/logout",
        "/account/settings",
    ],
)
def test_trading_and_account_paths_are_blocked(live_client, path: str):
    with pytest.raises(ReadOnlyKalshiViolation):
        live_client.request("GET", path)
    assert live_client._session.get.called is False  # type: ignore[attr-defined]


def test_query_string_does_not_bypass_blocklist(live_client):
    with pytest.raises(ReadOnlyKalshiViolation):
        live_client.request("GET", "/portfolio/orders?status=open")
    assert live_client._session.get.called is False  # type: ignore[attr-defined]


def test_allowed_endpoints_pass_block_check(live_client):
    # These must NOT raise.
    for path in (
        "/exchange/status",
        "/markets",
        "/markets?limit=10",
        "/events/ABC-2026",
        "/series/ABC",
    ):
        live_client.request("GET", path)
    assert live_client._session.get.call_count == 5  # type: ignore[attr-defined]


def test_auth_headers_used_but_not_returned_publicly(
    monkeypatch, live_client, caplog: pytest.LogCaptureFixture
):
    """The client signs requests but never returns or logs the headers."""
    with caplog.at_level(logging.DEBUG):
        live_client.request("GET", "/markets?limit=5")
    # Inspect the call to session.get — auth headers are present...
    call_kwargs = live_client._session.get.call_args.kwargs  # type: ignore[attr-defined]
    headers = call_kwargs["headers"]
    assert "KALSHI-ACCESS-KEY" in headers
    assert "KALSHI-ACCESS-SIGNATURE" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers
    # ...but the API Key ID and signature never reach the log stream.
    for record in caplog.records:
        msg = record.getMessage()
        assert SECRET_API_KEY_ID not in msg
        assert headers["KALSHI-ACCESS-SIGNATURE"] not in msg


# ---------------------------------------------------------------------------
# Live loader (mocked HTTP) + governance
# ---------------------------------------------------------------------------


def _make_fake_client(markets: list[dict]) -> MagicMock:
    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = "https://external-api.demo.kalshi.co/trade-api/v2"
    fake.get_exchange_status.return_value = {"exchange_active": True}
    fake.get_markets.return_value = {"markets": markets, "cursor": None}
    return fake


def test_run_live_smoke_applies_governance_and_writes_health(
    tmp_path: Path, generated_private_key_pem: Path
):
    cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
    markets = [
        {
            "ticker": "BTCMAY-2026",
            "title": "How high will Bitcoin get in May?",
            "category": "Crypto",
            "yes_ask": 0.42,
            "no_ask": 0.58,
            "close_time": "2026-05-31T23:59:00Z",
        },
        {
            "ticker": "PRES-2028-D",
            "title": "Will a Democrat win the 2028 US Presidential Election?",
            "category": "Elections",
            "yes_ask": 0.49,
            "no_ask": 0.51,
            "close_time": "2028-11-08T05:00:00Z",
        },
        {
            "ticker": "KXMVESPORTSMULTIGAME-1234",
            "title": "Esports multi-game",
            "category": "Esports",
            "yes_ask": 0.20,
            "close_time": "2026-07-01T00:00:00Z",
        },
        {
            "ticker": "NBA-FINALS-2026",
            "title": "Will the Lakers win the 2026 NBA Finals?",
            "category": "Sports",
            "yes_ask": 0.10,
            "close_time": "2026-06-30T00:00:00Z",
        },
    ]
    fake_client = _make_fake_client(markets)
    health = tmp_path / "kalshi_source_health.json"
    quarantine = tmp_path / "kalshi_quarantine.jsonl"

    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake_client,
        max_pages=1,
        limit=20,
        dry_run=True,
        health_path=health,
        quarantine_path=quarantine,
    )

    assert result.status == "ok"
    assert result.records_seen_total == 4
    assert result.records_allowed == 2
    assert result.records_quarantined == 2
    assert result.auth_used is True
    assert result.env == "demo"
    # Sports/esports must NOT be present in accepted_category_counts.
    assert "sports" not in result.accepted_category_counts
    assert "esports" not in result.accepted_category_counts
    # Health file written, contains mode/env/auth_used + safety, no secrets.
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["mode"] == "live_read_only"
    assert summary["env"] == "demo"
    assert summary["auth_used"] is True
    assert summary["advisory_only"] is True
    assert summary["broker_api_called"] is False
    assert summary["ai_execution_count"] == 0
    blob = json.dumps(summary)
    assert SECRET_API_KEY_ID not in blob
    assert "BEGIN PRIVATE KEY" not in blob
    assert "KALSHI-ACCESS-KEY" not in blob
    assert "KALSHI-ACCESS-SIGNATURE" not in blob
    # Quarantine jsonl exists and contains both rejected rows.
    lines = [
        json.loads(l)
        for l in quarantine.read_text(encoding="utf-8").splitlines()
        if l.strip()
    ]
    assert len(lines) == 2
    # KXMVESPORTS must never be remapped to crypto.
    for row in lines:
        assert row.get("mvp_category") not in {"crypto", "Crypto"}


def test_run_live_smoke_handles_http_error_without_leaking(
    tmp_path: Path, generated_private_key_pem: Path
):
    cfg = load_kalshi_live_config(environ=_make_env(generated_private_key_pem))
    fake = MagicMock(spec=KalshiLiveClient)
    fake.auth_used = True
    fake.base_url = "https://external-api.demo.kalshi.co/trade-api/v2"
    fake.get_exchange_status.side_effect = RuntimeError("offline")
    fake.get_markets.side_effect = RuntimeError("kalshi 503")
    health = tmp_path / "kalshi_source_health.json"
    quarantine = tmp_path / "kalshi_quarantine.jsonl"
    result = run_live_kalshi_smoke(
        config=cfg,
        client=fake,
        max_pages=1,
        limit=5,
        dry_run=True,
        health_path=health,
        quarantine_path=quarantine,
    )
    assert result.status == "error"
    assert result.records_seen_total == 0
    summary = json.loads(health.read_text(encoding="utf-8"))
    assert summary["mode"] == "live_read_only"
    blob = json.dumps(summary)
    assert SECRET_API_KEY_ID not in blob
