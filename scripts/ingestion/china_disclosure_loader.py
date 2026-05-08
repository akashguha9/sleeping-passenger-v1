"""
China disclosure read-only loader — Phase 2 Global Signal Fabric.

Fetches public data from SSE/SZSE exchange disclosure platforms.
No API key required for public data. All outputs advisory only.
"""
from __future__ import annotations

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_TIMEOUT = 15
_DEFAULT_MAX = 20


class ChinaDisclosureLoader(BaseSourceLoader):
    source_name = "china_disclosure"
    requires_key = False

    def __init__(
        self,
        exchange: str = "sse",
        max_records: int = _DEFAULT_MAX,
        timeout: int = _TIMEOUT,
    ) -> None:
        self._exchange = exchange.lower()
        self._max = max_records
        self._timeout = timeout

    def fetch(self) -> LoaderResult:
        """Fetch China exchange disclosure data (read-only, public endpoint)."""
        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        if self._exchange == "sse":
            url = "http://query.sse.com.cn/commonQuery.do"
            params = {
                "isPagination": "true",
                "pageHelp.pageSize": self._max,
                "pageHelp.pageNo": 1,
                "sqlId": "COMMON_SSE_ZQPZ_XXPL_LATEST_L",
            }
            headers = {"Referer": "http://www.sse.com.cn/"}
        else:
            url = "http://www.szse.cn/api/report/ShowReport/data"
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": "1815",
                "tab1PAGECOUNT": self._max,
                "random": "0.1",
            }
            headers = {"Referer": "http://www.szse.cn/"}

        try:
            resp = requests.get(
                url, params=params, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(
                f"China {self._exchange.upper()} API unreachable: {exc}"
            ) from exc

        rows: list = []
        if isinstance(data, dict):
            rows = data.get("result", data.get("data", []))
        elif isinstance(data, list):
            rows = data

        records = []
        for row in (rows or [])[: self._max]:
            if not isinstance(row, dict):
                continue
            rec = dict(row)
            rec["source"] = f"china_{self._exchange}"
            self._stamp_record(rec)
            records.append(rec)

        return LoaderResult(source_name=self.source_name, records=records)
