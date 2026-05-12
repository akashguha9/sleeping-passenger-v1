"""
SEC EDGAR read-only loader — Phase 2 Global Signal Fabric.

Requires SEC_USER_AGENT env var (SEC fair-access policy mandates an identifying
User-Agent header). Skips cleanly if the env var is not set.

CIK modes
---------
- Pass cik=<str>                    → fetch filings for that single entity.
- Pass use_default_watchlist=True   → iterate over the built-in watchlist.
- Pass neither                      → clean SkipLoader (no CIK provided).

Default watchlist
-----------------
  Apple     0000320193
  Microsoft 0000789019
  Nvidia    0001045810
  Tesla     0001318605
  Amazon    0001018724
  Meta      0001326801
  Alphabet  0001652044
"""
from __future__ import annotations

import re
from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_EDGAR_BASE = "https://data.sec.gov"
_TIMEOUT = 15

_CIK_RE = re.compile(r"^\d{1,10}$")

_DEFAULT_WATCHLIST: list[tuple[str, str]] = [
    ("Apple",     "0000320193"),
    ("Microsoft", "0000789019"),
    ("Nvidia",    "0001045810"),
    ("Tesla",     "0001318605"),
    ("Amazon",    "0001018724"),
    ("Meta",      "0001326801"),
    ("Alphabet",  "0001652044"),
]

# Accepted form types for advisory signal generation
_DEFAULT_FORM_TYPES: tuple[str, ...] = ("10-K", "10-Q", "8-K")


def _validate_cik(cik: str) -> str | None:
    """Return None if CIK is acceptable, or an error string."""
    raw = cik.strip()
    if not raw:
        return "CIK is empty"
    if not _CIK_RE.match(raw):
        return f"malformed CIK (expected 1-10 digits): {raw!r}"
    return None


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
        use_default_watchlist: bool = False,
    ) -> None:
        self._cik = cik
        self._form_types: tuple[str, ...] = (
            tuple(form_type.split(",")) if "," in form_type else (form_type,)
        )
        self._max = max_filings
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        self._use_default_watchlist = use_default_watchlist

    def _fetch_cik(
        self,
        cik: str,
        requests_mod: Any,
        headers: dict[str, str],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch and parse recent filings for a single CIK. Returns (records, error_or_None)."""
        cik_str = cik.strip()
        err = _validate_cik(cik_str)
        if err:
            return [], err

        cik_padded = cik_str.zfill(10)
        url = f"{self._base_url}/submissions/CIK{cik_padded}.json"
        try:
            resp = requests_mod.get(url, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return [], f"SEC EDGAR unreachable for CIK {cik_str}: {exc}"

        if not isinstance(data, dict):
            return [], f"unexpected response format for CIK {cik_str}"

        entity_name = data.get("name", "") or data.get("entityType", "") or ""
        filings = data.get("filings", {}).get("recent", {}) if isinstance(data, dict) else {}
        forms = filings.get("form", []) or []
        dates = filings.get("filingDate", []) or []
        acc_nos = filings.get("accessionNumber", []) or []

        records: list[dict[str, Any]] = []
        for i, form in enumerate(forms):
            if form not in self._form_types:
                continue
            if len(records) >= self._max:
                break
            rec = {
                "cik": cik_str,
                "entity_name": entity_name,
                "form_type": form,
                "filing_date": dates[i] if i < len(dates) else "",
                "accession_number": acc_nos[i] if i < len(acc_nos) else "",
                "source": "sec_edgar",
            }
            self._stamp_record(rec)
            records.append(rec)
        return records, None

    def fetch(self) -> LoaderResult:
        """Fetch recent SEC filings (read-only). Requires SEC_USER_AGENT env var."""
        user_agent = self._require_env_key("SEC_USER_AGENT")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        headers = {"User-Agent": user_agent, "Accept": "application/json"}

        # --- Single CIK mode ---
        if self._cik:
            err = _validate_cik(self._cik)
            if err:
                raise SkipLoader(f"Invalid CIK: {err}")
            records, fetch_err = self._fetch_cik(self._cik, requests, headers)
            if fetch_err:
                raise SkipLoader(fetch_err)
            return LoaderResult(source_name=self.source_name, records=records)

        # --- Watchlist mode ---
        if self._use_default_watchlist:
            all_records: list[dict[str, Any]] = []
            errors: list[str] = []
            for name, watch_cik in _DEFAULT_WATCHLIST:
                recs, err = self._fetch_cik(watch_cik, requests, headers)
                if err:
                    errors.append(f"{name}/{watch_cik}: {err}")
                else:
                    all_records.extend(recs)
            if not all_records and errors:
                raise SkipLoader(
                    f"SEC EDGAR watchlist all failed: {'; '.join(errors[:3])}"
                )
            return LoaderResult(source_name=self.source_name, records=all_records)

        # --- No CIK, no watchlist ---
        raise SkipLoader(
            "No CIK provided to SEC EDGAR loader — "
            "pass --sec-cik <CIK> or --sec-default-watchlist"
        )
