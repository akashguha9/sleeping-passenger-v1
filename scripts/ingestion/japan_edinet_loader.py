"""Japan EDINET placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class JapanEDINETLoader(PlaceholderLoader):
    source_name = "japan_edinet"
    source_type = "official_filing"
    jurisdiction = "JP"
    required_env = ()
