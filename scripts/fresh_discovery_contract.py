"""Fresh Discovery Contract — the strict provenance gate that keeps stale,
static, fallback, prior, Moltbook, fixture, seed, prompt-example and
cache-only names out of the Fresh Discovery Board.

Why this module exists
----------------------
The research/diagnostic discovery universe (``U_today``) ALWAYS injects the
static minimum universe, yesterday's candidates and the signal-ledger
watchlist so the *research* gate is never starved (see
``fresh_market_discovery.build_discovery_universe``). That is correct for
research, but it means wiping past trade logs does NOT stop old names
(NVDA, AMZN, RHM.DE, AIR.PA, SAP.DE, NOC, GLD, ZIM, EWG, INFY, BHP, ...) from
re-appearing — those names live in *code*, not in the logs.

This module is the fail-closed gate the operator asked for. A ticker may appear
on the Fresh Discovery Board ONLY if it is backed by live, verified,
current-session evidence:

    fresh_discovery_allowed =
        source_health == "VERIFIED_LIVE"
        AND is_live == true
        AND generated_at / session_date is current
        AND evidence_type NOT IN BLOCKED_EVIDENCE_TYPES
        AND live_evidence_count >= 1

Everything else is research/diagnostic-only and is quarantined with an explicit
per-ticker provenance reason. Fallback names are never ranked, never promoted,
never mixed with live candidates, and never enter the five-model synthesis as
fresh candidates. If no live candidate survives the gate the contract returns
``NO_FRESH_DISCOVERY_GENERATED`` rather than padding the board with stale names.

Advisory-only. No broker, no order generation, no position sizing. Pure module:
importing it has no side effects and it never mutates any file. We never
fabricate live data — a missing/UNVERIFIED feed degrades the board to empty.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import normalize_ticker
    from scripts.minimum_daily_universe import minimum_universe_tickers
    from scripts.runtime_common import SIGNAL_LEDGER_PATH, load_json_file
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import normalize_ticker
    from minimum_daily_universe import minimum_universe_tickers
    from runtime_common import SIGNAL_LEDGER_PATH, load_json_file


# ---------------------------------------------------------------------------
# Contract vocabulary
# ---------------------------------------------------------------------------

VERIFIED_LIVE = "VERIFIED_LIVE"
STATUS_OK = "FRESH_DISCOVERY_OK"
STATUS_NONE = "NO_FRESH_DISCOVERY_GENERATED"
VIOLATION_CODE = "DISCOVERY_PROVENANCE_VIOLATION"

# Evidence types that may NEVER appear on the Fresh Discovery Board.
BLOCKED_EVIDENCE_TYPES: frozenset[str] = frozenset(
    {
        "STATIC_UNIVERSE_FALLBACK",
        "STATIC_OR_EMPTY_FALLBACK",
        "EMPTY_FALLBACK",
        "PRIOR_CANDIDATE",
        "MOLTBOOK_MEMORY",
        "TEST_FIXTURE",
        "SEED_DATA",
        "EXAMPLE_PROMPT",
        "CACHE_ONLY",
    }
)

# Evidence types that represent genuine live, current-session evidence.
LIVE_EVIDENCE_TYPES: frozenset[str] = frozenset(
    {"LIVE_PRICE_MOVER", "LIVE_NEWS_EVENT", "LIVE_FILING_EVENT"}
)

# Provider strings emitted by the honest fallback builders — never live.
_FALLBACK_PROVIDERS: frozenset[str] = frozenset(
    {"STATIC_UNIVERSE_FALLBACK", "STATIC_OR_EMPTY_FALLBACK", "EMPTY_FALLBACK"}
)

# source_health values that are explicitly NOT verified-live.
_UNVERIFIED_HEALTH: frozenset[str] = frozenset(
    {"", "UNVERIFIED", "MISSING", "MISSING_OR_UNVERIFIED", "STALE", "COLLAPSED", "EMPTY", "UNKNOWN"}
)

# Record-level source_health values that, paired with is_live, count as live.
_VERIFIED_HEALTH: frozenset[str] = frozenset(
    {"VERIFIED_LIVE", "LIVE", "OK", "VERIFIED", "PARTIAL", "FRESH", "LIVE_VERIFIED"}
)

# freshness markers that mean "observed in the current session".
_FRESH_TODAY_MARKERS: frozenset[str] = frozenset(
    {"FRESH_TODAY", "UPDATED_TODAY", "LIVE", "VERIFIED_LIVE", "FRESH", "TODAY"}
)

# Substring markers that flag synthetic test / seed / prompt-example origins so
# they can never be mistaken for live evidence even if mislabelled is_live.
_FIXTURE_MARKERS = ("FIXTURE", "TEST", "MOCK", "DEMO", "SYNTHETIC", "DUMMY")
_SEED_MARKERS = ("SEED",)
_EXAMPLE_MARKERS = ("EXAMPLE", "SAMPLE", "PLACEHOLDER", "PROMPT")

# Priority order used to report the single most-relevant blocking evidence type
# for a name backed only by non-live sources. The provenance flags
# (from_cache / from_fallback / from_moltbook / from_trade_log) always carry the
# full picture; evidence_type is the primary label.
_NONLIVE_PRIORITY = (
    "EXAMPLE_PROMPT",
    "TEST_FIXTURE",
    "SEED_DATA",
    "PRIOR_CANDIDATE",
    "MOLTBOOK_MEMORY",
    "STATIC_OR_EMPTY_FALLBACK",
    "EMPTY_FALLBACK",
    "STATIC_UNIVERSE_FALLBACK",
    "CACHE_ONLY",
)

# Priority among live source kinds when a name has more than one live source.
_LIVE_PRIORITY = ("LIVE_PRICE_MOVER", "LIVE_FILING_EVENT", "LIVE_NEWS_EVENT")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _has_marker(blob: str, markers: tuple[str, ...]) -> bool:
    return any(marker in blob for marker in markers)


def _record_date(record: dict[str, Any]) -> str | None:
    """Best-effort YYYY-MM-DD date from a record's timestamp fields."""
    for key in ("last_live_seen_date", "session_date", "run_date", "timestamp_utc", "generated_at_utc", "observed_at"):
        value = record.get(key)
        if value:
            text = str(value).strip()
            if len(text) >= 10:
                return text[:10]
    return None


def record_is_live(record: dict[str, Any]) -> bool:
    """True only if a single payload record is genuine live, verified evidence.

    Fail-closed: a record that *claims* ``is_live`` but is labelled with a
    fallback provider, an unverified ``source_health`` or a synthetic
    fixture/seed/example marker is NOT live.
    """
    if not isinstance(record, dict):
        return False
    provider = str(record.get("provider") or "").upper()
    source = str(record.get("source") or "").upper()
    blob = f"{provider} {source}"
    if provider in _FALLBACK_PROVIDERS:
        return False
    if _has_marker(blob, _FIXTURE_MARKERS + _SEED_MARKERS + _EXAMPLE_MARKERS):
        return False
    if record.get("is_live") is not True:
        return False
    health = str(record.get("source_health") or "").upper()
    if health in _UNVERIFIED_HEALTH or health not in _VERIFIED_HEALTH:
        return False
    freshness = str(record.get("freshness") or "").upper()
    # A freshness field, when present, must indicate the current session.
    if freshness and freshness not in _FRESH_TODAY_MARKERS:
        return False
    return True


def _fallback_evidence_type(record: dict[str, Any], default: str) -> str:
    """Classify a non-live payload record into a blocked evidence type."""
    provider = str(record.get("provider") or "").upper()
    source = str(record.get("source") or "").upper()
    blob = f"{provider} {source}"
    if _has_marker(blob, _EXAMPLE_MARKERS):
        return "EXAMPLE_PROMPT"
    if _has_marker(blob, _FIXTURE_MARKERS):
        return "TEST_FIXTURE"
    if _has_marker(blob, _SEED_MARKERS):
        return "SEED_DATA"
    if provider in _FALLBACK_PROVIDERS:
        return provider
    # A non-live record with a real-looking provider but no freshness is, at
    # best, a cached read — never fresh.
    return "CACHE_ONLY" if provider else default


def _live_evidence_type(record: dict[str, Any], source_payload: str) -> str:
    return {
        "today_price_movers": "LIVE_PRICE_MOVER",
        "today_news_events": "LIVE_NEWS_EVENT",
        "today_filings_events": "LIVE_FILING_EVENT",
    }.get(source_payload, "LIVE_PRICE_MOVER")


def _scan_source(
    ticker: str,
    rows: list[dict[str, Any]],
    source_payload: str,
    fallback_default: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if normalize_ticker(row.get("ticker") or row.get("symbol")) != ticker:
            continue
        live = record_is_live(row)
        out.append(
            {
                "source_payload": source_payload,
                "is_live": live,
                "evidence_type": (
                    _live_evidence_type(row, source_payload)
                    if live
                    else _fallback_evidence_type(row, fallback_default)
                ),
                "source_health": VERIFIED_LIVE if live else str(row.get("source_health") or "UNVERIFIED").upper(),
                "provider": str(row.get("provider") or "").upper(),
                "seen_date": _record_date(row),
            }
        )
    return out


def signal_ledger_watchlist(signal_ledger_path: Path | None = None) -> list[str]:
    """Tickers carried as WATCHLIST in the (historical) Moltbook signal ledger."""
    payload = load_json_file(signal_ledger_path or SIGNAL_LEDGER_PATH, default=[])
    out: list[str] = []
    if isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            ticker = normalize_ticker(row.get("ticker") or row.get("symbol"))
            if ticker and ticker not in out:
                out.append(ticker)
    return out


def _resolve_session_date(payload: dict[str, Any]) -> str:
    run_date = payload.get("verified_holdings", {}).get("run_date")
    if run_date:
        return str(run_date)[:10]
    snap = payload.get("market_snapshot", {}).get("snapshot_timestamp_utc")
    if snap:
        return str(snap)[:10]
    try:
        from scripts.runtime_common import utc_timestamp
    except ModuleNotFoundError:  # pragma: no cover
        from runtime_common import utc_timestamp
    return utc_timestamp()[:10]


# ---------------------------------------------------------------------------
# Per-ticker provenance
# ---------------------------------------------------------------------------

def derive_ticker_provenance(
    ticker: str,
    payload: dict[str, Any],
    truth_gate: dict[str, Any],
    current_session_date: str,
    *,
    static_universe: set[str] | None = None,
    ledger_watchlist: set[str] | None = None,
    model_candidates: set[str] | None = None,
    example_prompt_tickers: set[str] | None = None,
) -> dict[str, Any]:
    """Build the full provenance record for one ticker (pure, null-safe)."""
    ticker = normalize_ticker(ticker)

    static_set = static_universe if static_universe is not None else set(minimum_universe_tickers())
    ledger_set = ledger_watchlist or set()
    model_set = {normalize_ticker(t) for t in (model_candidates or set())}
    example_set = {normalize_ticker(t) for t in (example_prompt_tickers or set())}

    yesterday_final = set(payload["yesterday_candidates"]["final_candidates"])
    yesterday_watch = set(payload["yesterday_candidates"]["watchlist"])
    closed_or_sold = set(truth_gate.get("closed_or_sold", []))
    do_not_treat = set(truth_gate.get("do_not_treat_as_open", []))
    stale_ledger = set(truth_gate.get("stale_ledger_tickers", []))

    entries: list[dict[str, Any]] = []
    entries += _scan_source(ticker, payload["price_movers"]["movers"], "today_price_movers", "STATIC_UNIVERSE_FALLBACK")
    entries += _scan_source(ticker, payload["news_events"]["events"], "today_news_events", "STATIC_OR_EMPTY_FALLBACK")
    entries += _scan_source(ticker, payload["filings_events"]["events"], "today_filings_events", "EMPTY_FALLBACK")

    live_entries = [e for e in entries if e["is_live"]]
    live_evidence_count = len(live_entries)
    has_live = bool(live_entries)

    # Provenance flags — full picture regardless of the chosen evidence_type.
    in_yesterday = ticker in yesterday_final or ticker in yesterday_watch
    in_ledger = ticker in ledger_set or ticker in stale_ledger
    in_trade_log = ticker in closed_or_sold
    from_cache = in_yesterday and not has_live
    from_moltbook = in_ledger
    from_trade_log = in_trade_log
    from_fallback = (not has_live) and (
        any(not e["is_live"] for e in entries) or ticker in static_set or ticker in example_set or ticker in model_set
    )

    if has_live:
        chosen = sorted(
            live_entries,
            key=lambda e: _LIVE_PRIORITY.index(e["evidence_type"]) if e["evidence_type"] in _LIVE_PRIORITY else 99,
        )[0]
        evidence_type = chosen["evidence_type"]
        source_payload = chosen["source_payload"]
        source_health = VERIFIED_LIVE
        is_live = True
        live_dates = sorted(e["seen_date"] for e in live_entries if e["seen_date"])
        last_live_seen_date = live_dates[-1] if live_dates else current_session_date
        generated_at = last_live_seen_date
    else:
        # Choose the single most-relevant blocking evidence type to report.
        present: dict[str, str] = {}
        for e in entries:
            present.setdefault(e["evidence_type"], e["source_payload"])
        if ticker in example_set or ticker in model_set:
            present.setdefault("EXAMPLE_PROMPT", "model_or_prompt_examples")
        if in_yesterday:
            present.setdefault("PRIOR_CANDIDATE", "yesterday_final_candidates")
        if in_ledger:
            present.setdefault("MOLTBOOK_MEMORY", "signal_ledger")
        if ticker in static_set:
            present.setdefault("STATIC_UNIVERSE_FALLBACK", "static_universe")
        evidence_type = next((t for t in _NONLIVE_PRIORITY if t in present), "CACHE_ONLY")
        source_payload = present.get(evidence_type, "unknown")
        # Report the raw (non-live) health if a payload row carried one.
        raw_health = next((e["source_health"] for e in entries if not e["is_live"]), "UNVERIFIED")
        source_health = raw_health
        is_live = False
        last_live_seen_date = None
        generated_at = None

    prov = {
        "ticker": ticker,
        "source_payload": source_payload,
        "source_health": source_health,
        "is_live": is_live,
        "generated_at": generated_at,
        "evidence_type": evidence_type,
        "live_evidence_count": live_evidence_count,
        "last_live_seen_date": last_live_seen_date,
        "from_cache": bool(from_cache),
        "from_fallback": bool(from_fallback),
        "from_moltbook": bool(from_moltbook),
        "from_trade_log": bool(from_trade_log),
    }
    allowed, exclusion_reason = _evaluate_allowed(prov, current_session_date)
    prov["allowed_in_fresh_discovery"] = allowed
    prov["exclusion_reason"] = exclusion_reason
    return prov


def _session_is_current(prov: dict[str, Any], current_session_date: str) -> bool:
    return bool(prov.get("last_live_seen_date")) and prov["last_live_seen_date"] == current_session_date


def fresh_discovery_allowed(prov: dict[str, Any], current_session_date: str) -> bool:
    """The Fresh Discovery Contract predicate, verbatim from the spec."""
    return (
        prov.get("source_health") == VERIFIED_LIVE
        and prov.get("is_live") is True
        and _session_is_current(prov, current_session_date)
        and prov.get("evidence_type") not in BLOCKED_EVIDENCE_TYPES
        and prov.get("evidence_type") in LIVE_EVIDENCE_TYPES
        and int(prov.get("live_evidence_count") or 0) >= 1
        and prov.get("from_fallback") is False
        and prov.get("from_cache") is False
    )


def candidate_is_stale(prov: dict[str, Any], current_session_date: str) -> bool:
    """A candidate is stale unless revalidated by fresh live evidence today."""
    if prov.get("source_health") != VERIFIED_LIVE:
        return True
    if prov.get("is_live") is not True:
        return True
    last = prov.get("last_live_seen_date")
    if not last:
        return True
    return str(last) < str(current_session_date)


def _evaluate_allowed(prov: dict[str, Any], current_session_date: str) -> tuple[bool, str]:
    if fresh_discovery_allowed(prov, current_session_date):
        return True, ""
    reasons: list[str] = []
    if prov.get("source_health") != VERIFIED_LIVE:
        reasons.append(f"source_health={prov.get('source_health')} (need VERIFIED_LIVE)")
    if prov.get("is_live") is not True:
        reasons.append("is_live=false")
    if not _session_is_current(prov, current_session_date):
        reasons.append(
            f"last_live_seen_date={prov.get('last_live_seen_date')} not current session {current_session_date}"
        )
    if prov.get("evidence_type") in BLOCKED_EVIDENCE_TYPES:
        reasons.append(f"evidence_type={prov.get('evidence_type')} is blocked")
    elif prov.get("evidence_type") not in LIVE_EVIDENCE_TYPES:
        reasons.append(f"evidence_type={prov.get('evidence_type')} is not a live source")
    if int(prov.get("live_evidence_count") or 0) < 1:
        reasons.append("live_evidence_count=0")
    if prov.get("from_fallback"):
        reasons.append("from_fallback=true")
    if prov.get("from_cache"):
        reasons.append("from_cache=true without live revalidation")
    return False, "; ".join(reasons) or "blocked"


# ---------------------------------------------------------------------------
# Regression guard
# ---------------------------------------------------------------------------

class DiscoveryProvenanceViolation(RuntimeError):
    """Raised when the Fresh Discovery Board contains a non-live name."""


def detect_provenance_violations(board: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Independently re-validate the final board (defense in depth).

    A board entry is a violation if it is from_fallback, from_cache without live
    revalidation, or carries a non-VERIFIED_LIVE source_health / blocked
    evidence type. By construction the board should be clean; this guard fails
    closed if any code path ever lets a stale name through.
    """
    violations: list[dict[str, Any]] = []
    for prov in board:
        bad: list[str] = []
        if prov.get("from_fallback"):
            bad.append("from_fallback")
        if prov.get("from_cache") and prov.get("is_live") is not True:
            bad.append("from_cache_without_live_revalidation")
        if prov.get("source_health") != VERIFIED_LIVE:
            bad.append(f"source_health={prov.get('source_health')}")
        if prov.get("is_live") is not True:
            bad.append("is_live_false")
        if prov.get("evidence_type") in BLOCKED_EVIDENCE_TYPES:
            bad.append(f"blocked_evidence_type={prov.get('evidence_type')}")
        if bad:
            violations.append({"ticker": prov.get("ticker"), "violations": bad, "code": VIOLATION_CODE})
    return violations


def assert_no_provenance_violation(contract: dict[str, Any]) -> None:
    """Raise ``DiscoveryProvenanceViolation`` if the run is contaminated."""
    if contract.get("discovery_provenance_violation"):
        offenders = ", ".join(v["ticker"] for v in contract.get("provenance_violations", []))
        raise DiscoveryProvenanceViolation(f"{VIOLATION_CODE}: {offenders}")


# ---------------------------------------------------------------------------
# NO_FRESH_DISCOVERY_GENERATED
# ---------------------------------------------------------------------------

def _payload_health(rows: list[dict[str, Any]]) -> str:
    if any(record_is_live(r) for r in rows or []):
        return VERIFIED_LIVE
    for r in rows or []:
        health = str(r.get("source_health") or "").upper()
        if health:
            return health
    return "UNVERIFIED"


def _next_required_fix(failed_payloads: list[str]) -> str:
    if not failed_payloads:
        return "No fix required."
    feeds = ", ".join(failed_payloads)
    return (
        "Wire at least one live, current-session provider so a payload reports "
        f"is_live=true AND source_health=VERIFIED_LIVE (failed: {feeds}). Static "
        "fallback is research/diagnostic-only and may never populate the Fresh "
        "Discovery Board."
    )


def build_no_fresh_discovery(
    payload: dict[str, Any],
    blocked_fallback_names: list[str],
) -> dict[str, Any]:
    source_health_by_payload = {
        "today_market_snapshot": str(payload["market_snapshot"]["source_health"] or "UNVERIFIED").upper(),
        "today_price_movers": _payload_health(payload["price_movers"]["movers"]),
        "today_news_events": _payload_health(payload["news_events"]["events"]),
        "today_filings_events": _payload_health(payload["filings_events"]["events"]),
    }
    failed_payloads = [name for name, health in source_health_by_payload.items() if health != VERIFIED_LIVE]
    return {
        "status": STATUS_NONE,
        "reason": (
            "No ticker is backed by live, verified, current-session evidence. "
            "Every discovery source is on static/empty fallback, so the Fresh "
            "Discovery Board is intentionally empty (fail-closed). Stale/static "
            "names were NOT used to populate it."
        ),
        "failed_payloads": failed_payloads,
        "source_health_by_payload": source_health_by_payload,
        "live_candidate_count": 0,
        "fallback_candidate_count": len(blocked_fallback_names),
        "blocked_fallback_names": list(blocked_fallback_names),
        "next_required_fix": _next_required_fix(failed_payloads),
    }


# ---------------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------------

def build_fresh_discovery_contract(
    payload: dict[str, Any],
    discovery: dict[str, Any],
    truth_gate: dict[str, Any],
    *,
    current_session_date: str | None = None,
    model_candidates: list[str] | None = None,
    example_prompt_tickers: list[str] | None = None,
    signal_ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Apply the Fresh Discovery Contract over the research discovery universe.

    Returns a self-contained object holding the strict ``fresh_discovery_board``,
    the per-ticker provenance report, the stale-revalidation quarantine, the
    ``NO_FRESH_DISCOVERY_GENERATED`` block (when empty) and the
    ``DISCOVERY_PROVENANCE_VIOLATION`` regression guard result.
    """
    current_session_date = current_session_date or _resolve_session_date(payload)
    universe = list(discovery.get("discovery_universe", []))
    static_universe = set(minimum_universe_tickers())
    ledger_set = set(signal_ledger_watchlist(signal_ledger_path))
    model_set = {normalize_ticker(t) for t in (model_candidates or [])}
    example_set = {normalize_ticker(t) for t in (example_prompt_tickers or [])}

    provenance_report: list[dict[str, Any]] = []
    for ticker in universe:
        provenance_report.append(
            derive_ticker_provenance(
                ticker,
                payload,
                truth_gate,
                current_session_date,
                static_universe=static_universe,
                ledger_watchlist=ledger_set,
                model_candidates=model_set,
                example_prompt_tickers=example_set,
            )
        )

    fresh_board = [p for p in provenance_report if p["allowed_in_fresh_discovery"]]
    blocked = [p for p in provenance_report if not p["allowed_in_fresh_discovery"]]
    stale_revalidation = [p for p in blocked if candidate_is_stale(p, current_session_date)]
    blocked_fallback_names = sorted({p["ticker"] for p in blocked if p["from_fallback"]})

    violations = detect_provenance_violations(fresh_board)
    discovery_provenance_violation = bool(violations)

    live_candidate_count = len(fresh_board)
    if live_candidate_count == 0:
        status = STATUS_NONE
        no_fresh = build_no_fresh_discovery(payload, blocked_fallback_names)
    else:
        status = STATUS_OK
        no_fresh = None

    return {
        "current_session_date": current_session_date,
        "status": status,
        "fresh_discovery_board": [p["ticker"] for p in fresh_board],
        "fresh_discovery_provenance": fresh_board,
        "live_candidate_count": live_candidate_count,
        "fallback_candidate_count": len(blocked_fallback_names),
        "blocked_fallback_names": blocked_fallback_names,
        "stale_revalidation_needed": [p["ticker"] for p in stale_revalidation],
        "provenance_report": provenance_report,
        "no_fresh_discovery": no_fresh,
        "discovery_provenance_violation": discovery_provenance_violation,
        "provenance_violations": violations,
        "blocked_evidence_types": sorted(BLOCKED_EVIDENCE_TYPES),
        "live_evidence_types": sorted(LIVE_EVIDENCE_TYPES),
        "safety": advisory_safety_stamps(),
    }


__all__ = [
    "VERIFIED_LIVE",
    "STATUS_OK",
    "STATUS_NONE",
    "VIOLATION_CODE",
    "BLOCKED_EVIDENCE_TYPES",
    "LIVE_EVIDENCE_TYPES",
    "DiscoveryProvenanceViolation",
    "record_is_live",
    "signal_ledger_watchlist",
    "derive_ticker_provenance",
    "fresh_discovery_allowed",
    "candidate_is_stale",
    "detect_provenance_violations",
    "assert_no_provenance_violation",
    "build_no_fresh_discovery",
    "build_fresh_discovery_contract",
]
