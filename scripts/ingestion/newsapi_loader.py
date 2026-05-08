"""NewsAPI placeholder loader (read-only). Skips cleanly without NEWSAPI_KEY."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class NewsAPILoader(PlaceholderLoader):
    source_name = "newsapi"
    source_type = "news_event"
    required_env = ("NEWSAPI_KEY",)
