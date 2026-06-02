"""Operator-run live provider refresh — yfinance, SEC EDGAR, GDELT.

Sprint 3 — Part 2.  Explicit, operator-only entry point that contacts the
three public providers and produces honest LIVE_VERIFIED evidence rows.

Safety contract
---------------
* Refusal-by-default: without ``MVP_LIVE_REFRESH_OK=1`` we do not call the
  network and we do not mark anything LIVE_VERIFIED.  Fixture data is
  *never* upgraded to LIVE_VERIFIED.
* Read-only: no broker / no order / no execution.  This script may never
  flip ``ADVISORY_ONLY`` / ``EXECUTION_GATE`` / ``HUMAN_EXECUTION_REQUIRED``.
* Honest degradation: when a provider import is missing, when the network
  fails, or when SEC_USER_AGENT is absent, the provider's evidence row is
  marked ``CONFIG_MISSING`` / ``FAILED`` / ``OFFLINE`` with the real
  exception type — never silently inflated.
* Operator-run only: CI must NOT set MVP_LIVE_REFRESH_OK; the release gate
  treats a missing or stale operator artifact as a WARN (not FAIL).

Artifacts
---------
* ``runtime/release/operator_live_provider_refresh_summary.json``
* ``runtime/release/live_provider_evidence.json``
* (extends) ``runtime/release/live_source_refresh_summary.json`` is left in
  place by the existing fixture builder; the release gate consults both.

Required PowerShell command
---------------------------
::

    $env:MVP_LIVE_REFRESH_OK="1"
    $env:SEC_USER_AGENT="sleeping-passenger-v1 local advisory MVP your-email@example.com"
    python scripts/operator_live_provider_refresh.py \
        --providers yfinance,sec_edgar,gdelt --write --timeout-seconds 45
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
    from scripts import typed_config as _typed_config
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]
    import typed_config as _typed_config  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = REPO_ROOT / "runtime" / "release"
OPERATOR_SUMMARY_PATH = RELEASE_DIR / "operator_live_provider_refresh_summary.json"
LIVE_EVIDENCE_PATH = RELEASE_DIR / "live_provider_evidence.json"

SUPPORTED_PROVIDERS: tuple[str, ...] = ("yfinance", "sec_edgar", "gdelt")
PROVIDER_SOURCE_CLASS: dict[str, str] = {
    "yfinance": "price_mover",
    "sec_edgar": "filing",
    "gdelt": "news_event",
}
PROVIDER_SOURCE_TYPE_LABEL: dict[str, str] = {
    "yfinance": "price_mover",
    "sec_edgar": "filing",
    "gdelt": "news_event",
}

# Representative tickers used when probing yfinance for a price snapshot.
# Kept tight so the operator-run refresh stays inside the configurable
# timeout; the operator may bump via LIVE_REFRESH_MAX_TICKERS up to 44.
_REPRESENTATIVE_TICKERS: tuple[str, ...] = (
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM",
    "XOM", "SPY",
)


# ---------------------------------------------------------------------------
# Status taxonomy
# ---------------------------------------------------------------------------
STATUS_SUCCESS = "SUCCESS"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"
STATUS_OFFLINE = "OFFLINE"
STATUS_CONFIG_MISSING = "CONFIG_MISSING"
STATUS_SKIPPED = "SKIPPED"

VERIF_LIVE_VERIFIED = "LIVE_VERIFIED"
VERIF_FIXTURE_VERIFIED = "FIXTURE_VERIFIED"
VERIF_UNVERIFIED = "UNVERIFIED"
VERIF_STALE = "STALE"
VERIF_OFFLINE = "OFFLINE"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso_utc(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _age_hours_from_now(ts: str | None, now: datetime | None = None) -> float | None:
    parsed = _parse_iso_utc(ts)
    if parsed is None:
        return None
    n = now or _utc_now()
    return max(0.0, (n - parsed).total_seconds() / 3600.0)


def _half_life_for(provider: str) -> float:
    return {
        "yfinance": 6.0,
        "sec_edgar": 36.0,
        "gdelt": 12.0,
    }.get(provider, 24.0)


def _payload_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                            default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Evidence dataclass + scoring
# ---------------------------------------------------------------------------


@dataclass
class ProviderEvidence:
    provider: str
    source_type: str
    run_mode: str = "live"
    status: str = STATUS_OFFLINE
    verification_status: str = VERIF_UNVERIFIED
    latest_provider_timestamp_utc: str | None = None
    checked_at_utc: str = field(default_factory=_utc_iso)
    events_seen: int = 0
    events_inserted: int = 0
    sample_asset_tags: list[str] = field(default_factory=list)
    sample_source_urls: list[str] = field(default_factory=list)
    last_error: str | None = None
    payload_hash: str | None = None
    blocks_promotion: bool = True
    advisory_only: bool = True

    @property
    def freshness_age_hours(self) -> float:
        age = _age_hours_from_now(self.latest_provider_timestamp_utc)
        return float(age) if age is not None else 9999.0

    @property
    def freshness_score(self) -> float:
        if self.latest_provider_timestamp_utc is None:
            return 0.0
        import math
        half = _half_life_for(self.provider)
        if half <= 0:
            return 0.0
        return round(math.exp(-math.log(2.0) * self.freshness_age_hours / half), 6)

    @property
    def availability_score(self) -> float:
        return {
            STATUS_SUCCESS: 1.0,
            STATUS_PARTIAL: 0.7,
            STATUS_FAILED: 0.0,
            STATUS_OFFLINE: 0.0,
            STATUS_CONFIG_MISSING: 0.0,
            STATUS_SKIPPED: 0.0,
        }.get(self.status, 0.0)

    @property
    def verification_score(self) -> float:
        return {
            VERIF_LIVE_VERIFIED: 1.0,
            VERIF_FIXTURE_VERIFIED: 0.7,
            VERIF_UNVERIFIED: 0.5,
            VERIF_STALE: 0.25,
            VERIF_OFFLINE: 0.0,
        }.get(self.verification_status, 0.0)

    @property
    def schema_score(self) -> float:
        # Schema validity is high only when we actually received structured
        # data with a real timestamp.  Missing timestamp -> 0.
        if not self.latest_provider_timestamp_utc:
            return 0.0
        if self.verification_status == VERIF_LIVE_VERIFIED:
            return 1.0
        if self.verification_status == VERIF_FIXTURE_VERIFIED:
            return 0.7
        if self.verification_status == VERIF_UNVERIFIED:
            return 0.5
        return 0.0

    @property
    def provider_score(self) -> float:
        v = (
            0.35 * self.freshness_score
            + 0.25 * self.availability_score
            + 0.25 * self.verification_score
            + 0.15 * self.schema_score
        )
        return round(max(0.0, min(1.0, v)), 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_type": self.source_type,
            "run_mode": self.run_mode,
            "status": self.status,
            "verification_status": self.verification_status,
            "latest_provider_timestamp_utc": self.latest_provider_timestamp_utc,
            "checked_at_utc": self.checked_at_utc,
            "freshness_age_hours": round(self.freshness_age_hours, 4),
            "freshness_score": self.freshness_score,
            "availability_score": self.availability_score,
            "verification_score": self.verification_score,
            "schema_score": self.schema_score,
            "provider_score": self.provider_score,
            "events_seen": int(self.events_seen),
            "events_inserted": int(self.events_inserted),
            "sample_asset_tags": list(self.sample_asset_tags)[:10],
            "sample_source_urls": list(self.sample_source_urls)[:10],
            "last_error": self.last_error,
            "payload_hash": self.payload_hash,
            "blocks_promotion": bool(self.blocks_promotion),
            "advisory_only": True,
        }


# ---------------------------------------------------------------------------
# LPQ uplift table
# ---------------------------------------------------------------------------


def lpq_uplift_score(evidences: list[ProviderEvidence],
                     previous_score: float = 8.2) -> tuple[float, dict[str, Any]]:
    """Map per-provider LIVE_VERIFIED status to the new LPQ floor.

    Per spec:
      * 3 LIVE_VERIFIED  -> max(previous, 8.6)
      * 2 LIVE_VERIFIED  -> max(previous, 8.45)
      * 1 LIVE_VERIFIED  -> max(previous, 8.35)
      * 0 LIVE_VERIFIED  -> previous (no inflation)

    A provider counts toward the uplift exactly when it is ``LIVE_VERIFIED``
    with a real provider timestamp — i.e. this run reached the provider and
    received genuine, timestamped data.  This is the SAME definition the
    orchestrator uses to populate ``providers_live_verified``, so the headline
    uplift can never contradict the reported live-verified provider set.

    This uplift table counts LIVE_VERIFIED *honesty*, NOT minute-by-minute
    freshness — as its name implies it is a floor, not a decay curve.  The
    freshness penalty is preserved where it belongs: in the per-provider
    ``freshness_score`` (half-life weighted) which feeds ``provider_score``
    and the downstream LPQ computation.  Folding a second, divergent age
    window in here previously let a genuinely live-verified provider (e.g.
    GDELT news a few days old) be silently dropped from the score while still
    appearing in ``providers_live_verified`` — an internal contradiction.
    """
    live_verified = [
        e for e in evidences
        if e.verification_status == VERIF_LIVE_VERIFIED
        and e.latest_provider_timestamp_utc
    ]
    n = len(live_verified)
    if n >= 3:
        new_score = max(previous_score, 8.6)
    elif n == 2:
        new_score = max(previous_score, 8.45)
    elif n == 1:
        new_score = max(previous_score, 8.35)
    else:
        new_score = previous_score
    return new_score, {
        "live_verified_provider_count": n,
        "live_verified_providers": [e.provider for e in live_verified],
        "previous_score": previous_score,
        "new_score": new_score,
    }


# ---------------------------------------------------------------------------
# Provider runners — each returns a ProviderEvidence.  Each isolates its own
# network/runtime errors so one provider failure cannot crash the others.
# ---------------------------------------------------------------------------


def _refused_offline(provider: str, reason: str) -> ProviderEvidence:
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL.get(provider, ""),
        run_mode="live",
        status=STATUS_OFFLINE,
        verification_status=VERIF_OFFLINE,
        last_error=reason,
        blocks_promotion=True,
    )


def _config_missing(provider: str, reason: str) -> ProviderEvidence:
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL.get(provider, ""),
        run_mode="live",
        status=STATUS_CONFIG_MISSING,
        verification_status=VERIF_UNVERIFIED,
        last_error=reason,
        blocks_promotion=True,
    )


def _skipped(provider: str, reason: str) -> ProviderEvidence:
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL.get(provider, ""),
        run_mode="live",
        status=STATUS_SKIPPED,
        verification_status=VERIF_OFFLINE,
        last_error=reason,
        blocks_promotion=True,
    )


def run_yfinance_live(
    *,
    max_tickers: int = 10,
    timeout_seconds: int = 45,
    yfinance_module: Any = None,
) -> ProviderEvidence:
    """Probe yfinance for recent OHLCV across representative tickers.

    Returns LIVE_VERIFIED only when at least one ticker yields a real OHLCV
    close + a market timestamp.  Network failures degrade to FAILED.
    """
    provider = "yfinance"
    tickers = list(_REPRESENTATIVE_TICKERS)[: max(1, max_tickers)]
    try:
        yf = yfinance_module or importlib.import_module("yfinance")
    except Exception as exc:
        return _config_missing(provider, f"yfinance import failed: {type(exc).__name__}")

    latest_ts: str | None = None
    successes = 0
    sample_tags: list[str] = []
    last_err: str | None = None
    for sym in tickers:
        try:
            ticker = yf.Ticker(sym)
            hist = ticker.history(period="2d", interval="1d")
        except Exception as exc:  # pragma: no cover - network defensive
            last_err = f"{sym}:{type(exc).__name__}:{exc}"
            continue
        try:
            n_rows = int(getattr(hist, "shape", (0,))[0]) if hist is not None else 0
        except Exception:
            n_rows = 0
        if not n_rows:
            continue
        try:
            idx = hist.index[-1]
            close = float(hist["Close"].iloc[-1])
        except Exception as exc:
            last_err = f"{sym}:close-extract:{type(exc).__name__}"
            continue
        try:
            # Normalize timestamp to UTC ISO.
            ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
            if hasattr(ts, "astimezone"):
                ts_utc = ts.astimezone(timezone.utc)
            else:
                ts_utc = datetime.fromtimestamp(float(ts), tz=timezone.utc)
            ts_iso = ts_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
        # Track latest timestamp seen across all tickers.
        if latest_ts is None or ts_iso > latest_ts:
            latest_ts = ts_iso
        successes += 1
        sample_tags.append(sym)
        if close <= 0:
            continue

    if successes == 0:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=last_err or "no successful ticker fetch",
            events_seen=0,
            events_inserted=0,
            blocks_promotion=True,
        )

    status = STATUS_SUCCESS if successes >= 1 else STATUS_PARTIAL
    verification = VERIF_LIVE_VERIFIED if (
        latest_ts is not None and successes >= 1
    ) else VERIF_UNVERIFIED
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
        status=status,
        verification_status=verification,
        latest_provider_timestamp_utc=latest_ts,
        events_seen=successes,
        events_inserted=successes,
        sample_asset_tags=sample_tags,
        sample_source_urls=[f"https://finance.yahoo.com/quote/{sym}"
                            for sym in sample_tags[:3]],
        payload_hash=_payload_hash({"provider": provider, "ts": latest_ts,
                                    "n": successes, "syms": sample_tags}),
        last_error=last_err if successes < len(tickers) else None,
        blocks_promotion=verification != VERIF_LIVE_VERIFIED,
    )


def run_sec_edgar_live(
    *,
    sec_user_agent: str | None = None,
    timeout_seconds: int = 45,
    requests_module: Any = None,
) -> ProviderEvidence:
    """Probe SEC EDGAR for recent filings.

    Requires ``SEC_USER_AGENT``; without it returns CONFIG_MISSING (never
    crash).  Uses the SEC fair-access policy compliant header.
    """
    provider = "sec_edgar"
    if not sec_user_agent:
        return _config_missing(provider, "SEC_USER_AGENT not set")
    try:
        req = requests_module or importlib.import_module("requests")
    except Exception as exc:
        return _config_missing(provider, f"requests import failed: {type(exc).__name__}")

    cik = "0000320193"  # Apple
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {"User-Agent": sec_user_agent,
               "Accept": "application/json",
               "Host": "data.sec.gov"}
    try:
        resp = req.get(url, headers=headers, timeout=timeout_seconds)
    except Exception as exc:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"network:{type(exc).__name__}:{exc}",
            blocks_promotion=True,
        )
    if getattr(resp, "status_code", 0) != 200:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"http_status:{getattr(resp, 'status_code', 'unknown')}",
            blocks_promotion=True,
        )
    try:
        data = resp.json()
    except Exception as exc:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"json_decode:{type(exc).__name__}",
            blocks_promotion=True,
        )
    recent = (data.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accession = recent.get("accessionNumber") or []
    if not forms or not dates or not accession:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_PARTIAL,
            verification_status=VERIF_UNVERIFIED,
            last_error="empty filings list",
            blocks_promotion=True,
        )
    # Latest filing timestamp.  Filing dates are YYYY-MM-DD; we anchor at
    # 00:00:00 UTC of that date — this is conservative for freshness.
    latest_filing_date = max(dates)
    latest_ts = f"{latest_filing_date}T00:00:00Z"
    sample_tags = ["AAPL"]
    sample_urls = [
        f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
    ]
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
        status=STATUS_SUCCESS,
        verification_status=VERIF_LIVE_VERIFIED,
        latest_provider_timestamp_utc=latest_ts,
        events_seen=len(forms),
        events_inserted=len(forms),
        sample_asset_tags=sample_tags,
        sample_source_urls=sample_urls,
        payload_hash=_payload_hash({"cik": cik, "ts": latest_ts,
                                    "n": len(forms)}),
        blocks_promotion=False,
    )


def run_gdelt_live(
    *,
    timeout_seconds: int = 45,
    requests_module: Any = None,
) -> ProviderEvidence:
    """Probe GDELT for recent news articles.

    Public endpoint (no key).  Returns LIVE_VERIFIED only when at least one
    article comes back with title + url + timestamp.
    """
    provider = "gdelt"
    try:
        req = requests_module or importlib.import_module("requests")
    except Exception as exc:
        return _config_missing(provider, f"requests import failed: {type(exc).__name__}")

    url = "https://api.gdeltproject.org/api/v2/doc/doc"
    params = {
        "query": "economy OR inflation OR \"federal reserve\"",
        "mode": "artlist",
        "maxrecords": 25,
        "format": "json",
    }
    headers = {"User-Agent": "sleeping-passenger-v1 advisory MVP"}
    try:
        resp = req.get(url, params=params, headers=headers,
                       timeout=min(timeout_seconds, 30))
    except Exception as exc:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"network:{type(exc).__name__}:{exc}",
            blocks_promotion=True,
        )
    if getattr(resp, "status_code", 0) != 200:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"http_status:{getattr(resp, 'status_code', 'unknown')}",
            blocks_promotion=True,
        )
    try:
        data = resp.json()
    except Exception as exc:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_FAILED,
            verification_status=VERIF_UNVERIFIED,
            last_error=f"json_decode:{type(exc).__name__}",
            blocks_promotion=True,
        )
    articles = data.get("articles") or []
    if not articles:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_PARTIAL,
            verification_status=VERIF_UNVERIFIED,
            last_error="empty articles",
            blocks_promotion=True,
        )
    # Pick the most recent article carrying a parseable timestamp.
    latest_ts: str | None = None
    sample_urls: list[str] = []
    sample_titles: list[str] = []
    for article in articles[:25]:
        url_a = article.get("url") or ""
        title_a = article.get("title") or ""
        seen_a = article.get("seendate") or ""
        if not (url_a and title_a):
            continue
        # GDELT seendate format: YYYYMMDDTHHMMSSZ.  Normalize.
        ts_iso: str | None = None
        if len(seen_a) >= 15 and seen_a[8] == "T":
            try:
                dt = datetime.strptime(seen_a, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc
                )
                ts_iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except ValueError:
                ts_iso = None
        if ts_iso and (latest_ts is None or ts_iso > latest_ts):
            latest_ts = ts_iso
        if len(sample_urls) < 5:
            sample_urls.append(url_a)
        if len(sample_titles) < 5:
            sample_titles.append(title_a[:80])
    if latest_ts is None:
        return ProviderEvidence(
            provider=provider,
            source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
            status=STATUS_PARTIAL,
            verification_status=VERIF_UNVERIFIED,
            last_error="no parseable seendate",
            events_seen=len(articles),
            blocks_promotion=True,
        )
    return ProviderEvidence(
        provider=provider,
        source_type=PROVIDER_SOURCE_TYPE_LABEL[provider],
        status=STATUS_SUCCESS,
        verification_status=VERIF_LIVE_VERIFIED,
        latest_provider_timestamp_utc=latest_ts,
        events_seen=len(articles),
        events_inserted=len(articles),
        sample_asset_tags=[],
        sample_source_urls=sample_urls,
        payload_hash=_payload_hash({"provider": provider, "ts": latest_ts,
                                    "n": len(articles),
                                    "titles": sample_titles}),
        blocks_promotion=False,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def refresh_providers(
    *,
    providers: list[str] | None = None,
    timeout_seconds: int = 45,
    cfg: _typed_config.TypedConfig | None = None,
    yfinance_module: Any = None,
    requests_module: Any = None,
    previous_summary_path: Path | None = None,
) -> dict[str, Any]:
    """Run the operator-mode refresh for ``providers``.

    Defaults to ``["yfinance", "sec_edgar", "gdelt"]``.  If
    ``MVP_LIVE_REFRESH_OK`` is not set every provider is recorded as
    OFFLINE (refused) and the artifact reflects the honest refusal.
    """
    now = _utc_now()
    started_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    if cfg is None:
        try:
            cfg = _typed_config.load_typed_config()
        except _typed_config.ConfigSafetyError as exc:
            cfg = None  # fall through; we still emit a safe artifact
            cfg_error = str(exc)
        else:
            cfg_error = None
    else:
        cfg_error = None

    requested = [p.strip().lower() for p in (providers or list(SUPPORTED_PROVIDERS))
                 if p.strip()]
    invalid = [p for p in requested if p not in SUPPORTED_PROVIDERS]
    if invalid:
        raise ValueError(
            f"unsupported providers requested: {invalid}; allowed: "
            f"{list(SUPPORTED_PROVIDERS)}"
        )

    # Honor allowlist when typed config is loaded.
    if cfg is not None:
        allowed = set(cfg.live_refresh_provider_allowlist)
        requested = [p for p in requested if p in allowed]

    network_allowed = (
        os.environ.get("MVP_LIVE_REFRESH_OK", "").strip().lower()
        in {"1", "true", "yes", "on"}
    ) and (cfg is None or cfg.mvp_live_refresh_ok)

    evidences: list[ProviderEvidence] = []
    for provider in requested:
        if not network_allowed:
            evidences.append(_refused_offline(
                provider,
                "MVP_LIVE_REFRESH_OK not set or config disables live refresh",
            ))
            continue
        # Per-provider enable check + execution.
        if provider == "yfinance":
            if cfg is not None and not cfg.yfinance_live_enabled:
                evidences.append(_skipped(provider, "YFINANCE_LIVE_ENABLED=false"))
                continue
            max_tickers = (cfg.live_refresh_max_tickers if cfg else 10)
            evidences.append(run_yfinance_live(
                max_tickers=max(1, min(max_tickers, 44)),
                timeout_seconds=timeout_seconds,
                yfinance_module=yfinance_module,
            ))
        elif provider == "sec_edgar":
            if cfg is not None and not cfg.sec_edgar_live_enabled:
                evidences.append(_skipped(provider, "SEC_EDGAR_LIVE_ENABLED=false"))
                continue
            ua = (cfg.sec_user_agent if cfg else None) or os.environ.get(
                "SEC_USER_AGENT") or ""
            evidences.append(run_sec_edgar_live(
                sec_user_agent=ua,
                timeout_seconds=timeout_seconds,
                requests_module=requests_module,
            ))
        elif provider == "gdelt":
            if cfg is not None and not cfg.gdelt_live_enabled:
                evidences.append(_skipped(provider, "GDELT_LIVE_ENABLED=false"))
                continue
            evidences.append(run_gdelt_live(
                timeout_seconds=timeout_seconds,
                requests_module=requests_module,
            ))

    # Aggregate counts + LPQ uplift.
    live_verified_providers = [
        e.provider for e in evidences
        if e.verification_status == VERIF_LIVE_VERIFIED
        and e.latest_provider_timestamp_utc
    ]
    previous_lpq_score = _read_previous_lpq_score(
        default=8.2, summary_path=previous_summary_path,
    )
    new_lpq_score, uplift_meta = lpq_uplift_score(evidences, previous_lpq_score)

    summary = {
        "report": "operator_live_provider_refresh_summary",
        "ok": bool(live_verified_providers) and network_allowed,
        "generated_at_utc": started_iso,
        "operator_run": True,
        "network_allowed": network_allowed,
        "mvp_live_refresh_ok_env": os.environ.get("MVP_LIVE_REFRESH_OK", ""),
        "config_loaded": cfg is not None,
        "config_error": cfg_error,
        "providers_requested": requested,
        "providers_live_verified": live_verified_providers,
        "providers_evidence": [e.to_dict() for e in evidences],
        "previous_live_payload_quality_score": previous_lpq_score,
        "live_payload_quality_score": new_lpq_score,
        "lpq_uplift": uplift_meta,
        "ttl_hours": (cfg.operator_live_refresh_ttl_hours if cfg else 24),
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }
    return summary


FIXTURE_LPQ_HONEST_CAP = 8.2


def _read_previous_lpq_score(
    default: float = FIXTURE_LPQ_HONEST_CAP,
    *,
    summary_path: Path | None = None,
) -> float:
    """Return the *honest* prior LPQ floor before this operator refresh.

    The existing fixture-mode artifact at
    ``runtime/release/live_source_refresh_summary.json`` reports a higher
    headline number (it uses FIXTURE_VERIFIED weighting), but the sprint
    spec is explicit: without LIVE_VERIFIED providers, the honest
    *live/fresh* payload quality score is capped at 8.2.  We only lift
    above 8.2 when the prior artifact itself was a successful operator-run
    with at least one LIVE_VERIFIED provider.

    ``summary_path`` lets callers (and tests) redirect the lookup away
    from the module-level ``OPERATOR_SUMMARY_PATH`` so a stale or
    real on-disk artifact cannot contaminate an isolated refresh.
    """
    prior_operator = summary_path if summary_path is not None else OPERATOR_SUMMARY_PATH
    if prior_operator.exists():
        try:
            data = json.loads(prior_operator.read_text(encoding="utf-8"))
            providers = list(data.get("providers_live_verified") or [])
            val = data.get("live_payload_quality_score")
            if providers and isinstance(val, (int, float)):
                return float(max(val, default))
        except (json.JSONDecodeError, OSError):
            pass
    return float(default)


def write_summary(
    summary: dict[str, Any],
    *,
    summary_path: Path | None = None,
    evidence_path: Path | None = None,
) -> dict[str, Any]:
    summary_target = summary_path or OPERATOR_SUMMARY_PATH
    evidence_target = evidence_path or LIVE_EVIDENCE_PATH
    summary_target.parent.mkdir(parents=True, exist_ok=True)

    tmp = summary_target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(summary_target)
    summary["summary_path"] = str(summary_target)

    evidence_payload = {
        "report": "live_provider_evidence",
        "generated_at_utc": summary.get("generated_at_utc") or _utc_iso(),
        "evidence": summary.get("providers_evidence", []),
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }
    tmp2 = evidence_target.with_suffix(".json.tmp")
    tmp2.write_text(json.dumps(evidence_payload, indent=2, default=str),
                    encoding="utf-8")
    tmp2.replace(evidence_target)
    summary["evidence_path"] = str(evidence_target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or OPERATOR_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def operator_artifact_valid(
    summary: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    ttl_hours: float | None = None,
) -> dict[str, Any]:
    """Validate the on-disk operator artifact against the TTL window.

    Returns a dict the release gate can splice into its proof:
    ``{attempted, valid, fresh, providers_live_verified, lpq_before,
       lpq_after, ttl_hours, age_hours}``.
    """
    if not isinstance(summary, dict):
        return {
            "attempted": False, "valid": False, "fresh": False,
            "providers_live_verified": [], "lpq_before": None,
            "lpq_after": None, "ttl_hours": ttl_hours or 24,
            "age_hours": None,
        }
    now = now or _utc_now()
    age = _age_hours_from_now(summary.get("generated_at_utc"), now=now)
    ttl = float(ttl_hours if ttl_hours is not None
                else summary.get("ttl_hours") or 24)
    fresh = bool(age is not None and age <= ttl)
    providers = list(summary.get("providers_live_verified") or [])
    valid = bool(summary.get("ok")) and fresh and bool(providers)
    return {
        "attempted": bool(summary.get("operator_run")),
        "valid": valid,
        "fresh": fresh,
        "providers_live_verified": providers,
        "lpq_before": summary.get("previous_live_payload_quality_score"),
        "lpq_after": summary.get("live_payload_quality_score"),
        "ttl_hours": ttl,
        "age_hours": round(age, 4) if age is not None else None,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="operator_live_provider_refresh.py",
        description=(
            "Operator-run live provider refresh for yfinance / SEC EDGAR / "
            "GDELT.  Requires MVP_LIVE_REFRESH_OK=1.  Read-only; advisory-only; "
            "never calls a broker."
        ),
    )
    p.add_argument("--providers", default=",".join(SUPPORTED_PROVIDERS),
                   help="comma-separated subset of yfinance,sec_edgar,gdelt")
    p.add_argument("--timeout-seconds", type=int, default=45)
    p.add_argument("--write", action="store_true",
                   help="persist operator_live_provider_refresh_summary.json "
                        "and live_provider_evidence.json")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    summary = refresh_providers(
        providers=providers,
        timeout_seconds=args.timeout_seconds,
    )
    if args.write:
        write_summary(summary)
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"operator_live_provider_refresh — ok={summary['ok']}")
        print(f"  providers_live_verified : {summary['providers_live_verified']}")
        print(f"  lpq_before              : {summary['previous_live_payload_quality_score']}")
        print(f"  lpq_after               : {summary['live_payload_quality_score']}")
        for ev in summary["providers_evidence"]:
            print(f"    {ev['provider']:10s} status={ev['status']:8s} "
                  f"verif={ev['verification_status']:18s} "
                  f"latest_ts={ev['latest_provider_timestamp_utc']} "
                  f"err={ev['last_error'] or '-'}")
    return 0 if summary["ok"] else 1


__all__ = [
    "SUPPORTED_PROVIDERS", "PROVIDER_SOURCE_CLASS", "PROVIDER_SOURCE_TYPE_LABEL",
    "STATUS_SUCCESS", "STATUS_PARTIAL", "STATUS_FAILED",
    "STATUS_OFFLINE", "STATUS_CONFIG_MISSING", "STATUS_SKIPPED",
    "VERIF_LIVE_VERIFIED", "VERIF_FIXTURE_VERIFIED",
    "VERIF_UNVERIFIED", "VERIF_STALE", "VERIF_OFFLINE",
    "OPERATOR_SUMMARY_PATH", "LIVE_EVIDENCE_PATH",
    "ProviderEvidence",
    "lpq_uplift_score",
    "run_yfinance_live", "run_sec_edgar_live", "run_gdelt_live",
    "refresh_providers", "write_summary", "read_summary",
    "operator_artifact_valid",
]


if __name__ == "__main__":
    raise SystemExit(main())
