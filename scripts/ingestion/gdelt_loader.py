"""
GDELT read-only loader — Phase 2 Global Signal Fabric.

Uses the public GDELT GKG / event API. No authentication required.

Retry strategy (rate-limit/offline-safe)
---------------------------------------
1. Primary query at short timeout (default 6s)
2. On 429 → return RATE_LIMITED immediately (no retry)
3. On timeout or HTTP error → try a simpler fallback query at reduced timeout (4s)
   with a smaller maxrecords value
4. On second failure → return TIMEOUT/HTTP_ERROR

Total worst-case budget: primary_timeout + 0.5s sleep + fallback_timeout
  → ~10.5s with defaults; never hangs 20+ s.

The fallback query keeps GDELT-stable DOC API params:
  - query (very short)
  - mode=artlist
  - maxrecords (small)
  - format=json
"""
from __future__ import annotations

import time

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_PRIMARY_TIMEOUT = 6
_FALLBACK_TIMEOUT = 4
_RETRY_SLEEP = 0.5
_DEFAULT_MAX = 25
_FALLBACK_MAX = 10

_DEFAULT_QUERY = (
    "economy OR inflation OR \"interest rate\" OR \"federal reserve\" "
    "OR recession OR \"stock market\" OR bitcoin OR tariff"
)
_FALLBACK_QUERY = "economy"

_USER_AGENT = "GSF-Pipeline/1.0 research-only (non-commercial)"


class GDELTLoader(BaseSourceLoader):
    source_name = "gdelt"
    requires_key = False

    def __init__(
        self,
        query: str = _DEFAULT_QUERY,
        max_records: int = _DEFAULT_MAX,
        timeout: int = _PRIMARY_TIMEOUT,
        base_url: str = _GDELT_DOC_API,
        fallback_timeout: int = _FALLBACK_TIMEOUT,
        fallback_query: str = _FALLBACK_QUERY,
        fallback_max_records: int = _FALLBACK_MAX,
    ) -> None:
        self._query = query
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url
        self._fallback_timeout = fallback_timeout
        self._fallback_query = fallback_query
        self._fallback_max = fallback_max_records

    def _fetch_once(
        self,
        requests_mod: any,
        query: str,
        timeout: int,
        max_records: int,
    ) -> tuple[list[dict], str | None]:
        """
        Single fetch attempt. Returns (articles, error_tag_or_None).
        error_tag is one of: RATE_LIMITED, TIMEOUT, HTTP_ERROR:..., or None (success).
        """
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": max_records,
            "format": "json",
        }
        headers = {"User-Agent": _USER_AGENT}
        try:
            resp = requests_mod.get(
                self._base_url, params=params, headers=headers, timeout=timeout
            )
        except requests_mod.exceptions.Timeout:
            return [], "TIMEOUT"
        except Exception as exc:
            return [], f"HTTP_ERROR:{type(exc).__name__}"

        if getattr(resp, "status_code", None) == 429:
            return [], "RATE_LIMITED"
        try:
            resp.raise_for_status()
        except Exception as exc:
            return [], f"HTTP_ERROR:{type(exc).__name__}"

        try:
            data = resp.json()
        except Exception:
            return [], "HTTP_ERROR:invalid_json"

        articles = data.get("articles", []) if isinstance(data, dict) else []
        return articles, None

    def fetch(self) -> LoaderResult:
        """Fetch recent GDELT articles matching query (read-only)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        # Attempt 1: primary query
        articles, err = self._fetch_once(
            requests, self._query, self._timeout, self._max
        )

        if err == "RATE_LIMITED":
            raise SkipLoader(
                "[RATE_LIMITED] GDELT API returned 429 Too Many Requests — retry later"
            )

        if err is not None:
            # Attempt 2: simpler fallback query with smaller maxrecords
            time.sleep(_RETRY_SLEEP)
            articles, err2 = self._fetch_once(
                requests,
                self._fallback_query,
                self._fallback_timeout,
                self._fallback_max,
            )
            if err2 == "RATE_LIMITED":
                raise SkipLoader(
                    "[RATE_LIMITED] GDELT API returned 429 Too Many Requests — retry later"
                )
            if err2 is not None:
                if "TIMEOUT" in (err, err2):
                    raise SkipLoader(
                        f"[TIMEOUT] GDELT API timed out after "
                        f"{self._timeout + self._fallback_timeout}s "
                        f"(primary={err}, fallback={err2})"
                    )
                raise SkipLoader(
                    f"GDELT API unreachable: primary={err}, fallback={err2}"
                )

        records = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            rec = {
                "url": art.get("url", ""),
                "title": art.get("title", ""),
                "seendate": art.get("seendate", ""),
                "domain": art.get("domain", ""),
                "language": art.get("language", ""),
                "sourcecountry": art.get("sourcecountry", ""),
                "source": "gdelt",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
