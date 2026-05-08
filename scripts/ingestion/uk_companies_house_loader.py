"""UK Companies House placeholder loader (read-only)."""
from __future__ import annotations

from scripts.ingestion._placeholder import PlaceholderLoader


class UKCompaniesHouseLoader(PlaceholderLoader):
    source_name = "uk_companies_house"
    source_type = "official_filing"
    jurisdiction = "UK"
    required_env = ("UK_COMPANIES_HOUSE_KEY",)
