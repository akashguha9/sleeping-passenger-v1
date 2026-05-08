"""
RBI/SEBI read-only loader — Phase 2 Global Signal Fabric.

Fetches public regulatory data from Reserve Bank of India and SEBI.
No API key required. All outputs advisory only.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_TIMEOUT = 15


class RBISEBILoader(BaseSourceLoader):
    source_name = "rbi_sebi"
    requires_key = False

    def __init__(
        self,
        source: str = "rbi",
        timeout: int = _TIMEOUT,
    ) -> None:
        self._source = source.lower()
        self._timeout = timeout

    def fetch(self) -> LoaderResult:
        """Fetch public RBI/SEBI regulatory notices (read-only)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        if self._source == "rbi":
            url = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
            try:
                resp = requests.get(url, timeout=self._timeout)
                resp.raise_for_status()
            except Exception as exc:
                raise SkipLoader(f"RBI website unreachable: {exc}") from exc
            rec = {
                "source": "rbi",
                "url": url,
                "note": "RBI press release page fetched",
                "status_code": resp.status_code,
            }
        else:
            url = (
                "https://www.sebi.gov.in/sebiweb/home/HomeAction.do"
                "?doListing=yes&sid=1&ssid=3&smid=0"
            )
            try:
                resp = requests.get(url, timeout=self._timeout)
                resp.raise_for_status()
            except Exception as exc:
                raise SkipLoader(f"SEBI website unreachable: {exc}") from exc
            rec = {
                "source": "sebi",
                "url": url,
                "note": "SEBI listing page fetched",
                "status_code": resp.status_code,
            }

        self._stamp_record(rec)
        return LoaderResult(source_name=self.source_name, records=[rec])
