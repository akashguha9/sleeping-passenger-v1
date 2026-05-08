"""
UK Companies House read-only loader — Phase 2 Global Signal Fabric.

Requires UK_COMPANIES_HOUSE_API_KEY env var. Skips cleanly if missing.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_CH_BASE = "https://api.company-information.service.gov.uk"
_TIMEOUT = 15
_DEFAULT_MAX = 10


class UKCompaniesHouseLoader(BaseSourceLoader):
    source_name = "uk_companies_house"
    requires_key = True

    def __init__(
        self,
        company_number: str | None = None,
        search_query: str | None = None,
        max_results: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _CH_BASE,
    ) -> None:
        self._company_number = company_number
        self._search_query = search_query
        self._max = max_results
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch Companies House filing data (read-only). Requires UK_COMPANIES_HOUSE_API_KEY."""
        api_key = self._require_env_key("UK_COMPANIES_HOUSE_API_KEY")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        auth = (api_key, "")

        if self._company_number:
            url = f"{self._base_url}/company/{self._company_number}/filing-history"
            params = {"items_per_page": self._max, "category": "accounts"}
            try:
                resp = requests.get(
                    url, auth=auth, params=params, timeout=self._timeout
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise SkipLoader(f"Companies House API unreachable: {exc}") from exc

            items = data.get("items", []) if isinstance(data, dict) else []
            records = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                rec = {
                    "company_number": self._company_number,
                    "description": item.get("description", ""),
                    "date": item.get("date", ""),
                    "category": item.get("category", ""),
                    "type": item.get("type", ""),
                    "source": "uk_companies_house",
                }
                self._stamp_record(rec)
                records.append(rec)

        elif self._search_query:
            url = f"{self._base_url}/search/companies"
            params = {"q": self._search_query, "items_per_page": self._max}
            try:
                resp = requests.get(
                    url, auth=auth, params=params, timeout=self._timeout
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise SkipLoader(f"Companies House API unreachable: {exc}") from exc

            items = data.get("items", []) if isinstance(data, dict) else []
            records = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                rec = {
                    "company_name": item.get("title", ""),
                    "company_number": item.get("company_number", ""),
                    "company_status": item.get("company_status", ""),
                    "company_type": item.get("company_type", ""),
                    "date_of_creation": item.get("date_of_creation", ""),
                    "source": "uk_companies_house",
                }
                self._stamp_record(rec)
                records.append(rec)
        else:
            raise SkipLoader(
                "UKCompaniesHouseLoader requires company_number or search_query"
            )

        return LoaderResult(source_name=self.source_name, records=records)
