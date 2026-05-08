"""India NSE/BSE placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class IndiaNSEBSELoader(PlaceholderLoader):
    source_name = "india_nse_bse"
    source_type = "official_filing"
    jurisdiction = "IN"
    required_env = ()
