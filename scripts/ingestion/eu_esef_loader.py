"""EU ESEF placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class EUESEFLoader(PlaceholderLoader):
    source_name = "eu_esef"
    source_type = "official_filing"
    jurisdiction = "EU"
    required_env = ()
