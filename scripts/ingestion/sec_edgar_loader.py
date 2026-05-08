"""SEC EDGAR read-only loader.

Reads /submissions/CIK########.json and /api/xbrl/companyfacts/CIK########.json.
SEC requires a descriptive User-Agent — without SEC_USER_AGENT env, the loader
skips cleanly.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseLoader, LoaderResult
from scripts.normalization.signal_event_schema import NumericSignal, SignalEvent
from scripts.normalization.signal_processor import process_signal
from scripts.scoring.filing_materiality_score import filing_materiality_score

EDGAR_BASE = "https://data.sec.gov"


class SECEdgarLoader(BaseLoader):
    source_name = "sec_edgar"
    source_type = "official_filing"

    def fetch(self, *, cik: str, limit: int = 10) -> LoaderResult:
        ua = self.env("SEC_USER_AGENT")
        if not ua:
            return self.skip(
                "SEC_USER_AGENT env var not set — required by SEC fair-access policy"
            )
        cik_padded = str(cik).zfill(10)
        url = f"{EDGAR_BASE}/submissions/CIK{cik_padded}.json"
        try:
            data = self._http_get(url, headers={"User-Agent": ua, "Accept": "application/json"})
        except Exception as exc:
            return self.fail(f"sec_edgar fetch failed: {exc}", cik=cik_padded)

        recent = (data.get("filings", {}) or {}).get("recent", {}) if isinstance(data, dict) else {}
        forms = recent.get("form", []) or []
        accession = recent.get("accessionNumber", []) or []
        filing_dates = recent.get("filingDate", []) or []
        primary_docs = recent.get("primaryDocument", []) or []
        company = data.get("name") if isinstance(data, dict) else None

        rows: list[dict[str, Any]] = []
        for i in range(min(limit, len(forms))):
            rows.append(
                {
                    "form": forms[i],
                    "accession": accession[i] if i < len(accession) else None,
                    "filing_date": filing_dates[i] if i < len(filing_dates) else None,
                    "primary_doc": primary_docs[i] if i < len(primary_docs) else None,
                    "cik": cik_padded,
                    "company": company,
                }
            )

        events = [self.normalize(row) for row in rows]
        return self.ok(events, cik=cik_padded)

    def normalize(self, raw: dict[str, Any]) -> SignalEvent:
        form = raw.get("form") or ""
        materiality = filing_materiality_score(form)
        ts = None
        if raw.get("filing_date"):
            ts = f"{raw['filing_date']}T00:00:00+00:00"
        cik_padded = raw.get("cik") or ""
        accession = raw.get("accession") or ""
        accession_clean = accession.replace("-", "") if accession else ""
        primary = raw.get("primary_doc") or ""
        url: str | None = None
        if cik_padded and accession_clean and primary:
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik_padded)}/"
                f"{accession_clean}/{primary}"
            )
        raw_event: dict[str, Any] = {
            "source_name": self.source_name,
            "source_type": self.source_type,
            "jurisdiction": "US",
            "headline_or_label": f"{raw.get('company') or ''} {form}".strip(),
            "raw_text_or_summary": f"SEC {form} filing for CIK {cik_padded}",
            "url": url,
            "event_type": "sec_filing",
            "asset_tags": [],
            "numeric_signal": NumericSignal(filing_materiality_score=materiality),
            "narrative_intensity": materiality,
            "metadata": {"form": form, "cik": cik_padded, "accession": accession},
        }
        if ts:
            raw_event["timestamp_utc"] = ts
        return process_signal(raw_event)
