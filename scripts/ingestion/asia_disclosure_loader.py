"""
Asia Disclosure unified read-only loader — Phase C.8 + public-page sprint.

This loader fans out to per-country sub-sources and aggregates their
read-only metadata into the canonical Asia Disclosure stream.

Sub-source status (May 2026):
  - EDINET (Japan):        official API, real fetch when EDINET_API_KEY or
                           JAPAN_EDINET_API_KEY is configured.
  - OpenDART (Korea):      official API, real fetch when OPENDART_API_KEY or
                           KOREA_DART_API_KEY is configured.
  - SSE / SZSE / HKEX / TDnet / SGX / DART (legacy):
                           still placeholders — no stable public JSON API
                           without scraping or paid registration.  Kept as
                           inactive entries so country/jurisdiction filters
                           remain meaningful.
  - Public-page providers (sgx_public, mops, hkexnews, cninfo, tadawul,
    adx, dfm, kap, idx, tase_magna, russia):
                           registered with verified landing URLs and a
                           generic public-page fetch/parse path.  Each
                           ships ``active=False`` + ``source_class=
                           planned_public_page`` until a per-source parser
                           is verified against live responses.  Inactive
                           public-page providers are excluded from stale
                           accounting and never produce fake rows.  The
                           parser path is exercised in tests by flipping
                           ``active`` via a patched ``_PROVIDER_CONFIGS``.

Safety
------
* No execution.  No order placement.  No wallet signing.
* Read-only metadata only — list endpoints, not document bodies.
* Every record stamps the advisory-only safety contract via
  ``BaseSourceLoader._stamp_record``.
* No API key value is ever logged, printed, or returned in records.
"""
from __future__ import annotations

import json
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
    {
        "country": "China",
        "disclosure_source": "CNINFO",
        "source_url": "http://www.cninfo.com.cn/new/index",
        "status": "Active",
        "notes": "Cninfo public disclosure index (planned public-page parser).",
    },
    {
        "country": "Japan",
        "disclosure_source": "EDINET",
        "source_url": "https://disclosure2.edinet-fsa.go.jp/",
        "status": "Active",
        "notes": "EDINET official API wired (Subscription-Key required).",
    },
    {
        "country": "Russia",
        "disclosure_source": "",
        "source_url": "",
        "status": "Active",
        "notes": "Russia disclosure ingestion planned pending safe public source verification.",
    },
    {
        "country": "South Korea",
        "disclosure_source": "OpenDART",
        "source_url": "https://opendart.fss.or.kr/",
        "status": "Active",
        "notes": "OpenDART official API wired (crtfc_key required).",
    },
    {
        "country": "Turkey",
        "disclosure_source": "KAP",
        "source_url": "https://www.kap.org.tr/en/",
        "status": "Active",
        "notes": "KAP public disclosure platform (planned public-page parser).",
    },
    {
        "country": "Indonesia",
        "disclosure_source": "IDX",
        "source_url": "https://www.idx.co.id/en/news/news/",
        "status": "Active",
        "notes": "IDX news / company announcements (planned public-page parser).",
    },
    {
        "country": "Saudi Arabia",
        "disclosure_source": "Saudi Exchange (Tadawul)",
        "source_url": "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/issuer-news",
        "status": "Active",
        "notes": "Tadawul issuer news (planned public-page parser).",
    },
    {
        "country": "Taiwan",
        "disclosure_source": "MOPS",
        "source_url": "https://mops.twse.com.tw/mops/web/index",
        "status": "Active",
        "notes": "Taiwan MOPS public disclosure search (planned public-page parser).",
    },
    {
        "country": "Israel",
        "disclosure_source": "TASE Maya / MAGNA",
        "source_url": "https://maya.tase.co.il/",
        "status": "Active",
        "notes": "TASE Maya / ISA MAGNA disclosures (planned public-page parser).",
    },
    {
        "country": "Singapore",
        "disclosure_source": "SGX",
        "source_url": "https://www.sgx.com/securities/company-announcements",
        "status": "Active",
        "notes": "SGX company announcements (planned public-page parser).",
    },
    {
        "country": "United Arab Emirates",
        "disclosure_source": "ADX / DFM",
        "source_url": "https://www.adx.ae/English/Pages/NewsAndEvents/CompaniesDisclosure.aspx",
        "status": "Active",
        "notes": "Abu Dhabi Securities Exchange + Dubai Financial Market (planned public-page parsers).",
    },
)


def get_asia_disclosure_countries() -> list[str]:
    """Return the canonical Asia Disclosure country list (India excluded)."""
    return list(ASIA_DISCLOSURE_COUNTRIES)


def get_asia_disclosure_country_rows() -> list[dict[str, str]]:
    """Return tabular rows for the Asia Disclosure tab.

    Columns: country, disclosure_source, source_url, status, notes.
    Each row is a fresh dict so callers may mutate without affecting the
    canonical tuple.  India is intentionally absent.
    """
    return [dict(row) for row in _ASIA_DISCLOSURE_COUNTRY_ROWS]


# Sub-source env var families.  Primary wins if both are set.
_EDINET_ENV_PRIMARY = "EDINET_API_KEY"
_EDINET_ENV_ALIASES: tuple[str, ...] = ("JAPAN_EDINET_API_KEY",)
_OPENDART_ENV_PRIMARY = "OPENDART_API_KEY"
_OPENDART_ENV_ALIASES: tuple[str, ...] = ("KOREA_DART_API_KEY",)


_PROVIDER_CONFIGS: dict[str, dict[str, Any]] = {
    "edinet": {
        "jurisdiction": "JP",
        "country": "Japan",
        "exchange_or_regulator": "EDINET",
        "disclosure_system": "EDINET",
        "disclosure_type": "edinet_filing",
        "url": "https://api.edinet-fsa.go.jp/api/v2/documents.json",
        "params": {"type": 2},
        "requires_key": True,
        "key_env": _EDINET_ENV_PRIMARY,
        "alt_key_envs": _EDINET_ENV_ALIASES,
        "active": True,
        "source_class": "official_api",
        "key_query_param": "Subscription-Key",
        "note": "Japan EDINET v2 documents list — read-only metadata.",
    },
    "opendart": {
        "jurisdiction": "KR",
        "country": "South Korea",
        "exchange_or_regulator": "OpenDART",
        "disclosure_system": "OpenDART",
        "disclosure_type": "opendart_filing",
        "url": "https://opendart.fss.or.kr/api/list.json",
        "params": {"page_no": "1", "page_count": "50"},
        "requires_key": True,
        "key_env": _OPENDART_ENV_PRIMARY,
        "alt_key_envs": _OPENDART_ENV_ALIASES,
        "active": True,
        "source_class": "official_api",
        "key_query_param": "crtfc_key",
        "note": "Korea OpenDART recent disclosure list — read-only metadata.",
    },
    # ---- Legacy placeholders (kept so jurisdiction filtering stays honest) ----
    "sse": {
        "jurisdiction": "CN",
        "country": "China",
        "exchange_or_regulator": "SSE",
        "disclosure_system": "SSE",
        "disclosure_type": "company_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": "Shanghai Stock Exchange — no stable public JSON API without scraping",
    },
    "szse": {
        "jurisdiction": "CN",
        "country": "China",
        "exchange_or_regulator": "SZSE",
        "disclosure_system": "SZSE",
        "disclosure_type": "company_announcement",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": "Shenzhen Stock Exchange — no stable public JSON API without scraping",
    },
    "hkex": {
        "jurisdiction": "HK",
        "country": "Hong Kong",
        "exchange_or_regulator": "HKEX",
        "disclosure_system": "HKEX",
        "disclosure_type": "regulatory_disclosure",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": "Hong Kong Exchanges — no stable public JSON API without browser auth",
    },
    "tdnet": {
        "jurisdiction": "JP",
        "country": "Japan",
        "exchange_or_regulator": "TDnet",
        "disclosure_system": "TDnet",
        "disclosure_type": "timely_disclosure",
        "url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": "Japan TDnet — no stable public JSON API",
    },
    "sgx": {
        "jurisdiction": "SG",
        "country": "Singapore",
        "exchange_or_regulator": "SGX",
        "disclosure_system": "SGX",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "params": {},
        "requires_key": True,
        "key_env": "SGX_API_KEY",
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": "Singapore Exchange — requires API key registration",
    },
    "dart": {
        "jurisdiction": "KR",
        "country": "South Korea",
        "exchange_or_regulator": "DART",
        "disclosure_system": "DART",
        "disclosure_type": "regulatory_filing",
        "url": None,
        "params": {},
        "requires_key": True,
        "key_env": "DART_API_KEY",
        "alt_key_envs": (),
        "active": False,
        "source_class": "placeholder",
        "note": (
            "Legacy DART placeholder — superseded by the live 'opendart' "
            "provider which uses OPENDART_API_KEY."
        ),
    },
    # ------------------------------------------------------------------
    # Public-page providers (no API key, no login).  All ship inactive
    # with ``source_class='planned_public_page'`` until a per-source
    # parser is verified against live responses.  When activated, the
    # loader uses the generic public-page fetch path
    # (``_fetch_public_page_provider``) and per-source response shape
    # extractors.  Every entry below ships a real, well-known landing
    # URL — no fabricated endpoints, no example.com placeholders.
    # ------------------------------------------------------------------
    "sgx_public": {
        "jurisdiction": "SG",
        "country": "Singapore",
        "exchange_or_regulator": "SGX",
        "disclosure_system": "SGX Company Announcements",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://www.sgx.com/securities/company-announcements",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "Singapore Exchange company announcements — public listing page; "
            "parser not yet wired (planned_public_page)."
        ),
    },
    "mops": {
        "jurisdiction": "TW",
        "country": "Taiwan",
        "exchange_or_regulator": "MOPS",
        "disclosure_system": "Taiwan MOPS (Market Observation Post System)",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://mops.twse.com.tw/mops/web/index",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "zh-TW",
        "note": (
            "Taiwan MOPS public disclosure search — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "hkexnews": {
        "jurisdiction": "HK",
        "country": "Hong Kong",
        "exchange_or_regulator": "HKEXnews",
        "disclosure_system": "HKEXnews",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://www.hkexnews.hk/",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "HKEXnews public listing — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "cninfo": {
        "jurisdiction": "CN",
        "country": "China",
        "exchange_or_regulator": "CNINFO",
        "disclosure_system": "CNINFO",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "http://www.cninfo.com.cn/new/index",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "zh-CN",
        "note": (
            "Cninfo (China) public disclosure index — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "tadawul": {
        "jurisdiction": "SA",
        "country": "Saudi Arabia",
        "exchange_or_regulator": "Saudi Exchange (Tadawul)",
        "disclosure_system": "Tadawul Issuer News",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": (
            "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/issuer-news"
        ),
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "Saudi Exchange (Tadawul) issuer news — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "adx": {
        "jurisdiction": "AE",
        "country": "United Arab Emirates",
        "exchange_or_regulator": "ADX",
        "disclosure_system": "Abu Dhabi Securities Exchange Disclosures",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": (
            "https://www.adx.ae/English/Pages/NewsAndEvents/CompaniesDisclosure.aspx"
        ),
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "Abu Dhabi Securities Exchange disclosures — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "dfm": {
        "jurisdiction": "AE",
        "country": "United Arab Emirates",
        "exchange_or_regulator": "DFM",
        "disclosure_system": "Dubai Financial Market Disclosures",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://www.dfm.ae/issuers/listed-securities/disclosures",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "Dubai Financial Market disclosures — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "kap": {
        "jurisdiction": "TR",
        "country": "Turkey",
        "exchange_or_regulator": "KAP",
        "disclosure_system": "KAP Public Disclosure Platform",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://www.kap.org.tr/en/",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "tr",
        "note": (
            "KAP Turkey public disclosure platform — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "idx": {
        "jurisdiction": "ID",
        "country": "Indonesia",
        "exchange_or_regulator": "IDX",
        "disclosure_system": "Indonesia Stock Exchange News",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": "https://www.idx.co.id/en/news/news/",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "en",
        "note": (
            "Indonesia Stock Exchange (IDX) news / disclosures — parser not "
            "yet wired (planned_public_page)."
        ),
    },
    "tase_magna": {
        "jurisdiction": "IL",
        "country": "Israel",
        "exchange_or_regulator": "TASE / MAGNA",
        "disclosure_system": "TASE Maya / ISA MAGNA",
        "disclosure_type": "regulatory_disclosure",
        "url": None,
        "landing_url": "https://maya.tase.co.il/",
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "he",
        "note": (
            "Israel TASE Maya / MAGNA disclosures — parser not yet wired "
            "(planned_public_page)."
        ),
    },
    "russia": {
        "jurisdiction": "RU",
        "country": "Russia",
        "exchange_or_regulator": "MOEX/CDR",
        "disclosure_system": "Russia disclosure (planned)",
        "disclosure_type": "exchange_announcement",
        "url": None,
        "landing_url": None,
        "params": {},
        "requires_key": False,
        "key_env": None,
        "alt_key_envs": (),
        "active": False,
        "source_class": "planned_public_page",
        "fetch_kind": "html",
        "language": "ru",
        "note": (
            "Russia disclosure ingestion is PLANNED pending verification of a "
            "safe, public, non-login source.  No URL is registered until "
            "such a source is verified."
        ),
    },
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ADF-Phase2/1.0; research-only)",
    "Accept": "application/json",
}

# Slightly different headers for public-page HTML fetches — we explicitly
# say we accept HTML so caching proxies don't 406 us.  We never claim a
# real browser; we identify as an advisory research bot.
_PUBLIC_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ADF-PublicPage/1.0; research-only)",
    "Accept": "text/html,application/xhtml+xml,application/xml,application/rss+xml,application/json;q=0.8,*/*;q=0.5",
    "Accept-Language": "en;q=0.9",
}


# Sub-source status taxonomy used to summarise per-provider outcomes.
_SUB_OK = "ok"
_SUB_OK_EMPTY = "no_rows"
_SUB_MISSING_KEY = "optional_config_missing"
_SUB_RATE_LIMITED = "rate_limited"
_SUB_HTTP_ERROR = "http_error"
_SUB_UNREACHABLE = "unreachable"
_SUB_PARSE_ERROR = "parse_error"
_SUB_PLACEHOLDER = "placeholder"
_SUB_PLANNED_PUBLIC_PAGE = "planned_public_page"
_SUB_BLOCKED = "blocked"

# Sub-source-class labels.  ``official_api`` / ``placeholder`` already
# existed; ``public_page`` and ``planned_public_page`` are added here so
# the UI / health summary can render each correctly without inspecting
# the loader internals.
_SOURCE_CLASS_OFFICIAL_API = "official_api"
_SOURCE_CLASS_PLACEHOLDER = "placeholder"
_SOURCE_CLASS_PUBLIC_PAGE = "public_page"
_SOURCE_CLASS_PLANNED_PUBLIC_PAGE = "planned_public_page"

# Inactive source-class → sub-source status mapping.  Used when a provider
# is registered but ``active=False``; the parent skip path emits the
# matching sub-source status so the truth filter can distinguish
# "we plan to support this but haven't" from "we never will".
_INACTIVE_STATUS_BY_CLASS: dict[str, str] = {
    _SOURCE_CLASS_PLANNED_PUBLIC_PAGE: _SUB_PLANNED_PUBLIC_PAGE,
    _SOURCE_CLASS_PUBLIC_PAGE: _SUB_PLANNED_PUBLIC_PAGE,
    _SOURCE_CLASS_PLACEHOLDER: _SUB_PLACEHOLDER,
}

# Statuses that count as "informational, not stale" — these never count
# as a failure in the aggregate outcome and never produce fake rows.
_INFORMATIONAL_STATUSES: frozenset[str] = frozenset(
    {_SUB_MISSING_KEY, _SUB_PLACEHOLDER, _SUB_PLANNED_PUBLIC_PAGE}
)

# Default per-call cap for a public-page provider response.  Picked low
# so we never spam a public listing page.
_PUBLIC_PAGE_DEFAULT_MAX_ITEMS = 25


def _resolve_provider_key(conf: dict[str, Any]) -> str | None:
    """Return the first non-empty env value among primary + aliases.

    Never returns or logs the value to anywhere other than the requests
    layer.  Returns ``None`` if no usable key is configured.
    """
    primary = conf.get("key_env")
    if primary:
        v = os.environ.get(primary, "").strip()
        if v:
            return v
    for alias in conf.get("alt_key_envs", ()) or ():
        v = os.environ.get(alias, "").strip()
        if v:
            return v
    return None


def _summarise_subsource_status(
    sub_status: dict[str, dict[str, Any]],
    rows_total: int,
) -> str:
    """Build a compact, no-secret JSON-string summary embeddable in
    ``skip_reason`` / ``error_message`` so operators can see per-sub-source
    outcomes without parsing logs.
    """
    payload = {
        "rows_added_total": int(rows_total),
        "sub_sources_attempted": sorted(sub_status.keys()),
        "sub_sources_succeeded": sorted(
            n for n, s in sub_status.items() if s.get("status") == _SUB_OK
        ),
        "sub_sources_skipped": sorted(
            n
            for n, s in sub_status.items()
            if s.get("status")
            in {_SUB_MISSING_KEY, _SUB_PLACEHOLDER, _SUB_PLANNED_PUBLIC_PAGE}
        ),
        "sub_sources_planned_public_page": sorted(
            n
            for n, s in sub_status.items()
            if s.get("status") == _SUB_PLANNED_PUBLIC_PAGE
        ),
        "sub_sources_failed": sorted(
            n
            for n, s in sub_status.items()
            if s.get("status")
            in {
                _SUB_RATE_LIMITED,
                _SUB_HTTP_ERROR,
                _SUB_UNREACHABLE,
                _SUB_PARSE_ERROR,
                _SUB_BLOCKED,
            }
        ),
        "per_source": {
            n: {
                "status": s.get("status", "unknown"),
                "reason": s.get("reason", "")[:160],
                "rows": int(s.get("rows", 0) or 0),
            }
            for n, s in sub_status.items()
        },
    }
    try:
        return json.dumps(payload, sort_keys=True)
    except Exception:
        return str(payload)


def _normalize_edinet_doc(
    doc: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    """Map one EDINET ``results[]`` entry to canonical asia_disclosure shape."""
    doc_id = str(doc.get("docID") or doc.get("docId") or "")
    filer_name = str(doc.get("filerName") or "")
    title_raw = str(doc.get("docDescription") or "")
    submit_dt = str(doc.get("submitDateTime") or doc.get("periodEnd") or "")
    sec_code = str(doc.get("secCode") or "")
    # EDINET does not publish a stable public document-list URL we can
    # construct without exposing the API key — leave blank rather than
    # invent one.
    return {
        "issuer_name": filer_name,
        "ticker_or_identifier": sec_code or doc_id,
        "exchange_or_regulator": conf["exchange_or_regulator"],
        "jurisdiction": conf["jurisdiction"],
        "country": conf["country"],
        "disclosure_system": conf["disclosure_system"],
        "disclosure_type": conf["disclosure_type"],
        "doc_id": doc_id,
        "published_at": submit_dt,
        "url": "",
        "title": title_raw or filer_name or doc_id or "EDINET Filing",
        "summary": title_raw,
        "provider": "edinet",
        "source_class": conf["source_class"],
        "language": "ja",
        "raw_payload": dict(doc),
    }


def _normalize_opendart_item(
    item: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    """Map one OpenDART ``list[]`` item to canonical asia_disclosure shape."""
    corp_name = str(item.get("corp_name") or "")
    report_nm = str(item.get("report_nm") or "")
    rcept_no = str(item.get("rcept_no") or "")
    rcept_dt = str(item.get("rcept_dt") or "")
    stock_code = str(item.get("stock_code") or "")
    # OpenDART exposes a stable public viewer URL keyed on rcept_no.
    url = (
        f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
        if rcept_no
        else ""
    )
    return {
        "issuer_name": corp_name,
        "ticker_or_identifier": stock_code or rcept_no,
        "exchange_or_regulator": conf["exchange_or_regulator"],
        "jurisdiction": conf["jurisdiction"],
        "country": conf["country"],
        "disclosure_system": conf["disclosure_system"],
        "disclosure_type": conf["disclosure_type"],
        "doc_id": rcept_no,
        "receipt_no": rcept_no,
        "published_at": rcept_dt,
        "url": url,
        "title": report_nm or corp_name or rcept_no or "OpenDART Filing",
        "summary": report_nm,
        "provider": "opendart",
        "source_class": conf["source_class"],
        "language": "ko",
        "raw_payload": dict(item),
    }


def _normalize_public_page_item(
    item: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    """Map one extracted public-page list item to the canonical shape.

    Designed to be schema-agnostic so a per-provider extractor can emit
    its raw row using common field aliases (issuer_name / company_name /
    name, title / headline / subject, published_at / date / pub_date,
    url / link, ticker / stock_code / symbol).  Missing fields fall back
    to safe defaults — we never invent a URL or fabricate an ID.
    """
    issuer_name = str(
        item.get("issuer_name")
        or item.get("company_name")
        or item.get("issuer")
        or item.get("name")
        or ""
    )
    ticker = str(
        item.get("ticker")
        or item.get("ticker_or_identifier")
        or item.get("stock_code")
        or item.get("symbol")
        or item.get("code")
        or ""
    )
    title_raw = str(
        item.get("title")
        or item.get("headline")
        or item.get("subject")
        or item.get("report_name")
        or ""
    )
    summary = str(
        item.get("summary")
        or item.get("description")
        or item.get("snippet")
        or title_raw
        or ""
    )
    published_at = str(
        item.get("published_at")
        or item.get("date")
        or item.get("pub_date")
        or item.get("filing_date")
        or item.get("timestamp")
        or ""
    )
    url = str(
        item.get("url")
        or item.get("link")
        or item.get("doc_url")
        or ""
    )
    doc_id = str(
        item.get("doc_id")
        or item.get("announcement_id")
        or item.get("filing_id")
        or item.get("id")
        or ""
    )
    return {
        "issuer_name": issuer_name,
        "ticker_or_identifier": ticker,
        "exchange_or_regulator": conf.get("exchange_or_regulator", ""),
        "jurisdiction": conf.get("jurisdiction", ""),
        "country": conf.get("country", ""),
        "disclosure_system": conf.get("disclosure_system", ""),
        "disclosure_type": conf.get("disclosure_type", "exchange_announcement"),
        "doc_id": doc_id,
        "published_at": published_at,
        "url": url,
        "title": (
            title_raw
            or (issuer_name + (" — " + ticker if ticker else ""))
            or "Public-page Disclosure"
        ),
        "summary": summary,
        "provider": str(item.get("provider") or ""),  # set by caller
        "source_class": conf.get("source_class", _SOURCE_CLASS_PUBLIC_PAGE),
        "language": str(conf.get("language") or ""),
        "raw_payload": dict(item),
    }


def _extract_public_page_items(
    provider_name: str,
    data: Any,
    raw_text: str,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Best-effort extractor for a public-page response.

    Tries the following shapes in order:
      1. Parsed JSON with a top-level ``list`` / ``items`` / ``data`` /
         ``results`` array of dicts.
      2. Parsed JSON as a top-level list of dicts.
      3. RSS / Atom XML containing ``<item>`` or ``<entry>`` elements.

    HTML scraping is deliberately NOT performed here — the constraint
    "do not scrape aggressively" applies and a regex-based HTML scrape
    too easily produces fake-looking rows.  When no extractor can read
    the response, returns ``(None, _SUB_PARSE_ERROR)`` so the caller
    surfaces an honest parse_error rather than falling through to a
    fabricated empty list.
    """
    # 1) JSON dict with a list under a known key.
    if isinstance(data, dict):
        for key in ("list", "items", "data", "results", "announcements", "rows"):
            value = data.get(key)
            if isinstance(value, list):
                items = [r for r in value if isinstance(r, dict)]
                return items, None
    # 2) JSON list at top level.
    if isinstance(data, list):
        items = [r for r in data if isinstance(r, dict)]
        return items, None

    # 3) RSS / Atom XML.
    text = (raw_text or "").strip()
    if text.startswith("<?xml") or "<rss" in text[:200].lower() or "<feed" in text[:200].lower():
        try:
            import xml.etree.ElementTree as ET

            root = ET.fromstring(text)
        except Exception:
            return None, _SUB_PARSE_ERROR
        items: list[dict[str, Any]] = []
        # RSS 2.0 channels/items use no namespace; Atom uses
        # ``http://www.w3.org/2005/Atom``.  We handle both, ignoring
        # namespaces by matching on the local tag name.
        for node in root.iter():
            tag = node.tag.split("}", 1)[-1].lower()
            if tag not in {"item", "entry"}:
                continue
            row: dict[str, Any] = {}
            for child in node:
                ctag = child.tag.split("}", 1)[-1].lower()
                value = (child.text or "").strip()
                if ctag == "title":
                    row["title"] = value
                elif ctag == "link":
                    href = child.attrib.get("href") or value
                    if href:
                        row["url"] = href
                elif ctag in {"pubdate", "published", "updated"}:
                    row["published_at"] = value
                elif ctag in {"description", "summary", "content"}:
                    row["summary"] = value
                elif ctag in {"guid", "id"}:
                    row["doc_id"] = value
                elif ctag in {"author", "dc:creator", "creator"}:
                    row.setdefault("issuer_name", value)
            if row:
                items.append(row)
        return items, None

    return None, _SUB_PARSE_ERROR


_PROVIDER_NORMALIZERS: dict[str, Any] = {
    "edinet": _normalize_edinet_doc,
    "opendart": _normalize_opendart_item,
}


class AsiaDisclosureLoader(BaseSourceLoader):
    """Unified Asia disclosure source: EDINET + OpenDART live; rest placeholder."""

    source_name = "asia_disclosure"
    # Parent flag stays False because individual sub-sources own their key
    # requirements.  Missing keys for both sub-sources produces a
    # SkipLoader with a structured ``optional_config_missing`` reason.
    requires_key = False

    def __init__(
        self,
        providers: list[str] | None = None,
        query: str | None = None,
        jurisdiction: str | None = None,
        max_items: int = _DEFAULT_MAX_ITEMS,
        timeout: int = _DEFAULT_TIMEOUT,
        date: str | None = None,
    ) -> None:
        self._providers = providers
        self._query = (query or "").strip().lower() or None
        self._jurisdiction = (jurisdiction or "").strip().upper() or None
        self._max_items = max_items
        self._timeout = timeout
        self._date = (date or "").strip() or None

    # ------------------------------------------------------------------
    # Provider selection
    # ------------------------------------------------------------------

    def _select_providers(self) -> list[str]:
        """Return provider names to attempt, honoring filters."""
        all_names = list(_PROVIDER_CONFIGS.keys())
        if self._providers is not None:
            return [p for p in self._providers if p in _PROVIDER_CONFIGS]
        if self._jurisdiction:
            return [
                name
                for name, conf in _PROVIDER_CONFIGS.items()
                if conf["jurisdiction"] == self._jurisdiction
            ]
        return all_names

    # ------------------------------------------------------------------
    # Generic field normalizer (used for non-edinet/opendart active hits,
    # e.g. when tests patch a placeholder config into active state)
    # ------------------------------------------------------------------

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
            "country": conf.get("country", ""),
            "disclosure_system": conf.get("disclosure_system", ""),
            "disclosure_type": conf["disclosure_type"],
            "published_at": published_at,
            "url": url,
            "title": title,
            "summary": summary,
            "provider": provider_name,
            "source_class": conf.get("source_class", ""),
            "language": language,
            "raw_payload": dict(item),
        }

    # ------------------------------------------------------------------
    # Per-provider HTTP fetch
    # ------------------------------------------------------------------

    def _build_provider_params(
        self,
        provider_name: str,
        conf: dict[str, Any],
        api_key: str | None,
    ) -> dict[str, Any]:
        """Return the query params for ``provider_name`` including the key.

        The API key is included as a request parameter (per each provider's
        spec) but is NEVER logged or echoed back into any record.
        """
        params: dict[str, Any] = dict(conf.get("params", {}) or {})
        if provider_name == "edinet":
            params.setdefault("type", 2)
            # EDINET requires ``date=YYYY-MM-DD``.  When the operator did
            # not pin a date, use *today* — the API returns the filings
            # submitted on that calendar day in JST.
            if self._date:
                params["date"] = self._date
            else:
                from datetime import date as _date

                params["date"] = _date.today().isoformat()
            if api_key:
                params["Subscription-Key"] = api_key
        elif provider_name == "opendart":
            # OpenDART accepts ``bgn_de`` / ``end_de`` as YYYYMMDD.  Default
            # to the last 3 calendar days so the call returns a small,
            # rate-limit-friendly window.
            from datetime import date as _date, timedelta as _timedelta

            today = _date.today()
            bgn = today - _timedelta(days=3)
            params.setdefault("bgn_de", bgn.strftime("%Y%m%d"))
            params.setdefault("end_de", today.strftime("%Y%m%d"))
            params.setdefault("page_no", "1")
            params.setdefault("page_count", "50")
            if api_key:
                params["crtfc_key"] = api_key
        else:
            # Fallback for legacy/test-patched providers.
            key_param = conf.get("key_query_param")
            if key_param and api_key:
                params[key_param] = api_key
        return params

    def _items_from_response(
        self,
        provider_name: str,
        data: Any,
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Extract the records list from a parsed JSON response.

        Returns ``(items, error)``.  When ``items`` is ``None`` the
        ``error`` field is the sub-source status (``rate_limited``,
        ``http_error``, ``parse_error``, …).
        """
        if provider_name == "edinet":
            if not isinstance(data, dict):
                return None, _SUB_PARSE_ERROR
            metadata = data.get("metadata") or {}
            status = (
                str(metadata.get("status") or "").strip()
                if isinstance(metadata, dict)
                else ""
            )
            if status and status not in {"200", "ok", "OK", "Success"}:
                # EDINET returns HTTP 200 with embedded status codes for
                # auth / rate / format errors.  Treat 4xx-shaped codes as
                # http_error and 429-shaped as rate_limited.
                if status in {"429", "503"}:
                    return None, _SUB_RATE_LIMITED
                return None, _SUB_HTTP_ERROR
            results = data.get("results")
            if results is None:
                return [], None
            if not isinstance(results, list):
                return None, _SUB_PARSE_ERROR
            return [r for r in results if isinstance(r, dict)], None

        if provider_name == "opendart":
            if not isinstance(data, dict):
                return None, _SUB_PARSE_ERROR
            status = str(data.get("status") or "").strip()
            # OpenDART status codes:
            #   "000" — success
            #   "013" — no data (treat as ok-empty, not error)
            #   "020" — registered IP exceeded request limit (rate_limited)
            #   "021" — daily request count exceeded (rate_limited)
            #   "010" — registered IP not allowed (http_error)
            #   "011" — unauthorised (http_error)
            #   anything else — http_error
            if status == "013":
                return [], None
            if status in {"020", "021"}:
                return None, _SUB_RATE_LIMITED
            if status and status != "000":
                return None, _SUB_HTTP_ERROR
            items = data.get("list")
            if items is None:
                return [], None
            if not isinstance(items, list):
                return None, _SUB_PARSE_ERROR
            return [r for r in items if isinstance(r, dict)], None

        # Default behaviour for legacy/test-patched providers — accept either
        # a top-level list or a ``data`` field.
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("data", [])
        else:
            return None, _SUB_PARSE_ERROR
        if not isinstance(items, list):
            return None, _SUB_PARSE_ERROR
        return [r for r in items if isinstance(r, dict)], None

    def _fetch_active_provider(
        self,
        provider_name: str,
        conf: dict[str, Any],
        requests_mod: Any,
        api_key: str | None,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Fetch one active provider.

        Returns ``(records, status, reason)`` where ``status`` is one of
        the ``_SUB_*`` constants.  ``records`` is the normalized list
        (possibly empty) when ``status`` is ``ok`` or ``no_rows``.

        Public-page providers (``source_class == 'public_page'``) are
        dispatched to :meth:`_fetch_public_page_provider`; everything
        else uses the official-API JSON path below.
        """
        if str(conf.get("source_class") or "") == _SOURCE_CLASS_PUBLIC_PAGE:
            return self._fetch_public_page_provider(
                provider_name, conf, requests_mod
            )

        url = conf["url"]
        params = self._build_provider_params(provider_name, conf, api_key)

        try:
            resp = requests_mod.get(
                url, params=params, headers=_HEADERS, timeout=self._timeout
            )
        except Exception as exc:
            return [], _SUB_UNREACHABLE, f"{type(exc).__name__}: {exc}"

        status_code = getattr(resp, "status_code", None)
        if status_code == 429:
            return [], _SUB_RATE_LIMITED, "HTTP 429 rate_limited"
        try:
            resp.raise_for_status()
        except Exception as exc:
            return [], _SUB_HTTP_ERROR, f"{type(exc).__name__}: {exc}"

        try:
            data = resp.json()
        except Exception as exc:
            return [], _SUB_PARSE_ERROR, f"json_decode: {type(exc).__name__}: {exc}"

        raw_items, err = self._items_from_response(provider_name, data)
        if err is not None:
            reason_map = {
                _SUB_PARSE_ERROR: "response shape unrecognised",
                _SUB_HTTP_ERROR: "provider returned non-success status",
                _SUB_RATE_LIMITED: "provider rate limit exceeded",
            }
            return [], err, reason_map.get(err, err)

        normalizer = _PROVIDER_NORMALIZERS.get(provider_name)
        records: list[dict[str, Any]] = []
        for item in raw_items or []:
            try:
                if normalizer is not None:
                    rec = normalizer(item, conf)
                else:
                    rec = self._normalize_raw_item(item, conf, provider_name)
            except Exception as exc:
                return [], _SUB_PARSE_ERROR, f"normalize_error: {type(exc).__name__}: {exc}"
            if self._query:
                searchable = " ".join(
                    [
                        str(rec.get("issuer_name", "")),
                        str(rec.get("ticker_or_identifier", "")),
                        str(rec.get("title", "")),
                        str(rec.get("summary", "")),
                        str(rec.get("disclosure_type", "")),
                        str(rec.get("jurisdiction", "")),
                    ]
                ).lower()
                if self._query not in searchable:
                    continue
            self._stamp_record(rec)
            records.append(rec)

        if not records:
            return [], _SUB_OK_EMPTY, "provider returned 0 rows"
        return records, _SUB_OK, "ok"

    # ------------------------------------------------------------------
    # Public-page provider fetch (no API key, no login, low-volume)
    # ------------------------------------------------------------------

    def _fetch_public_page_provider(
        self,
        provider_name: str,
        conf: dict[str, Any],
        requests_mod: Any,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Fetch a public-page provider response (HTML / RSS / JSON).

        Returns ``(records, status, reason)`` like :meth:`_fetch_active_provider`.

        Safety guarantees:
          * No API key is sent — the provider declares ``requires_key=False``.
          * Request is GET-only with a low timeout.
          * Empty / unparseable responses return honest ``no_rows`` /
            ``parse_error`` statuses, never fabricated rows.
          * Per-item normalization passes through ``_stamp_record`` so
            every emitted row carries the advisory contract.
        """
        url = conf.get("url") or conf.get("landing_url")
        if not url:
            return (
                [],
                _SUB_PARSE_ERROR,
                "public_page provider has no fetchable url",
            )
        params: dict[str, Any] = dict(conf.get("params", {}) or {})

        try:
            resp = requests_mod.get(
                url,
                params=params,
                headers=_PUBLIC_PAGE_HEADERS,
                timeout=self._timeout,
            )
        except Exception as exc:
            return [], _SUB_UNREACHABLE, f"{type(exc).__name__}: {exc}"

        status_code = getattr(resp, "status_code", None)
        if status_code == 429:
            return [], _SUB_RATE_LIMITED, "HTTP 429 rate_limited"
        if status_code in {401, 403}:
            # 401/403 on a "public" page usually means anti-bot / WAF block.
            # Treat as blocked so the operator sees the truthful reason
            # rather than a generic HTTP error.
            return [], _SUB_BLOCKED, f"HTTP {status_code} blocked"
        try:
            resp.raise_for_status()
        except Exception as exc:
            return [], _SUB_HTTP_ERROR, f"{type(exc).__name__}: {exc}"

        raw_text = ""
        try:
            raw_text = resp.text or ""
        except Exception:
            raw_text = ""

        data: Any = None
        try:
            data = resp.json()
        except Exception:
            data = None

        raw_items, err = _extract_public_page_items(
            provider_name, data, raw_text
        )
        if err is not None:
            reason_map = {
                _SUB_PARSE_ERROR: "public-page response could not be parsed",
            }
            return [], err, reason_map.get(err, err)

        max_items = int(conf.get("max_items") or _PUBLIC_PAGE_DEFAULT_MAX_ITEMS)
        records: list[dict[str, Any]] = []
        for item in (raw_items or [])[:max_items]:
            try:
                rec = _normalize_public_page_item(item, conf)
            except Exception as exc:
                return [], _SUB_PARSE_ERROR, (
                    f"normalize_error: {type(exc).__name__}: {exc}"
                )
            rec["provider"] = provider_name
            if self._query:
                searchable = " ".join(
                    [
                        str(rec.get("issuer_name", "")),
                        str(rec.get("ticker_or_identifier", "")),
                        str(rec.get("title", "")),
                        str(rec.get("summary", "")),
                        str(rec.get("disclosure_type", "")),
                        str(rec.get("jurisdiction", "")),
                    ]
                ).lower()
                if self._query not in searchable:
                    continue
            self._stamp_record(rec)
            records.append(rec)

        if not records:
            return [], _SUB_OK_EMPTY, "public-page returned 0 rows"
        return records, _SUB_OK, "ok"

    # ------------------------------------------------------------------
    # Public fetch entry point
    # ------------------------------------------------------------------

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

        sub_status: dict[str, dict[str, Any]] = {}

        if not active_names:
            planned_only = True
            for p in selected:
                conf = _PROVIDER_CONFIGS.get(p, {})
                source_class = str(conf.get("source_class") or "")
                inactive_status = _INACTIVE_STATUS_BY_CLASS.get(
                    source_class, _SUB_PLACEHOLDER
                )
                sub_status[p] = {
                    "status": inactive_status,
                    "reason": str(conf.get("note") or inactive_status),
                    "rows": 0,
                }
                if inactive_status != _SUB_PLANNED_PUBLIC_PAGE:
                    planned_only = False
            summary = _summarise_subsource_status(sub_status, 0)
            if planned_only:
                raise SkipLoader(
                    "[PLANNED_PUBLIC_PAGE] Asia Disclosure public-page "
                    "providers not yet implemented; "
                    f"sub_source_status={summary}"
                )
            raise SkipLoader(
                "[PLACEHOLDER] Asia Disclosure sub-sources not configured/active; "
                f"sub_source_status={summary}"
            )

        records: list[dict[str, Any]] = []

        for provider_name in active_names:
            conf = _PROVIDER_CONFIGS[provider_name]
            api_key: str | None = None
            if conf.get("requires_key"):
                api_key = _resolve_provider_key(conf)
                if not api_key:
                    sub_status[provider_name] = {
                        "status": _SUB_MISSING_KEY,
                        "reason": f"missing env: {conf.get('key_env') or 'API_KEY'}"
                        + (
                            f" (aliases: {', '.join(conf.get('alt_key_envs', ()) or ())})"
                            if conf.get("alt_key_envs")
                            else ""
                        ),
                        "rows": 0,
                    }
                    continue

            provider_records, status, reason = self._fetch_active_provider(
                provider_name, conf, requests, api_key
            )
            sub_status[provider_name] = {
                "status": status,
                "reason": reason,
                "rows": len(provider_records),
            }
            if status == _SUB_OK:
                records.extend(provider_records)

        rows_total = len(records)
        summary = _summarise_subsource_status(sub_status, rows_total)

        # Decide aggregate outcome.
        statuses = {s["status"] for s in sub_status.values()}

        if rows_total > 0:
            # Partial success counts as success.  Records returned.
            return LoaderResult(
                source_name=self.source_name,
                records=records[: self._max_items],
            )

        if statuses and statuses.issubset(_INFORMATIONAL_STATUSES):
            # Distinguish all-missing-key (informational; "optional config
            # missing") from all-placeholder / planned_public_page
            # (informational; nothing to do until parsers wired or keys
            # supplied).  Missing-key wins so the operator sees the
            # actionable banner first.
            if _SUB_MISSING_KEY in statuses:
                raise SkipLoader(
                    "[OPTIONAL_CONFIG_MISSING] Asia Disclosure has no "
                    "configured sub-source keys (EDINET_API_KEY / "
                    f"OPENDART_API_KEY); sub_source_status={summary}"
                )
            if statuses == {_SUB_PLANNED_PUBLIC_PAGE}:
                raise SkipLoader(
                    "[PLANNED_PUBLIC_PAGE] Asia Disclosure public-page "
                    "providers not yet implemented; "
                    f"sub_source_status={summary}"
                )
            raise SkipLoader(
                "[PLACEHOLDER] Asia Disclosure sub-sources not configured/"
                f"active; sub_source_status={summary}"
            )

        if _SUB_RATE_LIMITED in statuses:
            raise SkipLoader(
                f"[RATE_LIMITED] Asia Disclosure provider hit rate limit; "
                f"sub_source_status={summary}"
            )

        if _SUB_BLOCKED in statuses:
            raise SkipLoader(
                f"[BLOCKED] Asia Disclosure public-page provider blocked; "
                f"sub_source_status={summary}"
            )

        if _SUB_HTTP_ERROR in statuses or _SUB_UNREACHABLE in statuses:
            raise SkipLoader(
                f"Asia Disclosure providers unreachable / HTTP error; "
                f"sub_source_status={summary}"
            )

        if _SUB_PARSE_ERROR in statuses:
            raise SkipLoader(
                f"[PARSE_ERROR] Asia Disclosure provider parse error; "
                f"sub_source_status={summary}"
            )

        # All providers returned a syntactically valid but empty response.
        # This is not a skip — it is an honest "no rows" outcome.  We keep
        # ``skipped=False`` so the runner records the attempt as a normal
        # ok-with-zero-rows event, and the per-sub-source summary is
        # available for diagnostics in skip_reason for the underlying
        # log_source_run row (when persisted).
        return LoaderResult(
            source_name=self.source_name,
            records=[],
            skipped=False,
            skip_reason=(
                f"[NO_ROWS] Asia Disclosure providers returned empty "
                f"responses; sub_source_status={summary}"
            ),
        )
