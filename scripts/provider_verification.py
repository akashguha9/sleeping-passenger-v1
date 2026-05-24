"""Provider verification helpers — turn loader output into honest source-health rows.

Integrated Sprint — Part 2.  The existing repo already has provider loaders
(``scripts/ingestion/sec_edgar_loader.py``,
``scripts/ingestion/gdelt_loader.py``,
``scripts/yahoo_market_data_adapter.py``).  This module is the *integrated
sprint surface*: given the records a loader returned (or a degradation signal),
it produces the normalized provider-row that :mod:`scripts.live_payload_quality`
understands and ``runtime/release/release_gate.json`` consumes.

The hard rules the sprint demands:

  * FALLBACK / MOCK / UNVERIFIED can never produce ``status = HEALTHY``.
  * STALE producers must mark ``verification_status = STALE`` and ``status = STALE``.
  * Provider call failures degrade status but do *not* erase last-good data.
  * The timestamp must update only when verified fresh data actually arrived.

Pure module; no DB, no broker calls, no execution, no AI execution.  Network
work is deliberately *not* performed here — the loader does that; this
module classifies its output.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import live_payload_quality as _lpq
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import live_payload_quality as _lpq  # type: ignore[no-redef]


CLASS_SLA_DEFAULTS_HOURS: dict[str, float] = {
    "price": 24.0,
    "filings": 72.0,
    "news_event": 24.0,
    "ai_report": 24.0,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def age_hours(latest_event_timestamp_utc: str | None,
              now_utc: datetime | None = None) -> float | None:
    """Hours since the latest verified event.  ``None`` if no valid timestamp."""
    ts = _parse_utc(latest_event_timestamp_utc)
    if ts is None:
        return None
    now = now_utc or datetime.now(timezone.utc)
    delta = (now - ts).total_seconds() / 3600.0
    if math.isnan(delta) or delta < 0:
        return 0.0
    return round(delta, 6)


def classify_provider(
    *,
    provider: str,
    source_class: str,
    records: Iterable[dict[str, Any]] | None,
    latest_event_timestamp_utc: str | None,
    sla_hours: float | None = None,
    last_call_succeeded: bool = False,
    last_call_error: str | None = None,
    is_fallback: bool = False,
    is_mock: bool = False,
    schema_valid: bool = True,
    schema_partial: bool = False,
    previous_status: str | None = None,
    previous_timestamp_utc: str | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Return a normalized provider-health row.

    The hard rules:

    * ``is_mock``    → ``MOCK`` / verification ``MOCK``; never HEALTHY.
    * ``is_fallback``→ ``FALLBACK`` / verification ``FALLBACK``; never HEALTHY.
    * ``schema_valid=False`` → ``DEGRADED`` / verification ``UNVERIFIED``.
    * ``last_call_succeeded=False`` AND no previous data → ``OFFLINE``.
    * Provider call failure + previous data exists → ``DEGRADED`` (last-good
      data preserved; timestamp NOT advanced).
    * Age > SLA → ``STALE``.
    * Otherwise: HEALTHY only when (records present OR latest timestamp within
      SLA) AND last_call_succeeded AND schema_valid.
    """
    sla = float(sla_hours if sla_hours is not None
                else CLASS_SLA_DEFAULTS_HOURS.get(source_class, 24.0))
    record_list = list(records or [])
    record_count = len(record_list)
    age = age_hours(latest_event_timestamp_utc, now_utc=now_utc)
    has_records = record_count > 0
    has_timestamp = age is not None

    # MOCK / FALLBACK can never be HEALTHY.
    if is_mock:
        status = _lpq.STATUS_MOCK
        verification = _lpq.VERIF_MOCK
        # Preserve previous timestamp; do not advance with mock data.
        effective_timestamp = previous_timestamp_utc
    elif is_fallback:
        status = _lpq.STATUS_FALLBACK
        verification = _lpq.VERIF_FALLBACK
        effective_timestamp = previous_timestamp_utc
    elif not schema_valid:
        status = _lpq.STATUS_DEGRADED
        verification = _lpq.VERIF_UNVERIFIED
        effective_timestamp = previous_timestamp_utc
    elif not last_call_succeeded:
        if previous_timestamp_utc:
            # Degrade but preserve last-good data + previous timestamp.
            status = _lpq.STATUS_DEGRADED
            verification = _lpq.VERIF_STALE if (
                age_hours(previous_timestamp_utc, now_utc=now_utc) or 0
            ) > sla else _lpq.VERIF_UNVERIFIED
            effective_timestamp = previous_timestamp_utc
        else:
            status = _lpq.STATUS_OFFLINE
            verification = _lpq.VERIF_UNVERIFIED
            effective_timestamp = None
    else:
        # Successful call.  Honest classification by age + records.
        if not has_records and not has_timestamp:
            status = _lpq.STATUS_DEGRADED
            verification = _lpq.VERIF_UNVERIFIED
            effective_timestamp = previous_timestamp_utc
        elif age is not None and age > sla:
            status = _lpq.STATUS_STALE
            verification = _lpq.VERIF_STALE
            effective_timestamp = latest_event_timestamp_utc
        else:
            status = _lpq.STATUS_HEALTHY
            verification = _lpq.VERIF_VERIFIED
            effective_timestamp = latest_event_timestamp_utc
            if schema_partial:
                status = _lpq.STATUS_DEGRADED

    # Compute scores per source-health formula (advisory; sprint spec).
    fresh = _lpq.freshness_score(age, sla) if age is not None else 0.0
    availability = (
        1.0 if last_call_succeeded
        else 0.5 if previous_timestamp_utc else 0.0
    )
    schema = (
        1.0 if schema_valid and not schema_partial
        else 0.5 if (schema_valid and schema_partial)
        else 0.0
    )
    verification_score = {
        _lpq.VERIF_VERIFIED: 1.0,
        _lpq.VERIF_UNVERIFIED: 0.5,
        _lpq.VERIF_STALE: 0.25,
        _lpq.VERIF_FALLBACK: 0.0,
        _lpq.VERIF_MOCK: 0.0,
    }.get(verification, 0.0)
    provider_health = round(
        max(0.0, min(1.0,
                     0.35 * fresh
                     + 0.25 * availability
                     + 0.20 * schema
                     + 0.20 * verification_score)),
        6,
    )

    return {
        "provider": provider,
        "source_class": source_class,
        "status": status,
        "verification_status": verification,
        "freshness_status": (
            "FRESH" if status == _lpq.STATUS_HEALTHY
            else "AGING" if status == _lpq.STATUS_DEGRADED
            else "STALE" if status in {_lpq.STATUS_STALE, _lpq.STATUS_FALLBACK,
                                       _lpq.STATUS_MOCK}
            else "UNKNOWN"
        ),
        "record_count": record_count,
        "age_hours": age,
        "sla_hours": sla,
        "latest_event_timestamp_utc": effective_timestamp,
        "checked_at_utc": _utc_iso(),
        "last_call_succeeded": bool(last_call_succeeded),
        "last_error": last_call_error,
        "freshness_score": fresh,
        "availability_score": availability,
        "schema_score": schema,
        "verification_score": verification_score,
        "provider_health": provider_health,
        "is_fallback": bool(is_fallback),
        "is_mock": bool(is_mock),
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def normalize_signal_event(
    *,
    raw_record: dict[str, Any],
    provider: str,
    source_class: str,
    verification_status: str,
    freshness_status: str,
) -> dict[str, Any]:
    """Project a loader's raw record into the sprint-spec normalized SignalEvent."""
    import hashlib

    title = (raw_record.get("title") or raw_record.get("event_type")
             or raw_record.get("source") or "")
    source = (raw_record.get("source_name") or raw_record.get("source")
              or provider)
    ts = (raw_record.get("timestamp_utc") or raw_record.get("fetched_at")
          or raw_record.get("published_at"))
    asset_tags = list(raw_record.get("asset_tags") or
                      ([raw_record["ticker"]] if raw_record.get("ticker") else []))
    key = "|".join([
        str(source).lower(),
        str(provider).lower(),
        str(raw_record.get("event_type") or "").lower(),
        str(ts or "")[:16],
        ",".join(sorted(asset_tags)),
        str(title)[:120].lower(),
    ])
    event_id = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return {
        "event_id": event_id,
        "source_name": source,
        "source_type": source_class,
        "provider": provider,
        "jurisdiction": raw_record.get("jurisdiction"),
        "timestamp_utc": ts,
        "ingested_at_utc": _utc_iso(),
        "asset_tags": asset_tags,
        "event_type": raw_record.get("event_type"),
        "numeric_signal": raw_record.get("numeric_signal") or {},
        "text_signal": raw_record.get("text_signal") or {},
        "source_url": raw_record.get("source_url"),
        "reliability": float(raw_record.get("reliability", 0.0) or 0.0),
        "freshness": float(raw_record.get("freshness", 0.0) or 0.0),
        "verification_status": verification_status,
        "freshness_status": freshness_status,
        "advisory_only": True,
        "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="provider_verification.py",
        description=(
            "Classify a provider's last-run output into the normalized "
            "source-health row. Read-only; no broker calls; no execution."
        ),
    )
    p.add_argument("--provider", required=True)
    p.add_argument("--source-class", required=True,
                   choices=list(CLASS_SLA_DEFAULTS_HOURS))
    p.add_argument("--latest-ts", default=None)
    p.add_argument("--record-count", type=int, default=0)
    p.add_argument("--last-call-succeeded", action="store_true")
    p.add_argument("--is-fallback", action="store_true")
    p.add_argument("--is-mock", action="store_true")
    p.add_argument("--schema-valid", action="store_true", default=True)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    row = classify_provider(
        provider=args.provider,
        source_class=args.source_class,
        records=[{} for _ in range(max(0, args.record_count))],
        latest_event_timestamp_utc=args.latest_ts,
        last_call_succeeded=args.last_call_succeeded,
        is_fallback=args.is_fallback,
        is_mock=args.is_mock,
        schema_valid=args.schema_valid,
    )
    if args.json:
        print(json.dumps(row, indent=2, default=str))
    else:
        print(f"{args.provider} ({args.source_class}) -> {row['status']} / "
              f"{row['verification_status']} (health={row['provider_health']})")
    return 0


__all__ = [
    "CLASS_SLA_DEFAULTS_HOURS",
    "age_hours",
    "classify_provider",
    "normalize_signal_event",
]


if __name__ == "__main__":
    raise SystemExit(main())
