"""
Polymarket × Kalshi cross-venue disagreement scanner.

Advisory-only information-fracture detector.  When the same real-world
event trades at two different implied probabilities on Polymarket and
Kalshi, this scanner emits an alert so a human reviewer can decide
whether the divergence reflects information asymmetry, resolution
ambiguity, or market noise.

Hard non-goals — these MUST NOT be added
-----------------------------------------
- NOT arbitrage.  NOT a trade recommendation.  NOT execution.
- No "buy", "sell", "execute", "trade now", "arbitrage this",
  "guaranteed edge", or "order placement" language in any output.
- No broker call, broker integration, or order endpoint.
- Authenticated Kalshi or Polymarket endpoints remain forbidden.

Inputs
------
By default the scanner loads the most recent ``signal_events`` rows for
``source_name`` of ``polymarket`` and ``kalshi`` from the canonical
SQLite store.  ``--from-fixtures`` lets a test or operator point the
scanner at a JSON file with two arrays (``polymarket`` and ``kalshi``).

Outputs
-------
Dry-run mode prints a compact JSON list of pairs (always advisory).
Write mode persists each disagreement into ``signal_events`` under
``source_name="prediction_market_disagreement"`` so the existing API
surface can serve it without schema changes.  No new mutation table is
created; we deliberately keep the disagreement layer as a *derived*
signal stream.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.prediction_market_semantic_pairing import (
        AMBIGUOUS_MATCH,
        FALSE_MATCH,
        SAME_EVENT_DIFFERENT_THRESHOLD,
        SAME_EVENT_SAME_RESOLUTION,
        SAME_THEME_DIFFERENT_EVENT,
        PairClassification,
        classify_pair_resolution,
        deterministic_fake_embedding,
        iter_pair_candidates,
    )
    from scripts.prediction_market_embedding_providers import (
        DeterministicEmbeddingProvider,
        EmbeddingProvider,
        EmbeddingProviderUnavailable,
        resolve_embedding_provider,
    )
except ModuleNotFoundError:  # pragma: no cover
    from prediction_market_semantic_pairing import (  # type: ignore[no-redef]
        AMBIGUOUS_MATCH,
        FALSE_MATCH,
        SAME_EVENT_DIFFERENT_THRESHOLD,
        SAME_EVENT_SAME_RESOLUTION,
        SAME_THEME_DIFFERENT_EVENT,
        PairClassification,
        classify_pair_resolution,
        deterministic_fake_embedding,
        iter_pair_candidates,
    )
    from prediction_market_embedding_providers import (  # type: ignore[no-redef]
        DeterministicEmbeddingProvider,
        EmbeddingProvider,
        EmbeddingProviderUnavailable,
        resolve_embedding_provider,
    )

CROSS_VENUE_SIGNAL_CLASS = "CROSS_VENUE_DISAGREEMENT"
CUSTOMER_LABEL = "Prediction Market Disagreement Alert"
PERSISTENCE_SOURCE_NAME = "prediction_market_disagreement"
DEFAULT_DISAGREEMENT_THRESHOLD = 0.05

# Pair types eligible to emit a clean disagreement alert.
_ELIGIBLE_PAIR_TYPES: frozenset[str] = frozenset(
    {SAME_EVENT_SAME_RESOLUTION, AMBIGUOUS_MATCH}
)

# Pair types that produce diagnostics-only output (no clean alert).
_DIAGNOSTIC_PAIR_TYPES: frozenset[str] = frozenset(
    {SAME_EVENT_DIFFERENT_THRESHOLD, SAME_THEME_DIFFERENT_EVENT}
)

# Reason prefixes that disqualify a pair from a clean ALERT regardless of
# how large the probability gap is.  These come from the semantic-pairing
# layer's own diagnostics — when any of them appear we degrade to BLOCKED
# so embedding similarity alone can never override entity / threshold /
# resolution / category mismatches.
_ALERT_FORBIDDEN_REASON_PREFIXES: tuple[str, ...] = (
    "no_shared_asset_entity",
    "category_mismatch",
    "entity_mismatch",
    "threshold_mismatch",
    "settlement_source_mismatch",
    "resolution_mismatch_blocks_clean_alert",
    "incompatible_category",
    "low_semantic_overlap_no_shared_entity",
)

# Confidence bands that block any ALERT.
_BLOCKED_CONFIDENCE_BANDS: frozenset[str] = frozenset({"BLOCKED", "LOW"})

# Confidence-band thresholds against the semantic-pairing final_score.
_CONFIDENCE_BAND_STRONG = 0.65
_CONFIDENCE_BAND_MEDIUM = 0.45

# Read-only / advisory contract stamped on every CLI report envelope.
_READ_ONLY_CONTRACT: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_permission": "ADVISORY_ONLY",
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "broker_api_called": False,
    "ai_execution_count": 0,
    "trading_endpoints_called": False,
    "auth_headers_sent": False,
}


def _monotonic() -> float:
    import time as _time

    return _time.monotonic()


def _now_iso() -> str:
    try:
        try:
            from scripts.runtime_common import utc_timestamp
        except ModuleNotFoundError:
            from runtime_common import utc_timestamp  # type: ignore[no-redef]
        return utc_timestamp()
    except Exception:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


def _log_source_run(
    *,
    status: str,
    fetched_count: int,
    error_message: str,
    timestamp_utc: str,
    duration_ms: int,
    extras: dict[str, Any] | None = None,
) -> None:
    """Best-effort source_run_log write for the disagreement scanner.

    Mirrors the convention used by ``scripts.live_source_runner`` so the
    /source-health/summary endpoint can report ``never_run`` / ``stale``
    / healthy state for the disagreement family.  Always advisory-only;
    never raises into the caller.
    """
    try:
        try:
            from scripts import persistence as _persistence
            from scripts.persistence import log_source_run
        except ModuleNotFoundError:
            import persistence as _persistence  # type: ignore[no-redef]
            from persistence import log_source_run  # type: ignore[no-redef]
    except Exception:
        return
    target_db = getattr(_persistence, "DB_PATH", None)
    skipped_reason = ""
    if extras:
        try:
            skipped_reason = json.dumps(extras, default=str)
        except Exception:
            skipped_reason = ""
    try:
        kwargs: dict[str, Any] = {
            "source_name": PERSISTENCE_SOURCE_NAME,
            "status": status,
            "fetched_count": int(fetched_count),
            "skipped_reason": skipped_reason,
            "error_message": error_message,
            "timestamp_utc": timestamp_utc,
            "duration_ms": int(duration_ms),
        }
        if target_db is not None:
            kwargs["db_path"] = target_db
        log_source_run(**kwargs)
    except Exception:
        return


# ---------------------------------------------------------------------------
# Probability extraction
# ---------------------------------------------------------------------------


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract_implied_probability(market: dict[str, Any]) -> float | None:
    """Best-effort recovery of a 0..1 implied probability for a market.

    Backwards-compatible wrapper around
    :func:`extract_implied_probability_with_source` that returns only the
    numeric probability.  Use the ``_with_source`` variant when you need
    the provenance label too.
    """
    prob, _ = extract_implied_probability_with_source(market)
    return prob


def extract_implied_probability_with_source(
    market: dict[str, Any],
) -> tuple[float | None, str]:
    """Recover ``(probability, source_field_name)`` for a market.

    Field priority (first valid 0..1 wins):

      1. ``implied_probability``   — canonical (must already be 0..1)
      2. ``yes_price`` / ``yes_ask`` — Kalshi YES leg (0..1 or 0..100)
      3. ``last_price``            — Kalshi last traded
      4. ``outcomePrices`` / ``outcome_prices`` — Polymarket Gamma
      5. ``lastTradePrice``        — Polymarket fallback

    ``"missing"`` is returned for the source when no field yields a
    valid probability — callers can branch on that to emit
    ``PROBABILITY_MISSING`` cleanly.
    """
    if not isinstance(market, dict):
        return None, "missing"

    direct = _coerce_float(market.get("implied_probability"))
    if direct is not None and 0.0 <= direct <= 1.0:
        return direct, "implied_probability"

    yes = _coerce_float(market.get("yes_price") or market.get("yes_ask"))
    if yes is not None:
        if 0.0 <= yes <= 1.0:
            return yes, "yes_price"
        if 0.0 <= yes <= 100.0:
            return yes / 100.0, "yes_price"

    last = _coerce_float(market.get("last_price") or market.get("lastTradePrice"))
    if last is not None:
        if 0.0 <= last <= 1.0:
            return last, "last_price"
        if 0.0 <= last <= 100.0:
            return last / 100.0, "last_price"

    # Polymarket outcomePrices is typically a stringified list like
    # '["0.62","0.38"]' or a real list.  Try both ``outcomePrices`` and
    # the snake_case alias.
    for field in ("outcomePrices", "outcome_prices"):
        outcome = market.get(field)
        if isinstance(outcome, str):
            try:
                outcome = json.loads(outcome)
            except (ValueError, TypeError):
                outcome = None
        if isinstance(outcome, list) and outcome:
            first = _coerce_float(outcome[0])
            if first is not None and 0.0 <= first <= 1.0:
                return first, field

    return None, "missing"


def _pair_id(poly: dict[str, Any], kalshi: dict[str, Any]) -> str:
    poly_id = str(
        poly.get("market_id")
        or poly.get("event_id")
        or poly.get("condition_id")
        or "unknown"
    )
    kalshi_id = str(
        kalshi.get("source_market_id")
        or kalshi.get("event_id")
        or "unknown"
    )
    return f"poly_{poly_id}__kalshi_{kalshi_id}"


# ---------------------------------------------------------------------------
# Alert construction
# ---------------------------------------------------------------------------


def _compute_confidence_band(classification: PairClassification) -> str:
    """Derive ``STRONG`` / ``MEDIUM`` / ``LOW`` / ``BLOCKED`` from a pair.

    ``BLOCKED`` short-circuits on any disqualifying signal — false-match
    classification, populated ``resolution_mismatch_reasons``, or absent
    shared entity.  Above ``BLOCKED`` the band falls out of the blended
    ``final_score`` produced by the semantic-pairing layer.
    """
    if classification.pair_type == FALSE_MATCH:
        return "BLOCKED"
    if classification.resolution_mismatch_reasons:
        return "BLOCKED"
    if not classification.shared_entities:
        return "BLOCKED"
    components = classification.pair_score_components or {}
    try:
        final_score = float(components.get("final_score") or 0.0)
    except (TypeError, ValueError):
        final_score = 0.0
    if final_score >= _CONFIDENCE_BAND_STRONG:
        return "STRONG"
    if final_score >= _CONFIDENCE_BAND_MEDIUM:
        return "MEDIUM"
    return "LOW"


def _alert_block_reasons(
    classification: PairClassification,
    *,
    gap: float | None,
    threshold: float,
    confidence_band: str,
    eligible_pair_types: frozenset[str],
) -> list[str]:
    """Every reason this pair must NOT produce a clean ``ALERT``.

    Empty list ⇒ the pair satisfies every guardrail and may ALERT.
    Otherwise the scanner downgrades the status (``WATCH`` when the only
    block is ``below_threshold``, ``BLOCKED`` for everything else) and
    surfaces this list on the record so an operator can audit exactly
    why the alert was withheld.
    """
    blocks: list[str] = []
    if gap is None:
        blocks.append("probability_missing")
    elif gap < threshold:
        blocks.append("below_threshold")
    if classification.pair_type not in eligible_pair_types:
        blocks.append(f"pair_type_not_eligible:{classification.pair_type}")
    if classification.resolution_mismatch_reasons:
        blocks.append("resolution_mismatch_reasons_present")
    if not classification.shared_entities:
        blocks.append("no_shared_entity")
    for reason in classification.reasons or []:
        for prefix in _ALERT_FORBIDDEN_REASON_PREFIXES:
            if reason.startswith(prefix):
                blocks.append(f"forbidden_reason:{prefix}")
                break
    if confidence_band in _BLOCKED_CONFIDENCE_BANDS:
        blocks.append(f"confidence_band_blocked:{confidence_band}")
    seen: set[str] = set()
    out: list[str] = []
    for entry in blocks:
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def build_disagreement_alert(
    polymarket: dict[str, Any],
    kalshi: dict[str, Any],
    *,
    disagreement_threshold: float = DEFAULT_DISAGREEMENT_THRESHOLD,
    embedding_provider: EmbeddingProvider | None = None,
) -> dict[str, Any] | None:
    """Compute a disagreement record for one (poly, kalshi) pair.

    Returns ``None`` when the pair is not a candidate match at all
    (resolution mismatch, different event, false match, missing
    probability, etc.).  Returns a fully-stamped advisory record when
    the pair is eligible — ``disagreement_triggered`` indicates whether
    the probability gap reached the alert threshold AND every
    cross-axis guardrail in :func:`_alert_block_reasons` passed.

    ``embedding_provider`` selects the embedding source used by the
    semantic-pairing layer; defaults to the offline deterministic
    baseline.  The provider's name, model, and availability are
    stamped onto every alert so the operator can see whether a real
    provider was actually consulted.
    """
    provider = embedding_provider or DeterministicEmbeddingProvider()
    classification = classify_pair_resolution(
        polymarket, kalshi, embedding_fn=provider.as_callable()
    )
    poly_prob, poly_prob_source = extract_implied_probability_with_source(polymarket)
    kalshi_prob, kalshi_prob_source = extract_implied_probability_with_source(kalshi)

    confidence_band = _compute_confidence_band(classification)

    if poly_prob is None or kalshi_prob is None:
        gap: float | None = None
    else:
        gap = abs(poly_prob - kalshi_prob)

    block_reasons = _alert_block_reasons(
        classification,
        gap=gap,
        threshold=disagreement_threshold,
        confidence_band=confidence_band,
        eligible_pair_types=_ELIGIBLE_PAIR_TYPES,
    )

    record_base = {
        "pair_id": _pair_id(polymarket, kalshi),
        "polymarket_event_id": polymarket.get("event_id") or polymarket.get("market_id"),
        "kalshi_event_id": kalshi.get("event_id") or kalshi.get("source_market_id"),
        "polymarket_title": polymarket.get("title") or polymarket.get("question"),
        "kalshi_title": kalshi.get("title") or kalshi.get("question"),
        "semantic_similarity": classification.semantic_similarity,
        "embedding_similarity": classification.embedding_similarity,
        "pair_type": classification.pair_type,
        "shared_entities": list(classification.shared_entities),
        "shared_thresholds": list(classification.shared_thresholds),
        "shared_months": list(classification.shared_months),
        "pair_score_components": dict(classification.pair_score_components or {}),
        "resolution_mismatch_reasons": list(
            classification.resolution_mismatch_reasons or []
        ),
        "confidence_band": confidence_band,
        "alert_block_reasons": list(block_reasons),
        "polymarket_probability": poly_prob,
        "kalshi_probability": kalshi_prob,
        "probability_source_polymarket": poly_prob_source,
        "probability_source_kalshi": kalshi_prob_source,
        "disagreement_threshold": disagreement_threshold,
        "signal_class": CROSS_VENUE_SIGNAL_CLASS,
        "customer_label": CUSTOMER_LABEL,
        "human_review_required": True,
        "execution_permission": "ADVISORY_ONLY",
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "reasons": list(classification.reasons),
        **provider.to_status_dict(),
    }

    # False matches do not warrant a record at all.
    if classification.pair_type == FALSE_MATCH:
        return None

    # Diagnostic-only pair types: emit a watch record, never a clean alert.
    if classification.pair_type in _DIAGNOSTIC_PAIR_TYPES:
        record_base["probability_gap"] = round(gap, 4) if gap is not None else None
        record_base["disagreement_triggered"] = False
        record_base["status"] = "DIAGNOSTIC"
        return record_base

    # SAME_EVENT_SAME_RESOLUTION + AMBIGUOUS_MATCH — eligible only when
    # every cross-axis guardrail is satisfied AND the probability gap
    # reaches the alert threshold.  A large gap is necessary but never
    # sufficient.
    if gap is None:
        record_base["probability_gap"] = None
        record_base["disagreement_triggered"] = False
        record_base["status"] = "PROBABILITY_MISSING"
        return record_base

    record_base["probability_gap"] = round(gap, 4)

    if not block_reasons:
        record_base["disagreement_triggered"] = True
        record_base["status"] = "ALERT"
    elif block_reasons == ["below_threshold"]:
        record_base["disagreement_triggered"] = False
        record_base["status"] = "WATCH"
    else:
        # Any non-threshold block (no shared entity, resolution mismatch,
        # forbidden reason token, low/blocked confidence band, ineligible
        # pair_type) downgrades to BLOCKED — never ALERT, never WATCH.
        record_base["disagreement_triggered"] = False
        record_base["status"] = "BLOCKED"

    return record_base


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def scan_disagreements(
    polymarket_rows: list[dict[str, Any]],
    kalshi_rows: list[dict[str, Any]],
    *,
    disagreement_threshold: float = DEFAULT_DISAGREEMENT_THRESHOLD,
    limit: int | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> list[dict[str, Any]]:
    """Run the scanner over an explicit row set; returns advisory records.

    The output preserves *all* eligible/diagnostic pairs (not just
    triggered alerts) so downstream consumers can see why a pair was
    watched but not alerted.
    """
    provider = embedding_provider or DeterministicEmbeddingProvider()
    pairs = iter_pair_candidates(polymarket_rows, kalshi_rows)
    out: list[dict[str, Any]] = []
    for poly, kalshi in pairs:
        rec = build_disagreement_alert(
            poly,
            kalshi,
            disagreement_threshold=disagreement_threshold,
            embedding_provider=provider,
        )
        if rec is None:
            continue
        out.append(rec)
        if limit is not None and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# SQLite + fixture loading
# ---------------------------------------------------------------------------


def _load_from_sqlite(limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        try:
            from scripts.persistence import get_signal_events
        except ModuleNotFoundError:
            from persistence import get_signal_events  # type: ignore[no-redef]
    except Exception:
        return [], []
    poly_raw = get_signal_events(source_name="polymarket", limit=limit)
    kalshi_raw = get_signal_events(source_name="kalshi", limit=limit)
    poly = [
        (row["raw_payload"] if isinstance(row.get("raw_payload"), dict) else _try_json(row.get("raw_payload")))
        for row in poly_raw
    ]
    kalshi = [
        (row["raw_payload"] if isinstance(row.get("raw_payload"), dict) else _try_json(row.get("raw_payload")))
        for row in kalshi_raw
    ]
    return [p for p in poly if isinstance(p, dict)], [k for k in kalshi if isinstance(k, dict)]


def _try_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _load_from_fixture(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    poly = payload.get("polymarket") or []
    kalshi = payload.get("kalshi") or []
    return list(poly), list(kalshi)


def _persist_alerts(alerts: list[dict[str, Any]], fetched_at: str) -> int:
    """Write disagreement alerts into ``signal_events`` (no new table).

    We deliberately persist into the existing signal_events stream under
    a distinct source_name so the existing API + frontend can render
    them without schema changes.  The row is *NOT* a trade record; it
    carries the explicit signal_class + customer label + safety stamps.
    """
    try:
        try:
            from scripts import persistence as _persistence
            from scripts.persistence import insert_signal_event
        except ModuleNotFoundError:
            import persistence as _persistence  # type: ignore[no-redef]
            from persistence import insert_signal_event  # type: ignore[no-redef]
    except Exception:
        return 0
    target_db = getattr(_persistence, "DB_PATH", None)
    written = 0
    for alert in alerts:
        try:
            kwargs: dict[str, Any] = {
                "event_id": alert["pair_id"],
                "source_name": PERSISTENCE_SOURCE_NAME,
                "raw_payload": alert,
                "fetched_at": fetched_at,
            }
            if target_db is not None:
                kwargs["db_path"] = target_db
            if insert_signal_event(**kwargs):
                written += 1
        except Exception:
            continue
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Polymarket × Kalshi cross-venue disagreement scanner. "
            "Advisory-only: emits information-fracture alerts for human "
            "review. Never a buy/sell recommendation."
        )
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Scan and print results without persisting (default).",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Persist triggered alerts into canonical SQLite signal_events "
        "(source_name='prediction_market_disagreement').",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max number of pair records to emit (default 50).",
    )
    p.add_argument(
        "--from-fixtures",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Load polymarket/kalshi rows from a JSON file with two arrays "
            "instead of canonical SQLite. Useful for tests and operator dry-runs."
        ),
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DISAGREEMENT_THRESHOLD,
        help="Probability gap threshold for an alert (default 0.05).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print the alert list as JSON (default human-readable summary).",
    )
    p.add_argument(
        "--embedding-provider",
        choices=("deterministic", "real"),
        default="deterministic",
        help=(
            "Embedding backend used for the semantic-pairing layer. "
            "'deterministic' (default) is offline and reproducible; "
            "'real' attempts the configured HTTP provider and falls "
            "back to deterministic when not configured."
        ),
    )
    p.add_argument(
        "--embedding-model",
        type=str,
        default=None,
        help="Optional model identifier passed to the real embedding provider.",
    )
    p.add_argument(
        "--embedding-timeout-seconds",
        type=float,
        default=None,
        help="Per-call timeout (seconds) for the real embedding provider (default 10).",
    )
    p.add_argument(
        "--strict-embedding",
        action="store_true",
        help=(
            "Fail (instead of silently falling back) when --embedding-provider "
            "real is requested but the provider cannot be constructed."
        ),
    )
    return p


def _summarise(
    alerts: list[dict[str, Any]],
    provider: EmbeddingProvider | None = None,
) -> str:
    triggered = [a for a in alerts if a.get("disagreement_triggered")]
    watching = [a for a in alerts if a.get("status") == "WATCH"]
    diagnostic = [a for a in alerts if a.get("status") == "DIAGNOSTIC"]
    blocked = [a for a in alerts if a.get("status") == "BLOCKED"]
    missing = [a for a in alerts if a.get("status") == "PROBABILITY_MISSING"]
    provider_label = provider.name if provider else "deterministic"
    provider_available = provider.available if provider else True
    lines = [
        "Polymarket × Kalshi disagreement scanner (advisory-only)",
        f"  total_pairs:       {len(alerts)}",
        f"  triggered_alerts:  {len(triggered)}",
        f"  watch_only:        {len(watching)}",
        f"  diagnostic_only:   {len(diagnostic)}",
        f"  blocked:           {len(blocked)}",
        f"  missing_prob:      {len(missing)}",
        f"  embedding:         {provider_label} (available={provider_available})",
        "  contract: ADVISORY_ONLY | HUMAN_REVIEW_REQUIRED | execution_gate=LOCKED | "
        "broker_api_called=False | ai_execution_count=0",
    ]
    if triggered:
        lines.append("  triggered:")
        for alert in triggered[:5]:
            lines.append(
                "    - "
                f"poly={alert.get('polymarket_title')!r} "
                f"kalshi={alert.get('kalshi_title')!r} "
                f"gap={alert.get('probability_gap')}"
            )
    return "\n".join(lines)


def run(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    started_monotonic = _monotonic()
    try:
        provider = resolve_embedding_provider(
            args.embedding_provider,
            model=args.embedding_model,
            timeout_seconds=args.embedding_timeout_seconds,
            strict=args.strict_embedding,
        )
    except EmbeddingProviderUnavailable as exc:
        # Strict mode: surface a clean non-zero exit.  The advisory
        # pipeline is read-only so no rollback is required.
        print(
            json.dumps(
                {
                    "artifact_kind": "prediction_market_disagreement_report",
                    "source_name": PERSISTENCE_SOURCE_NAME,
                    "error": "embedding_provider_unavailable",
                    "detail": str(exc),
                    "read_only_contract": _READ_ONLY_CONTRACT,
                }
            )
        )
        return 2

    if args.from_fixtures:
        poly_rows, kalshi_rows = _load_from_fixture(args.from_fixtures)
    else:
        poly_rows, kalshi_rows = _load_from_sqlite(limit=max(50, args.limit))

    alerts = scan_disagreements(
        poly_rows,
        kalshi_rows,
        disagreement_threshold=args.threshold,
        limit=args.limit,
        embedding_provider=provider,
    )

    persisted = 0
    if args.write:
        # Only persist alerts that actually triggered — diagnostic and
        # watch rows stay in dry-run output.
        triggered = [a for a in alerts if a.get("disagreement_triggered")]
        fetched_at = _now_iso()
        persisted = _persist_alerts(triggered, fetched_at)
        # Record a source_run_log entry so /source-health/summary and
        # /live-sources/status report honest never_run/stale/healthy
        # state for the disagreement source family alongside the other
        # live sources.  Dry-run never writes a run log entry.
        duration_ms = int(max(0.0, (_monotonic() - started_monotonic)) * 1000)
        _log_source_run(
            status="OK",
            fetched_count=int(persisted),
            error_message="",
            timestamp_utc=fetched_at,
            duration_ms=duration_ms,
            extras={
                "total_pairs": len(alerts),
                "triggered_count": sum(
                    1 for a in alerts if a.get("disagreement_triggered")
                ),
                "watch_count": sum(1 for a in alerts if a.get("status") == "WATCH"),
                "diagnostic_count": sum(
                    1 for a in alerts if a.get("status") == "DIAGNOSTIC"
                ),
                "blocked_count": sum(
                    1 for a in alerts if a.get("status") == "BLOCKED"
                ),
                "missing_probability_count": sum(
                    1 for a in alerts if a.get("status") == "PROBABILITY_MISSING"
                ),
                **provider.to_status_dict(),
            },
        )

    output = {
        "artifact_kind": "prediction_market_disagreement_report",
        "source_name": PERSISTENCE_SOURCE_NAME,
        "total_pairs": len(alerts),
        "triggered_count": sum(1 for a in alerts if a.get("disagreement_triggered")),
        "persisted_count": persisted,
        "write_mode": args.write,
        "threshold": args.threshold,
        "alerts": alerts,
        "embedding_provider": provider.to_status_dict(),
        "read_only_contract": _READ_ONLY_CONTRACT,
    }

    if args.json:
        print(json.dumps(output, indent=2, default=str))
    else:
        print(_summarise(alerts, provider))
    return 0


__all__ = [
    "CROSS_VENUE_SIGNAL_CLASS",
    "CUSTOMER_LABEL",
    "PERSISTENCE_SOURCE_NAME",
    "DEFAULT_DISAGREEMENT_THRESHOLD",
    "build_disagreement_alert",
    "scan_disagreements",
    "extract_implied_probability",
    "extract_implied_probability_with_source",
    "run",
]
__all__ += [
    "_alert_block_reasons",
    "_compute_confidence_band",
    "_ALERT_FORBIDDEN_REASON_PREFIXES",
    "_BLOCKED_CONFIDENCE_BANDS",
    "_ELIGIBLE_PAIR_TYPES",
    "_DIAGNOSTIC_PAIR_TYPES",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(run())
