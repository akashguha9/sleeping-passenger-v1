"""RBI/SEBI placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class RBISEBILoader(PlaceholderLoader):
    source_name = "rbi_sebi"
    source_type = "regulator_disclosure"
    jurisdiction = "IN"
    required_env = ()
