"""
Japan EDINET read-only loader — Phase 2 Global Signal Fabric.

Requires EDINET_API_KEY env var. Skips cleanly if missing.
EDINET is Japan's Electronic Disclosure for Investors' NeTwork.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v1"
_TIMEOUT = 15
_DEFAULT_MAX = 10


class JapanEDINETLoader(BaseSourceLoader):
    source_name = "japan_edinet"
    requires_key = True

    def __init__(
        self,
        date: str | None = None,
        doc_type: str = "120",
        max_docs: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
        base_url: str = _EDINET_BASE,
    ) -> None:
        self._date = date
        self._doc_type = doc_type
        self._max = max_docs
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")

    def fetch(self) -> LoaderResult:
        """Fetch EDINET filing list (read-only). Requires EDINET_API_KEY."""
        api_key = self._require_env_key("EDINET_API_KEY")

        if not self._date:
            from datetime import date as _date
            self._date = _date.today().isoformat()

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        url = f"{self._base_url}/documents.json"
        params = {
            "date": self._date,
            "type": 2,
            "Subscription-Key": api_key,
        }
        try:
            resp = requests.get(url, params=params, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"EDINET API unreachable: {exc}") from exc

        results = data.get("results", []) if isinstance(data, dict) else []
        records = []
        for doc in results[: self._max]:
            if not isinstance(doc, dict):
                continue
            if self._doc_type and doc.get("docTypeCode") != self._doc_type:
                continue
            rec = {
                "doc_id": doc.get("docID", ""),
                "filer_name": doc.get("filerName", ""),
                "doc_type_code": doc.get("docTypeCode", ""),
                "period_start": doc.get("periodStart", ""),
                "period_end": doc.get("periodEnd", ""),
                "submit_date": doc.get("submitDateTime", ""),
                "source": "japan_edinet",
            }
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
