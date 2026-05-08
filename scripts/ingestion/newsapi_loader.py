"""
NewsAPI read-only loader — Phase 2 Global Signal Fabric.

Requires NEWS_API_KEY env var. Skips cleanly if missing.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_NEWSAPI_BASE = "https://newsapi.org/v2/everything"
_TIMEOUT = 15
_DEFAULT_QUERY = "markets economy finance"
_DEFAULT_MAX = 20


class NewsAPILoader(BaseSourceLoader):
    source_name = "newsapi"
    requires_key = True

    def __init__(
        self,
        query: str = _DEFAULT_QUERY,
        max_articles: int = _DEFAULT_MAX,
        language: str = "en",
        timeout: int = _TIMEOUT,
        base_url: str = _NEWSAPI_BASE,
    ) -> None:
        self._query = query
        self._max = max_articles
        self._language = language
        self._timeout = timeout
        self._base_url = base_url

    def fetch(self) -> LoaderResult:
        """Fetch news articles from NewsAPI (read-only). Requires NEWS_API_KEY."""
        api_key = self._require_env_key("NEWS_API_KEY")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        params = {
            "q": self._query,
            "language": self._language,
            "pageSize": self._max,
            "apiKey": api_key,
        }
        try:
            resp = requests.get(self._base_url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"NewsAPI unreachable: {exc}") from exc

        articles = data.get("articles", []) if isinstance(data, dict) else []
        records = []
        for art in articles:
            if not isinstance(art, dict):
                continue
            rec = {
                "title": art.get("title", ""),
                "description": art.get("description", ""),
                "url": art.get("url", ""),
                "published_at": art.get("publishedAt", ""),
                "source_name": (art.get("source") or {}).get("name", ""),
                "source": "newsapi",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
