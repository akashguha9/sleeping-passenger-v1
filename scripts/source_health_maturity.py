"""Source-health maturity classification + freshness-weighted scoring.

KANTE_SOURCE_HEALTH_MATURITY
============================

Kanté always knows which team-mate is tired or out of position.  This module is
that awareness for *data sources*: it classifies every provider / adapter / source
on a fine-grained maturity ladder and scores its health from configuration,
freshness, acceptance and canonical-write evidence.

It deliberately sits *beside* :mod:`scripts.source_health_score` (which scores the
live-source registry) rather than replacing it — this layer adds the explicit
maturity vocabulary the Kanté sprint requires and a single freshness-weighted
``source_health_score`` per the documented formula.

Maturity labels
---------------
    DISABLED            — switched off (intentionally)
    CONFIG_MISSING      — required credential / config absent
    MOCK_ONLY           — mock transport; never live
    STUB_SAFE           — safe stub / placeholder; never live
    LIVE_ADVISORY       — live + advisory, not yet outcome-verified
    LIVE_VERIFIED       — live + fresh canonical writes (never mock/stub)
    STALE               — last fresh signal older than its TTL
    DEGRADED            — partial health (low acceptance / write ratio)
    ERROR_SAFE          — last run errored; degraded safely
    NO_FRESH_ROWS       — accepted rows but nothing written canonically
    FILTERED_EMPTY      — rows seen but all filtered out (allowlist)
    ZERO_DECISION_IMPACT — informational only; cannot influence a decision

Mathematics (see docs/KANTE_SCORE_CEILING_AUDIT.md, WORKSTREAM C)
-----------------------------------------------------------------
    age_hours              = (now_utc - last_fresh_signal_at_utc) / 3600
    freshness_ratio        = age_hours / max(freshness_ttl_hours, epsilon)
    freshness_score        = clip(1 - freshness_ratio, 0, 1)
    acceptance_score       = rows_accepted        / max(rows_seen, 1)
    canonical_write_score  = canonical_rows_written / max(rows_accepted, 1)
    configured_enabled_score =
          1.0 if configured and enabled
          0.5 if disabled intentionally
          0.0 otherwise

    source_health_score =
          0.35 * configured_enabled_score
        + 0.25 * freshness_score
        + 0.20 * acceptance_score
        + 0.20 * canonical_write_score

If a source is disabled by default its ``decision_impact`` is NONE and the score
is *informational only*.  A mock / stub source can never be LIVE_VERIFIED.

Hard safety contract
--------------------
Pure module.  No DB, no network, no broker calls.  Every returned dict carries
the advisory-only safety stamps; nothing here executes, sizes real money, or
unlocks a broker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

_EPSILON = 1e-9

# Score weights (must sum to 1.0).
W_CONFIGURED_ENABLED = 0.35
W_FRESHNESS = 0.25
W_ACCEPTANCE = 0.20
W_CANONICAL_WRITE = 0.20

# Maturity labels.
DISABLED = "DISABLED"
CONFIG_MISSING = "CONFIG_MISSING"
MOCK_ONLY = "MOCK_ONLY"
STUB_SAFE = "STUB_SAFE"
LIVE_ADVISORY = "LIVE_ADVISORY"
LIVE_VERIFIED = "LIVE_VERIFIED"
STALE = "STALE"
DEGRADED = "DEGRADED"
ERROR_SAFE = "ERROR_SAFE"
NO_FRESH_ROWS = "NO_FRESH_ROWS"
FILTERED_EMPTY = "FILTERED_EMPTY"
ZERO_DECISION_IMPACT = "ZERO_DECISION_IMPACT"

# Decision-impact vocabulary.
IMPACT_NONE = "NONE"
IMPACT_ADVISORY_CONTEXT_ONLY = "ADVISORY_CONTEXT_ONLY"

# Acceptance / write ratios below this are "degraded".
_DEGRADED_RATIO = 0.50

_PROOF = "SOURCE_HEALTH_MATURITY_ADVISORY_ONLY"


def _clip(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def _f(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness_age_hours(
    last_fresh_signal_at_utc: Any, now_utc: Any = None
) -> float | None:
    """Return ``(now - last_fresh)`` in hours, or None when unknown."""
    last = _parse_utc(last_fresh_signal_at_utc)
    if last is None:
        return None
    now = _parse_utc(now_utc) or datetime.now(timezone.utc)
    return max(0.0, (now - last).total_seconds() / 3600.0)


def configured_enabled_score(
    *, configured: bool, enabled: bool, disabled_intentionally: bool
) -> float:
    """``1`` if configured+enabled, ``0.5`` if intentionally disabled, else 0."""
    if configured and enabled:
        return 1.0
    if disabled_intentionally:
        return 0.5
    return 0.0


def compute_source_health_score(entry: dict[str, Any]) -> dict[str, Any]:
    """Classify and score a single source.

    ``entry`` keys (all optional, conservative defaults)::

        source_name, source_type            str
        configured, enabled                 bool
        disabled_intentionally              bool
        is_mock, is_stub, errored           bool
        last_success_at_utc                 str/datetime
        last_fresh_signal_at_utc            str/datetime
        now_utc                             str/datetime (defaults to now)
        freshness_age_hours                 float (overrides the computed age)
        freshness_ttl_hours                 float (default 24)
        rows_seen, rows_accepted, rows_rejected,
        rows_filtered, canonical_rows_written  int

    Never raises.  Returns the full per-source health dict with safety stamps.
    """
    e = dict(entry or {})
    source_name = str(e.get("source_name") or "unknown")
    source_type = str(e.get("source_type") or "UNKNOWN")
    configured = bool(e.get("configured", False))
    enabled = bool(e.get("enabled", False))
    disabled_intentionally = bool(e.get("disabled_intentionally", False))
    is_mock = bool(e.get("is_mock", False))
    is_stub = bool(e.get("is_stub", False))
    errored = bool(e.get("errored", False))

    ttl = _f(e.get("freshness_ttl_hours"))
    if ttl is None or ttl <= 0:
        ttl = 24.0

    age = _f(e.get("freshness_age_hours"))
    if age is None:
        age = freshness_age_hours(e.get("last_fresh_signal_at_utc"), e.get("now_utc"))

    rows_seen = int(_f(e.get("rows_seen")) or 0)
    rows_accepted = int(_f(e.get("rows_accepted")) or 0)
    rows_rejected = int(_f(e.get("rows_rejected")) or 0)
    rows_filtered = int(_f(e.get("rows_filtered")) or 0)
    canonical_written = int(_f(e.get("canonical_rows_written")) or 0)

    # ----- component scores -------------------------------------------------
    ce_score = configured_enabled_score(
        configured=configured,
        enabled=enabled,
        disabled_intentionally=disabled_intentionally,
    )
    if age is None:
        freshness_ratio = None
        freshness_score = 0.0  # unknown freshness is not trusted
    else:
        freshness_ratio = age / max(ttl, _EPSILON)
        freshness_score = _clip(1.0 - freshness_ratio, 0.0, 1.0)
    acceptance_score = _clip(rows_accepted / max(rows_seen, 1), 0.0, 1.0)
    canonical_write_score = _clip(
        canonical_written / max(rows_accepted, 1), 0.0, 1.0
    )

    health_score = round(
        W_CONFIGURED_ENABLED * ce_score
        + W_FRESHNESS * freshness_score
        + W_ACCEPTANCE * acceptance_score
        + W_CANONICAL_WRITE * canonical_write_score,
        6,
    )

    # ----- maturity classification (ordered by safety precedence) -----------
    stale = age is not None and freshness_ratio is not None and freshness_ratio > 1.0
    label = _classify(
        configured=configured,
        enabled=enabled,
        disabled_intentionally=disabled_intentionally,
        is_mock=is_mock,
        is_stub=is_stub,
        errored=errored,
        stale=stale,
        rows_seen=rows_seen,
        rows_accepted=rows_accepted,
        rows_filtered=rows_filtered,
        canonical_written=canonical_written,
        acceptance_score=acceptance_score,
        canonical_write_score=canonical_write_score,
    )

    # Disabled / config-missing / informational sources never influence a
    # decision; live ones provide advisory context only.
    no_impact_labels = {
        DISABLED,
        CONFIG_MISSING,
        ERROR_SAFE,
        ZERO_DECISION_IMPACT,
        FILTERED_EMPTY,
        NO_FRESH_ROWS,
    }
    decision_impact = (
        IMPACT_NONE if label in no_impact_labels else IMPACT_ADVISORY_CONTEXT_ONLY
    )
    # Disabled-by-default => the score is informational only.
    score_informational_only = label in {DISABLED, CONFIG_MISSING}

    proof_status = (
        f"{label}_VERIFIED_FRESH_CANONICAL"
        if label == LIVE_VERIFIED
        else f"{label}_ADVISORY_ONLY"
    )

    out: dict[str, Any] = {
        "source_name": source_name,
        "source_type": source_type,
        "configured": configured,
        "enabled": enabled,
        "maturity_label": label,
        "last_success_at_utc": e.get("last_success_at_utc"),
        "last_fresh_signal_at_utc": e.get("last_fresh_signal_at_utc"),
        "freshness_age_hours": None if age is None else round(age, 6),
        "freshness_ttl_hours": round(ttl, 6),
        "freshness_ratio": None if freshness_ratio is None else round(freshness_ratio, 6),
        "freshness_score": round(freshness_score, 6),
        "rows_seen": rows_seen,
        "rows_accepted": rows_accepted,
        "rows_rejected": rows_rejected,
        "rows_filtered": rows_filtered,
        "canonical_rows_written": canonical_written,
        "configured_enabled_score": round(ce_score, 6),
        "acceptance_score": round(acceptance_score, 6),
        "canonical_write_score": round(canonical_write_score, 6),
        "source_health_score": health_score,
        "score_informational_only": score_informational_only,
        "decision_impact": decision_impact,
        "proof_status": proof_status,
        # Hard, unconditional safety stamps.
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_gate": "LOCKED",
        "real_money_sizing_impact": "PROHIBITED",
        "real_money_weight_allowed": False,
    }
    return out


def _classify(
    *,
    configured: bool,
    enabled: bool,
    disabled_intentionally: bool,
    is_mock: bool,
    is_stub: bool,
    errored: bool,
    stale: bool,
    rows_seen: int,
    rows_accepted: int,
    rows_filtered: int,
    canonical_written: int,
    acceptance_score: float,
    canonical_write_score: float,
) -> str:
    """Assign the maturity label by safety precedence (safest verdict first)."""
    if disabled_intentionally or not enabled:
        return DISABLED
    if not configured:
        return CONFIG_MISSING
    if errored:
        return ERROR_SAFE
    # Mock / stub can NEVER be LIVE_VERIFIED — surfaced before any "live" verdict.
    if is_mock:
        return MOCK_ONLY
    if is_stub:
        return STUB_SAFE
    if stale:
        return STALE
    if rows_seen > 0 and rows_accepted == 0 and rows_filtered > 0:
        return FILTERED_EMPTY
    if rows_accepted > 0 and canonical_written == 0:
        return NO_FRESH_ROWS
    if rows_seen == 0 and rows_accepted == 0:
        return ZERO_DECISION_IMPACT
    if acceptance_score < _DEGRADED_RATIO or canonical_write_score < _DEGRADED_RATIO:
        return DEGRADED
    # Fresh canonical writes from a live, configured, non-mock source.
    if canonical_written > 0 and not stale:
        return LIVE_VERIFIED
    return LIVE_ADVISORY


def build_source_health_maturity_summary(
    sources: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Classify and score a list of sources and summarise label counts.

    Honest when empty: reports ``data_available = False`` rather than an
    invented all-clear.  Carries the advisory-only safety stamps.
    """
    scored = [compute_source_health_score(s) for s in (sources or [])]
    label_counts: dict[str, int] = {}
    for s in scored:
        label_counts[s["maturity_label"]] = label_counts.get(s["maturity_label"], 0) + 1

    live_verified = [s for s in scored if s["maturity_label"] == LIVE_VERIFIED]
    avg_score = (
        round(sum(s["source_health_score"] for s in scored) / len(scored), 6)
        if scored
        else 0.0
    )

    out: dict[str, Any] = {
        "report": "source_health_maturity_summary",
        "data_available": bool(scored),
        "source_count": len(scored),
        "label_counts": label_counts,
        "live_verified_count": len(live_verified),
        "average_source_health_score": avg_score,
        "sources": scored,
        "operator_message": (
            f"{len(scored)} source(s) classified; {len(live_verified)} live-verified."
            if scored
            else "No sources to classify. Source-health maturity unavailable."
        ),
    }
    out.update(_contract.advisory_safety_stamps())
    out["advisory_only"] = True
    out["real_money_sizing_impact"] = "PROHIBITED"
    out["proof_status"] = _PROOF
    return out


__all__ = [
    "DISABLED",
    "CONFIG_MISSING",
    "MOCK_ONLY",
    "STUB_SAFE",
    "LIVE_ADVISORY",
    "LIVE_VERIFIED",
    "STALE",
    "DEGRADED",
    "ERROR_SAFE",
    "NO_FRESH_ROWS",
    "FILTERED_EMPTY",
    "ZERO_DECISION_IMPACT",
    "IMPACT_NONE",
    "IMPACT_ADVISORY_CONTEXT_ONLY",
    "freshness_age_hours",
    "configured_enabled_score",
    "compute_source_health_score",
    "build_source_health_maturity_summary",
]
