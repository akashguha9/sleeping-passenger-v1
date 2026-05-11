"""
GDELT read-only loader — Phase 2 Global Signal Fabric.

Uses the public GDELT GKG / event API. No authentication required.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_TIMEOUT = 15
_DEFAULT_QUERY = "market OR economy OR inflation"
_DEFAULT_MAX = 25


class GDELTLoader(BaseSourceLoader):
    source_name = "gdelt"
    requires_key = False

    def __init__(
        self,
        query: str = _DEFAULT_QUERY,
        max_records: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _GDELT_DOC_API,
    ) -> None:
        self._query = query
        self._max = max_records
        self._timeout = timeout
        self._base_url = base_url

    def fetch(self) -> LoaderResult:
        """Fetch recent GDELT articles matching query (read-only)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        params = {
            "query": self._query,
            "mode": "artlist",
            "maxrecords": self._max,
            "format": "json",
        }
        try:
            resp = requests.get(self._base_url, params=params, timeout=self._timeout)
            if resp.status_code == 429:
                raise SkipLoader(
                    f"[RATE_LIMITED] GDELT API returned 429 Too Many Requests — retry later"
                )
            resp.raise_for_status()
            data = resp.json()
        except SkipLoader:
            raise
        except requests.exceptions.Timeout:
            raise SkipLoader(
                f"[TIMEOUT] GDELT API timed out after {self._timeout}s"
            )
        except Exception as exc:
            raise SkipLoader(f"GDELT API unreachable: {exc}") from exc

        articles = data.get("articles", []) if isinstance(data, dict) else []
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
