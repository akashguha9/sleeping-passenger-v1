"""Singapore ACRA/SGX placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class SingaporeACRASGXLoader(PlaceholderLoader):
    source_name = "singapore_acra_sgx"
    source_type = "official_filing"
    jurisdiction = "SG"
    required_env = ()
