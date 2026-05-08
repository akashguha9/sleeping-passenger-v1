"""Grok / xAI interpretation placeholder loader (read-only).

Skips cleanly without GROK_API_KEY. This is interpretation only — it never
issues trade actions and inherits the ADVISORY_ONLY guardrails.
"""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class GrokInterpreter(PlaceholderLoader):
    source_name = "grok"
    source_type = "interpretation"
    required_env = ("GROK_API_KEY",)
