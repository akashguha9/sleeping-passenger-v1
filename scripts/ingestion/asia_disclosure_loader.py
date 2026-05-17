"""
Asia Disclosure unified read-only loader — Phase C.8.

Ingests public regulatory disclosures and exchange announcements from:
  - SSE   (China, Shanghai):  placeholder — no stable public JSON API without scraping
  - SZSE  (China, Shenzhen):  placeholder — no stable public JSON API without scraping
  - HKEX  (Hong Kong):        placeholder — no stable public JSON API without browser auth
  - TDnet (Japan):            placeholder — no stable public JSON API
  - SGX   (Singapore):        placeholder — requires API key registration
  - DART  (Korea):            placeholder — requires API key registration

This source complements global_filings by providing a dedicated Asia/China disclosure
ingestion layer with jurisdiction-specific normalization and filtering.

No API key required for currently-active providers. All outputs are ADVISORY_ONLY.
Failures on individual providers are tolerated; raises SkipLoader only when every
selected active provider fails or no active providers exist.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader
except ModuleNotFoundError:
    from ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader  # type: ignore[no-redef]

_DEFAULT_MAX_ITEMS = 50
_DEFAULT_TIMEOUT = 15

# Canonical Asia Disclosure country list — the source of truth for the
# "Asia Disclosure" tab/section inside Live Signals.
#
# India is intentionally **excluded** here because India is tracked
# separately via ``scripts.ingestion.india_loader`` /
# ``india_nse_bse_loader`` / ``rbi_sebi_loader`` and surfaces under the
# dedicated "India" source family.  Listing India twice would double-
# count its disclosure flow.
#
# Status semantics:
#   "Active" = country is in scope for the Asia Disclosure tab.  The
#              underlying adapter remains ``adapter_status=planned`` in
#              ``scripts.live_source_registry`` until a real integration
#              exists, which is correct and honest.  Status here is
#              tab/country-list configuration, not source-health.
#
# ``disclosure_source`` and ``source_url`` are intentionally left blank
# for countries without a verified, key-free disclosure endpoint we can
# actually call.  No fake URLs are introduced.  When a real integration
# is added (e.g. SGX for Singapore, DART for Korea), update the row in
# place — do not maintain duplicate copies elsewhere.
ASIA_DISCLOSURE_COUNTRIES: tuple[str, ...] = (
    "China",
    "Japan",
    "Russia",
    "South Korea",
    "Turkey",
    "Indonesia",
    "Saudi Arabia",
    "Taiwan",
    "Israel",
    "Singapore",
    "United Arab Emirates",
)

_ASIA_DISCLOSURE_COUNTRY_ROWS: tuple[dict[str, str], ...] = (
    {"country": "China", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Japan", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Russia", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "South Korea", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Turkey", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Indonesia", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Saudi Arabia", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Taiwan", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Israel", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "Singapore", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
    {"country": "United Arab Emirates", "disclosure_source": "", "source_url": "", "status": "Active", "notes": ""},
)


def get_asia_disclosure_countries() -> list[str]:
    """Return the canonical Asia Disclosure country list (India excluded)."""
    return list(ASIA_DISCLOSURE_COUNTRIES)


def get_asia_disclosure_country_rows() -> list[dict[str, str]]:
    """Return tabular rows for the Asia Disclosure tab.

    Columns: country, disclosure_source, source_url, status, notes.
    Each row is a fresh dict so callers may mutate without affecting the
    canonical tuple.  India is intentionally absent — see module docstring.
    """
    return [dict(row) for row in _ASIA_DISCLOSURE_COUNTRY_ROWS]

_PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "sse": {
        "jurisdiction": "CN",
        "exchange_or_regulator": "SSE",
        "disclosure_type": "company_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "Shanghai Stock Exchange — no stable public JSON API without scraping",
    },
    "szse": {
        "jurisdiction": "CN",
        "exchange_or_regulator": "SZSE",
        "disclosure_type": "company_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "Shenzhen Stock Exchange — no stable public JSON API without scraping",
    },
    "hkex": {
        "jurisdiction": "HK",
        "exchange_or_regulator": "HKEX",
        "disclosure_type": "regulatory_disclosure",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "Hong Kong Exchanges — no stable public JSON API without browser auth",
    },
    "tdnet": {
        "jurisdiction": "JP",
        "exchange_or_regulator": "TDnet",
        "disclosure_type": "timely_disclosure",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "Japan TDnet — no stable public JSON API",
    },
    "sgx": {
        "jurisdiction": "SG",
        "exchange_or_regulator": "SGX",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "params": {},
        "requires_key": True,
        "key_env": "SGX_API_KEY",
        "active": False,
        "note": "Singapore Exchange — requires API key registration",
    },
    "dart": {
        "jurisdiction": "KR",
        "exchange_or_regulator": "DART",
        "disclosure_type": "regulatory_filing",
        "url": None,
        "params": {},
        "requires_key": True,
        "key_env": "DART_API_KEY",
        "active": False,
        "note": "Korea DART — requires API key registration",
    },
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ADF-Phase2/1.0; research-only)",
    "Accept": "application/json",
}


class AsiaDisclosureLoader(BaseSourceLoader):
    """Unified Asia disclosure source: SSE/SZSE/HKEX/TDnet/SGX/DART (all placeholder)."""

    source_name = "asia_disclosure"
    requires_key = False

    def __init__(
        self,
        providers: list[str] | None = None,
        query: str | None = None,
        jurisdiction: str | None = None,
        max_items: int = _DEFAULT_MAX_ITEMS,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._providers = providers
        self._query = (query or "").strip().lower() or None
        self._jurisdiction = (jurisdiction or "").strip().upper() or None
        self._max_items = max_items
        self._timeout = timeout

    def _select_providers(self) -> list[str]:
        """Return provider names to attempt, honoring filters."""
        all_names = list(_PROVIDER_CONFIGS.keys())
        if self._providers:
            return [p for p in self._providers if p in _PROVIDER_CONFIGS]
        if self._jurisdiction:
            return [
                name
                for name, conf in _PROVIDER_CONFIGS.items()
                if conf["jurisdiction"] == self._jurisdiction
            ]
        return all_names

    def _normalize_raw_item(
        self,
        item: dict[str, Any],
        conf: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        """Map a raw provider API item to the canonical asia_disclosure shape."""
        issuer_name = str(
            item.get("issuer_name")
            or item.get("company_name")
            or item.get("name")
            or item.get("issuer_short_name")
            or ""
        )
        ticker = str(
            item.get("ticker")
            or item.get("stock_code")
            or item.get("symbol")
            or item.get("issuer_code")
            or ""
        )
        title = str(
            item.get("title")
            or item.get("headline")
            or item.get("subject")
            or item.get("description")
            or ""
        )
        summary = str(
            item.get("summary")
            or item.get("description")
            or item.get("title")
            or item.get("headline")
            or ""
        )
        url = str(
            item.get("url")
            or item.get("link")
            or item.get("pdf_url")
            or ""
        )
        published_at = str(
            item.get("published_at")
            or item.get("date")
            or item.get("document_date")
            or item.get("timestamp")
            or ""
        )
        language = str(item.get("language") or "")
        return {
            "issuer_name": issuer_name,
            "ticker_or_identifier": ticker,
            "exchange_or_regulator": conf["exchange_or_regulator"],
            "jurisdiction": conf["jurisdiction"],
            "disclosure_type": conf["disclosure_type"],
            "published_at": published_at,
            "url": url,
            "title": title,
            "summary": summary,
            "provider": provider_name,
            "language": language,
            "raw_payload": dict(item),
        }

    def _fetch_active_provider(
        self,
        provider_name: str,
        conf: dict[str, Any],
        requests_mod: Any,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch from one active provider. Returns (records, error_or_None)."""
        url = conf["url"]
        params = dict(conf.get("params", {}))

        try:
            resp = requests_mod.get(
                url, params=params, headers=_HEADERS, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return [], f"{provider_name}: {type(exc).__name__}: {exc}"

        items = (
            data
            if isinstance(data, list)
            else data.get("data", [])
            if isinstance(data, dict)
            else []
        )

        records: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            rec = self._normalize_raw_item(item, conf, provider_name)
            if self._query:
                searchable = " ".join([
                    rec["issuer_name"],
                    rec["ticker_or_identifier"],
                    rec["title"],
                    rec["summary"],
                    rec["disclosure_type"],
                    rec["jurisdiction"],
                ]).lower()
                if self._query not in searchable:
                    continue
            self._stamp_record(rec)
            records.append(rec)
        return records, None

    def fetch(self) -> LoaderResult:
        """Fetch Asia disclosure records (read-only, no execution)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        selected = self._select_providers()
        if not selected:
            raise SkipLoader(
                "No matching Asia disclosure providers found for the given filter"
            )

        active_names = [p for p in selected if _PROVIDER_CONFIGS[p].get("active")]
        if not active_names:
            placeholder_notes = "; ".join(
                f"{p.upper()}: {_PROVIDER_CONFIGS[p].get('note', 'placeholder')}"
                for p in selected
                if p in _PROVIDER_CONFIGS
            )
            raise SkipLoader(
                "[PLACEHOLDER] Asia Disclosure not implemented yet — "
                "all configured providers (SSE, SZSE, HKEX, TDnet, SGX, DART) "
                "require auth/registration or scraping and are intentionally "
                "left as placeholders. No records are ever persisted in this "
                f"state. Details: {placeholder_notes}"
            )

        records: list[dict[str, Any]] = []
        errors: list[str] = []

        for provider_name in active_names:
            conf = _PROVIDER_CONFIGS[provider_name]
            if conf.get("requires_key") and conf.get("key_env"):
                key = os.environ.get(conf["key_env"], "").strip()
                if not key:
                    errors.append(
                        f"{provider_name}: missing env var {conf['key_env']!r}"
                    )
                    continue
            provider_records, error = self._fetch_active_provider(
                provider_name, conf, requests
            )
            if error:
                errors.append(error)
            else:
                records.extend(provider_records)

        if not records and errors:
            raise SkipLoader(
                f"All active Asia disclosure providers unreachable: {'; '.join(errors)}"
            )

        return LoaderResult(
            source_name=self.source_name,
            records=records[: self._max_items],
        )
