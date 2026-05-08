"""
Event Registry read-only loader — Phase 2 Global Signal Fabric.

Requires EVENT_REGISTRY_API_KEY env var. Skips cleanly if missing.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_ER_BASE = "https://eventregistry.org/api/v1/article/getArticles"
_TIMEOUT = 15
_DEFAULT_KEYWORDS = ["economy", "markets", "finance"]
_DEFAULT_MAX = 20


class EventRegistryLoader(BaseSourceLoader):
    source_name = "event_registry"
    requires_key = True

    def __init__(
        self,
        keywords: list[str] | None = None,
        max_articles: int = _DEFAULT_MAX,
        language: str = "eng",
        timeout: int = _TIMEOUT,
        base_url: str = _ER_BASE,
    ) -> None:
        self._keywords = keywords or _DEFAULT_KEYWORDS
        self._max = max_articles
        self._language = language
        self._timeout = timeout
        self._base_url = base_url

    def fetch(self) -> LoaderResult:
        """Fetch articles from Event Registry (read-only). Requires EVENT_REGISTRY_API_KEY."""
        api_key = self._require_env_key("EVENT_REGISTRY_API_KEY")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        payload = {
            "action": "getArticles",
            "keyword": self._keywords,
            "lang": self._language,
            "articlesCount": self._max,
            "resultType": "articles",
            "apiKey": api_key,
        }
        try:
            resp = requests.post(self._base_url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"Event Registry unreachable: {exc}") from exc

        articles = (
            data.get("articles", {}).get("results", [])
            if isinstance(data, dict)
            else []
        )
        records = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            rec = {
                "title": art.get("title", ""),
                "url": art.get("url", ""),
                "date_time": art.get("dateTime", ""),
                "source_name": (art.get("source") or {}).get("title", ""),
                "body": art.get("body", "")[:500],
                "source": "event_registry",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
