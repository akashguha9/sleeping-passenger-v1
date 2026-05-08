"""
EU ESEF (European Single Electronic Format) read-only loader — Phase 2.

Fetches public XBRL filing metadata from ESMA/EFRAG portals.
No API key required for public endpoints.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_ESMA_BASE = "https://filings.efrag.org/api"
_TIMEOUT = 15
_DEFAULT_MAX = 10


class EUESEFLoader(BaseSourceLoader):
    source_name = "eu_esef"
    requires_key = False

    def __init__(
        self,
        country: str | None = None,
        max_filings: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _ESMA_BASE,
    ) -> None:
        self._country = country
        self._max = max_filings
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch EU ESEF XBRL filing metadata (read-only)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        url = f"{self._base_url}/filings"
        params: dict = {"limit": self._max}
        if self._country:
            params["country"] = self._country

        try:
            resp = requests.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"EU ESEF API unreachable: {exc}") from exc

        filings = data if isinstance(data, list) else data.get("filings", [])
        records = []
        for f in filings[: self._max]:
            if not isinstance(f, dict):
                continue
            rec = {
                "entity_name": f.get("entityName", ""),
                "lei": f.get("lei", ""),
                "period": f.get("period", ""),
                "country": f.get("country", ""),
                "filing_date": f.get("filingDate", ""),
                "source": "eu_esef",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
