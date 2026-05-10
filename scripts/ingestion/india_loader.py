"""
India unified read-only loader — Phase C.6 Global Signal Fabric.

Aggregates data from:
  - NSE India allIndices endpoint (Nifty 50, Nifty Bank, India VIX, etc.)
  - RBI press-release page (advisory only)
  - SEBI regulatory listing page (advisory only)

No API key required. All outputs are ADVISORY_ONLY.
Failures on individual sub-sources are tolerated; only skips when ALL fail.
"""
from __future__ import annotations

try:
    from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader
except ModuleNotFoundError:
    from ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader  # type: ignore[no-redef]

_NSE_BASE = "https://www.nseindia.com/api"
_RBI_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
_SEBI_URL = (
    "https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
    "?doListing=yes&sid=1&ssid=3&smid=0"
)
_DEFAULT_INDICES = ["NIFTY 50", "NIFTY BANK", "INDIA VIX"]
_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GSF-Phase2/1.0; research-only)",
    "Accept": "application/json",
}
_DEFAULT_TIMEOUT = 15
_DEFAULT_MAX_ITEMS = 50


class IndiaLoader(BaseSourceLoader):
    """Unified India source: NSE market indices + RBI/SEBI regulatory pages."""

    source_name = "india"
    requires_key = False

    def __init__(
        self,
        symbols: list[str] | None = None,
        date: str | None = None,
        max_items: int = _DEFAULT_MAX_ITEMS,
        timeout: int = _DEFAULT_TIMEOUT,
        nse_base_url: str = _NSE_BASE,
    ) -> None:
        self._symbols = symbols
        self._date = date
        self._max_items = max_items
        self._timeout = timeout
        self._nse_base_url = nse_base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch NSE indices + RBI + SEBI pages (read-only, no execution)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        records: list[dict] = []
        errors: list[str] = []

        # --- NSE indices ---
        nse_indices = self._symbols or _DEFAULT_INDICES
        nse_url = f"{self._nse_base_url}/allIndices"
        try:
            resp = requests.get(nse_url, headers=_NSE_HEADERS, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
            indices_data = data.get("data", []) if isinstance(data, dict) else []
            wanted = {n.upper() for n in nse_indices}
            for idx in indices_data:
                if not isinstance(idx, dict):
                    continue
                if idx.get("index", "").upper() in wanted:
                    rec: dict = {
                        "index_name": idx.get("index", ""),
                        "last_price": idx.get("last"),
                        "change": idx.get("change"),
                        "percent_change": idx.get("percentChange"),
                        "regulatory_source": "india_nse",
                        "regulatory_url": nse_url,
                        "regulatory_note": None,
                    }
                    self._stamp_record(rec)
                    records.append(rec)
        except SkipLoader:
            raise
        except Exception as exc:
            errors.append(f"NSE: {exc}")

        # --- RBI press releases ---
        try:
            resp = requests.get(_RBI_URL, timeout=self._timeout)
            resp.raise_for_status()
            rec = {
                "index_name": "RBI Press Releases",
                "last_price": None,
                "change": None,
                "percent_change": None,
                "regulatory_source": "india_rbi",
                "regulatory_url": _RBI_URL,
                "regulatory_note": "RBI press release page fetched (read-only)",
            }
            self._stamp_record(rec)
            records.append(rec)
        except Exception as exc:
            errors.append(f"RBI: {exc}")

        # --- SEBI listing ---
        try:
            resp = requests.get(_SEBI_URL, timeout=self._timeout)
            resp.raise_for_status()
            rec = {
                "index_name": "SEBI Regulatory Listings",
                "last_price": None,
                "change": None,
                "percent_change": None,
                "regulatory_source": "india_sebi",
                "regulatory_url": _SEBI_URL,
                "regulatory_note": "SEBI listing page fetched (read-only)",
            }
            self._stamp_record(rec)
            records.append(rec)
        except Exception as exc:
            errors.append(f"SEBI: {exc}")

        if not records and errors:
            raise SkipLoader(f"All India endpoints unreachable: {'; '.join(errors)}")

        return LoaderResult(
            source_name=self.source_name,
            records=records[: self._max_items],
        )
