"""Solscan placeholder loader (read-only). Skips without SOLSCAN_API_KEY."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class SolscanLoader(PlaceholderLoader):
    source_name = "solscan"
    source_type = "onchain"
    required_env = ("SOLSCAN_API_KEY",)
