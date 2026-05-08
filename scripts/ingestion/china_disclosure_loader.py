"""China SSE/SZSE/CNINFO/HKEX placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class ChinaDisclosureLoader(PlaceholderLoader):
    source_name = "china_disclosure"
    source_type = "official_filing"
    jurisdiction = "CN"
    required_env = ()
