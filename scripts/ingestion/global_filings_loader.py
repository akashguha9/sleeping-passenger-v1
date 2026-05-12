"""
Global Filings / Disclosure unified read-only loader — Phase C.7.

Ingests public regulatory disclosures and exchange announcements from:
  - SEC EFTS (USA): EDGAR full-text search — stable public JSON API, User-Agent required
  - ASX  (Australia): placeholder — endpoint returns 404, removed from active
  - HKEX (Hong Kong): placeholder — no stable public JSON API without browser
  - SGX  (Singapore): placeholder — requires API registration
  - UK FCA/RNS (UK):  placeholder — no stable public JSON API
  - ESMA (EU):        placeholder — complex XML API not implemented
  - SEDAR (Canada):   placeholder — no public JSON API
  - TDnet (Japan):    placeholder — no stable public JSON API

Provider notes
--------------
SEC EFTS is the only active provider. It uses the public EDGAR Full-Text Search
endpoint (efts.sec.gov) which requires the SEC_USER_AGENT env var as per the
SEC's fair-access policy.  No paid subscription needed.

No API key required for active providers (SEC_USER_AGENT is a user-agent string,
not a secret key). All outputs are ADVISORY_ONLY.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader
except ModuleNotFoundError:
    from ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader  # type: ignore[no-redef]

_DEFAULT_MAX_ITEMS = 50
_DEFAULT_TIMEOUT = 15

# EDGAR EFTS full-text search
_SEC_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_SEC_EFTS_FORMS = "8-K,10-K,10-Q"
_SEC_EFTS_QUERY = "earnings OR economy OR inflation OR revenue OR guidance OR outlook"

_PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "sec_efts": {
        "jurisdiction": "US",
        "exchange_or_regulator": "SEC/EDGAR",
        "disclosure_type": "sec_filing",
        "url": _SEC_EFTS_URL,
        "params": {
            "q": _SEC_EFTS_QUERY,
            "forms": _SEC_EFTS_FORMS,
            "dateRange": "custom",
        },
        "requires_key": True,
        "key_env": "SEC_USER_AGENT",
        "auth_header": "User-Agent",
        "active": True,
        "note": "SEC EDGAR full-text search — public, requires User-Agent per SEC fair-access policy",
    },
    "asx": {
        "jurisdiction": "AU",
        "exchange_or_regulator": "ASX",
        "disclosure_type": "company_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "ASX company announcements endpoint returns 404 — removed from active providers",
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
    "uk_rns": {
        "jurisdiction": "UK",
        "exchange_or_regulator": "FCA/LSE",
        "disclosure_type": "rns_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "UK FCA/RNS — no stable public JSON API",
    },
    "esma": {
        "jurisdiction": "EU",
        "exchange_or_regulator": "ESMA",
        "disclosure_type": "regulatory_disclosure",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "ESMA — complex XML API, not implemented",
    },
    "sedar": {
        "jurisdiction": "CA",
        "exchange_or_regulator": "SEDAR",
        "disclosure_type": "regulatory_filing",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "active": False,
        "note": "SEDAR+ — no public JSON API",
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
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GSF-Phase2/1.0; research-only)",
    "Accept": "application/json",
}


def _sec_efts_date_params() -> dict[str, str]:
    """Build startdt/enddt for recent 30-day window."""
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return {"startdt": start, "enddt": end}


class GlobalFilingsLoader(BaseSourceLoader):
    """Unified global disclosures source: SEC EFTS (active) + placeholder providers."""

    source_name = "global_filings"
    requires_key = False

    def __init__(
        self,
        providers: list[str] | None = None,
        query: str | None = None,
        region: str | None = None,
        max_items: int = _DEFAULT_MAX_ITEMS,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._providers = providers
        self._query = (query or "").strip().lower() or None
        self._region = (region or "").strip().upper() or None
        self._max_items = max_items
        self._timeout = timeout

    def _select_providers(self) -> list[str]:
        """Return provider names to attempt, honoring filters."""
        all_names = list(_PROVIDER_CONFIGS.keys())
        if self._providers is not None:
            return [p for p in self._providers if p in _PROVIDER_CONFIGS]
        if self._region:
            return [
                name
                for name, conf in _PROVIDER_CONFIGS.items()
                if conf["jurisdiction"] == self._region
            ]
        return all_names

    def _normalize_raw_item(
        self,
        item: dict[str, Any],
        conf: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        """Map a raw provider API item to the canonical global_filings shape."""
        issuer_name = str(
            item.get("issuer_short_name")
            or item.get("entity_name")
            or item.get("issuer_name")
            or item.get("company_name")
            or item.get("name")
            or ""
        )
        ticker = str(
            item.get("ticker")
            or item.get("issuer_code")
            or item.get("stock_code")
            or item.get("symbol")
            or ""
        )
        summary = str(
            item.get("description")
            or item.get("title")
            or item.get("headline")
            or item.get("subject")
            or item.get("form_type")
            or ""
        )
        url = str(
            item.get("url")
            or item.get("link")
            or item.get("pdf_url")
            or ""
        )
        published_at = str(
            item.get("file_date")
            or item.get("document_date")
            or item.get("date")
            or item.get("published_at")
            or item.get("timestamp")
            or ""
        )
        return {
            "issuer_name": issuer_name,
            "ticker_or_identifier": ticker,
            "exchange_or_regulator": conf["exchange_or_regulator"],
            "jurisdiction": conf["jurisdiction"],
            "disclosure_type": item.get("form_type") or conf["disclosure_type"],
            "published_at": published_at,
            "url": url,
            "summary": summary,
            "provider": provider_name,
            "raw_payload": dict(item),
        }

    def _fetch_sec_efts(
        self,
        conf: dict[str, Any],
        requests_mod: Any,
        user_agent: str,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch from EDGAR EFTS full-text search. Returns (records, error_or_None)."""
        params = dict(conf.get("params", {}))
        params.update(_sec_efts_date_params())

        headers = {**_HEADERS, "User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

        try:
            resp = requests_mod.get(
                conf["url"], params=params, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return [], f"sec_efts: {type(exc).__name__}: {str(exc)[:200]}"

        hits_outer = data.get("hits", {}) if isinstance(data, dict) else {}
        hits = hits_outer.get("hits", []) if isinstance(hits_outer, dict) else []
        if isinstance(hits_outer, list):
            hits = hits_outer

        records: list[dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            src = hit.get("_source", {}) if isinstance(hit, dict) else {}
            if not isinstance(src, dict):
                continue

            # Build a canonical item from EFTS _source fields
            display_names = src.get("display_names") or []
            entity = ""
            ticker = ""
            if display_names and isinstance(display_names, list):
                first = display_names[0] if display_names else {}
                if isinstance(first, dict):
                    entity = first.get("name", "")
                    ticker = first.get("ticker", "")

            # Fallback: entity_name at top level
            entity = entity or src.get("entity_name", "") or src.get("name", "")
            accession = src.get("accession_no", "") or src.get("_id", "")
            form = src.get("form_type", "") or src.get("file_form", "")
            file_date = src.get("file_date", "") or src.get("period_of_report", "")

            # Build EDGAR viewer URL from accession number
            edgar_url = ""
            if accession:
                clean_acc = accession.replace("-", "")
                edgar_url = (
                    f"https://www.sec.gov/Archives/edgar/data/{clean_acc[:10]}/"
                    f"{accession}.htm"
                )

            item = {
                "entity_name": entity,
                "ticker": ticker,
                "form_type": form,
                "file_date": file_date,
                "accession_no": accession,
                "url": edgar_url,
                "description": f"{form} — {entity}" if entity else form,
            }
            rec = self._normalize_raw_item(item, conf, "sec_efts")

            if self._query:
                searchable = " ".join([
                    rec["issuer_name"],
                    rec["ticker_or_identifier"],
                    rec["summary"],
                    rec["disclosure_type"],
                ]).lower()
                if self._query not in searchable:
                    continue

            self._stamp_record(rec)
            records.append(rec)

            if len(records) >= self._max_items:
                break

        return records, None

    def _fetch_active_provider(
        self,
        provider_name: str,
        conf: dict[str, Any],
        requests_mod: Any,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch from one active provider. Returns (records, error_or_None)."""
        # SEC EFTS needs special handling (User-Agent key goes in header, not params)
        if provider_name == "sec_efts":
            user_agent = os.environ.get(conf["key_env"], "").strip()
            if not user_agent:
                return [], f"sec_efts: missing env var {conf['key_env']!r}"
            return self._fetch_sec_efts(conf, requests_mod, user_agent)

        url = conf["url"]
        if not url:
            return [], f"{provider_name}: no URL configured"
        params = dict(conf.get("params", {}))
        if "count" in params:
            params["count"] = min(params["count"], self._max_items)

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
                    rec["summary"],
                    rec["disclosure_type"],
                ]).lower()
                if self._query not in searchable:
                    continue
            self._stamp_record(rec)
            records.append(rec)
        return records, None

    def fetch(self) -> LoaderResult:
        """Fetch global filings disclosures (read-only, no execution)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        selected = self._select_providers()
        if not selected:
            raise SkipLoader("No matching providers found for the given filter")

        active_names = [p for p in selected if _PROVIDER_CONFIGS[p].get("active")]
        if not active_names:
            raise SkipLoader(
                "[PLACEHOLDER] No active global filings providers in selection — "
                "all are placeholders. Only sec_efts is active (requires SEC_USER_AGENT)."
            )

        records: list[dict[str, Any]] = []
        errors: list[str] = []

        for provider_name in active_names:
            conf = _PROVIDER_CONFIGS[provider_name]
            provider_records, error = self._fetch_active_provider(
                provider_name, conf, requests
            )
            if error:
                errors.append(error)
            else:
                records.extend(provider_records)

        if not records and errors:
            raise SkipLoader(
                f"All active global filings providers unreachable: {'; '.join(errors)}"
            )

        return LoaderResult(
            source_name=self.source_name,
            records=records[: self._max_items],
        )
