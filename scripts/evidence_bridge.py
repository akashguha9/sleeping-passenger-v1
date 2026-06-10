"""Production evidence-ledger bridge (Pass 5, Phase 3).

Pass 4 built the evidence ledger; this bridge makes it the DEFAULT path
for every signal-relevant write by hooking the persistence chokepoints
(``insert_signal_event`` covers ALL live ingestion runners — news,
filings, prediction markets; manual trades / reconciliation / moltbook /
imported outcomes cover the journal; ``ai_report_ingestion`` covers LLM
reports).

Contract:
  * BEST-EFFORT, NEVER RAISES into the caller — a broken ledger must not
    block journaling (the gap is visible in the coverage audit instead).
  * Every successful evidence write also emits a tamper-evident audit
    event (``evidence_recorded``).
  * Naive timestamps from legacy writers are recorded as assumed-UTC with
    ``extraction_method`` flagged and confidence capped at 0.4 — recorded
    honestly rather than dropped; the temporal guard still refuses them
    for EVALUATION, which is the strict layer.
  * Under pytest the bridge is inert unless ``MVP_EVIDENCE_LEDGER_PATH``
    is explicitly set (same precedent as the dotenv loader): thousands of
    unrelated tests must not pollute the operator's real ledger.

Advisory-only: records that evidence exists; executes nothing.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from typing import Any

try:
    from scripts import data_quality as _dq
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import data_quality as _dq  # type: ignore[no-redef]

_ASSUMED_UTC_METHOD = "assumed_utc_naive_timestamp"
_ASSUMED_UTC_MAX_CONFIDENCE = 0.4


def _bridge_inert() -> bool:
    return "pytest" in sys.modules and not os.environ.get(
        "MVP_EVIDENCE_LEDGER_PATH", ""
    ).strip()


def _to_aware_utc(value: Any) -> tuple[_dt.datetime | None, bool]:
    """Parse to aware UTC. Returns (dt, was_naive). None on unparsable."""
    if value is None:
        return None, False
    if isinstance(value, _dt.datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None, False
        try:
            dt = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None, False
    if dt.tzinfo is None:
        # Legacy writers stamp naive UTC; record honestly as assumed.
        return dt.replace(tzinfo=_dt.timezone.utc), True
    return dt.astimezone(_dt.timezone.utc), False


def record_evidence(
    *,
    source_type: str,
    source_name: str,
    claim: str,
    raw_evidence: Any,
    observed_at: Any = None,
    published_at: Any = None,
    symbol: str = "",
    value: str = "",
    confidence: float = 0.6,
    provenance: str = "",
    extraction_method: str = "production_bridge",
) -> dict | None:
    """Best-effort: validate + append one evidence item + audit event.

    Returns the persisted record dict, or None when skipped/inert/failed.
    """
    if _bridge_inert():
        return None
    try:
        observed, naive_obs = _to_aware_utc(observed_at)
        if observed is None:
            observed = _dt.datetime.now(_dt.timezone.utc)
        published, naive_pub = _to_aware_utc(published_at)
        if naive_obs or naive_pub:
            confidence = min(float(confidence), _ASSUMED_UTC_MAX_CONFIDENCE)
            extraction_method = f"{extraction_method}+{_ASSUMED_UTC_METHOD}"
        if published is not None and observed < published:
            # Impossible ordering — drop the published stamp, keep evidence.
            published = None
            extraction_method += "+published_after_observed_dropped"

        if not isinstance(raw_evidence, (bytes, str)):
            raw_evidence = json.dumps(raw_evidence, sort_keys=True, default=str)

        item = _dq.build_evidence(
            source_type=source_type,
            source_name=source_name,
            claim=claim,
            raw_evidence=raw_evidence,
            observed_at=observed,
            published_at=published,
            symbol=symbol,
            value=value,
            confidence=confidence,
            provenance=provenance,
            extraction_method=extraction_method,
        )
        _dq.append_evidence(item)
        try:
            from scripts.audit_log import append_event
        except ModuleNotFoundError:  # pragma: no cover
            from audit_log import append_event  # type: ignore[no-redef]
        append_event(
            "evidence_recorded",
            actor="system",
            action=f"evidence:{source_type}:{source_name}",
            outcome="ok",
            metadata={"evidence_id": item.evidence_id, "symbol": item.symbol},
        )
        return item.to_dict()
    except Exception:
        # Never break the production write path; the coverage audit and
        # ledger verification surface gaps instead.
        return None


# ---------------------------------------------------------------------------
# Typed adapters for each production chokepoint
# ---------------------------------------------------------------------------


def on_signal_event(event_id: str, source_name: str, raw_payload: dict,
                    fetched_at: str) -> dict | None:
    """Hook for persistence.insert_signal_event (ALL live ingestion)."""
    symbol = str(
        raw_payload.get("symbol") or raw_payload.get("ticker") or ""
    )
    title = str(
        raw_payload.get("title") or raw_payload.get("headline")
        or raw_payload.get("question") or raw_payload.get("event_type")
        or f"signal event {event_id}"
    )
    return record_evidence(
        source_type="api",
        source_name=source_name or "unknown_runner",
        claim=title,
        raw_evidence=raw_payload,
        observed_at=fetched_at,
        published_at=raw_payload.get("published_at") or raw_payload.get("seendate"),
        symbol=symbol,
        provenance=str(raw_payload.get("url") or raw_payload.get("link") or ""),
        confidence=0.6,
        extraction_method="insert_signal_event",
    )


def on_manual_trade(trade: dict) -> dict | None:
    """Hook for persistence.insert_manual_trade (operator journal)."""
    return record_evidence(
        source_type="manual",
        source_name="manual_trade_log",
        claim=str(trade.get("thesis") or f"manual trade {trade.get('ticker', '?')}"),
        raw_evidence={k: trade.get(k) for k in
                      ("trade_id", "ticker", "side", "quantity", "price", "thesis")},
        observed_at=trade.get("executed_at") or trade.get("logged_at"),
        symbol=str(trade.get("ticker") or ""),
        value=str(trade.get("price") or ""),
        confidence=0.9,  # first-person observation
        extraction_method="insert_manual_trade",
    )


def on_reconciliation(rec: dict) -> dict | None:
    """Hook for persistence.insert_reconciliation (outcome evidence)."""
    return record_evidence(
        source_type="manual",
        source_name="reconciliation",
        claim=f"outcome {rec.get('outcome_status', '?')} for trade {rec.get('trade_id', '?')}",
        raw_evidence={k: rec.get(k) for k in
                      ("trade_id", "outcome_status", "pnl_estimate", "actual_price")},
        observed_at=rec.get("reconciled_at"),
        symbol=str(rec.get("ticker") or ""),
        value=str(rec.get("pnl_estimate") or ""),
        confidence=0.9,
        extraction_method="insert_reconciliation",
    )


def on_moltbook_entry(entry: dict) -> dict | None:
    """Hook for persistence.insert_moltbook_entry (post-mortem journal)."""
    return record_evidence(
        source_type="manual",
        source_name="moltbook",
        claim=str(entry.get("lesson_learned") or entry.get("mistake_type")
                  or "moltbook entry"),
        raw_evidence={k: entry.get(k) for k in
                      ("entry_id", "ticker", "outcome", "mistake_type")},
        observed_at=entry.get("created_at"),
        symbol=str(entry.get("ticker") or ""),
        confidence=0.8,
        extraction_method="insert_moltbook_entry",
    )


def on_imported_outcomes(rows: list[dict]) -> int:
    """Hook for persistence.insert_imported_outcomes (backtest datasets)."""
    written = 0
    for row in rows:
        if record_evidence(
            source_type="file",
            source_name=str(row.get("source_type") or "imported_outcomes"),
            claim=(f"imported outcome {row.get('outcome_id', '?')} "
                   f"{row.get('ticker', '?')} {row.get('direction', '')}").strip(),
            raw_evidence=row,
            observed_at=row.get("closed_at") or row.get("opened_at"),
            symbol=str(row.get("ticker") or ""),
            value=str(row.get("exit_price") or ""),
            confidence=0.7,
            extraction_method="insert_imported_outcomes",
        ):
            written += 1
    return written


def on_ai_report(report: dict) -> dict | None:
    """Hook for ai_report_ingestion (LLM synthesis outputs)."""
    tags = report.get("asset_tags") or []
    return record_evidence(
        source_type="llm",
        source_name=str(report.get("model_name") or "unknown_model"),
        claim=(f"{report.get('stance', '?')} on {', '.join(tags) or 'unspecified assets'} "
               f"(conf {report.get('confidence', '?')})"),
        raw_evidence={"report_id": report.get("report_id"),
                      "raw_text_hash": report.get("raw_text_hash"),
                      "claims": report.get("extracted_claims")},
        observed_at=report.get("ingested_at_utc"),
        published_at=report.get("generated_at_utc"),
        symbol=str(tags[0]) if tags else "",
        confidence=min(float(report.get("confidence") or 0.5), 1.0),
        extraction_method="ai_report_ingestion",
    )
