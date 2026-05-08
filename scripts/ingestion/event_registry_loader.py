"""Event Registry placeholder loader (read-only). Skips without EVENT_REGISTRY_KEY."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class EventRegistryLoader(PlaceholderLoader):
    source_name = "event_registry"
    source_type = "news_event"
    required_env = ("EVENT_REGISTRY_KEY",)
