"""
GDELT read-only loader — Phase 2 Global Signal Fabric.

Uses the public GDELT GKG / event API. No authentication required.

Retry strategy:
1. Primary query at short timeout (8 s)
2. On 429 → return RATE_LIMITED immediately (no retry)
3. On timeout → try a simpler fallback query at reduced timeout (6 s)
4. On second failure → return TIMEOUT
Total budget: ~18 s maximum, never hangs 40+ s
"""
from __future__ import annotations

import time

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_PRIMARY_TIMEOUT = 8
_FALLBACK_TIMEOUT = 6
_RETRY_SLEEP = 1.0
_DEFAULT_MAX = 25

_DEFAULT_QUERY = (
    "economy OR inflation OR \"interest rate\" OR \"federal reserve\" "
    "OR recession OR \"stock market\" OR bitcoin OR tariff"
)
_FALLBACK_QUERY = "economy OR inflation"

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
    ) -> None:
        self._query = query
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url
        self._fallback_timeout = fallback_timeout

    def _fetch_once(
        self,
        requests_mod: any,
        query: str,
        timeout: int,
    ) -> tuple[list[dict], str | None]:
        """
        Single fetch attempt. Returns (articles, error_tag_or_None).
        error_tag is one of: RATE_LIMITED, TIMEOUT, HTTP_ERROR, or None (success).
        """
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": self._max,
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
            return [], f"HTTP_ERROR:{exc}"

        if resp.status_code == 429:
            return [], "RATE_LIMITED"
        try:
            resp.raise_for_status()
        except Exception as exc:
            return [], f"HTTP_ERROR:{exc}"

        try:
            data = resp.json()
        except Exception:
            return [], "HTTP_ERROR:invalid JSON"

        articles = data.get("articles", []) if isinstance(data, dict) else []
        return articles, None

    def fetch(self) -> LoaderResult:
        """Fetch recent GDELT articles matching query (read-only)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        # Attempt 1: primary query
        articles, err = self._fetch_once(requests, self._query, self._timeout)

        if err == "RATE_LIMITED":
            raise SkipLoader("[RATE_LIMITED] GDELT API returned 429 Too Many Requests — retry later")

        if err is not None:
            # Attempt 2: simpler fallback query
            time.sleep(_RETRY_SLEEP)
            articles, err2 = self._fetch_once(requests, _FALLBACK_QUERY, self._fallback_timeout)
            if err2 == "RATE_LIMITED":
                raise SkipLoader("[RATE_LIMITED] GDELT API returned 429 Too Many Requests — retry later")
            if err2 is not None:
                if "TIMEOUT" in (err, err2 or ""):
                    raise SkipLoader(
                        f"[TIMEOUT] GDELT API timed out after {self._timeout + self._fallback_timeout}s"
                    )
                raise SkipLoader(f"GDELT API unreachable: {err2 or err}")

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
