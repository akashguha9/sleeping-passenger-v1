"""
SEC EDGAR read-only loader — Phase 2 Global Signal Fabric.

Requires SEC_USER_AGENT env var (SEC fair-access policy mandates an identifying
User-Agent header). Skips cleanly if the env var is not set.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_EDGAR_BASE = "https://data.sec.gov"
_TIMEOUT = 15


class SECEdgarLoader(BaseSourceLoader):
    source_name = "sec_edgar"
    requires_key = True

    def __init__(
        self,
        cik: str | None = None,
        form_type: str = "10-K",
        max_filings: int = 10,
        timeout: int = _TIMEOUT,
        base_url: str = _EDGAR_BASE,
    ) -> None:
        self._cik = cik
        self._form_type = form_type
        self._max = max_filings
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch recent SEC filings (read-only). Requires SEC_USER_AGENT env var."""
        user_agent = self._require_env_key("SEC_USER_AGENT")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        headers = {"User-Agent": user_agent, "Accept": "application/json"}

        if self._cik:
            cik_padded = str(self._cik).zfill(10)
            url = f"{self._base_url}/submissions/CIK{cik_padded}.json"
            try:
                resp = requests.get(url, headers=headers, timeout=self._timeout)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                raise SkipLoader(f"SEC EDGAR unreachable: {exc}") from exc

            filings = (
                data.get("filings", {}).get("recent", {})
                if isinstance(data, dict)
                else {}
            )
            forms = filings.get("form", []) or []
            dates = filings.get("filingDate", []) or []
            acc_nos = filings.get("accessionNumber", []) or []
            records = []
            for i, form in enumerate(forms):
                if form != self._form_type:
                    continue
                if len(records) >= self._max:
                    break
                rec = {
                    "cik": self._cik,
                    "form_type": form,
                    "filing_date": dates[i] if i < len(dates) else "",
                    "accession_number": acc_nos[i] if i < len(acc_nos) else "",
                    "source": "sec_edgar",
                }
                self._stamp_record(rec)
                records.append(rec)
        else:
            url = f"{self._base_url}/submissions"
            try:
                resp = requests.get(url, headers=headers, timeout=self._timeout)
                resp.raise_for_status()
            except Exception as exc:
                raise SkipLoader(f"SEC EDGAR unreachable: {exc}") from exc
            rec = {"source": "sec_edgar", "note": "no cik provided, index fetched"}
            self._stamp_record(rec)
            records = [rec]

        return LoaderResult(source_name=self.source_name, records=records)
