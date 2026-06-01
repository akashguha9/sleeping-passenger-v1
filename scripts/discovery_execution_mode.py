"""Three-lane mode model: SURVIVAL vs DISCOVERY vs EXECUTION.

The MVP collapsed from "discovery mode" into "survival mode": when the price
layer was weak the whole system suppressed candidate output, so the operator
saw a dead board. This module fixes the conceptual error:

    DISCOVERY MODE != EXECUTION MODE != SURVIVAL MODE

Discovery is allowed to surface research candidates even when execution is
blocked. Execution (advisory paper BUY / PROBE_BUY *classification*) requires a
clean price layer, clean portfolio truth, clean phantom state, clean leverage,
clean exit debt, and healthy sources. Bad execution data blocks BUY — it never
blocks DISCOVERED / WATCHLIST / CONDITIONAL_PROBE.

ADVISORY-ONLY INVARIANT (unchanged by this module):
  * No broker calls, no order placement, no execution route.
  * BUY / PROBE_BUY are advisory paper-signal classifications only.
  * Human execution is always required; the execution gate stays LOCKED.
  * Operator override is never treated as a model-approved buy.
  * Leverage conflicts are SURFACED, never silently resolved.

This is a pure module: no I/O, no network, no file mutation, no fabrication.
It composes existing primitives (``leverage_policy``, ``advisory_contract``,
``daily_payload.normalize_ticker``) and the central thresholds from
``discovery_execution_config``.
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import normalize_ticker
    from scripts.discovery_execution_config import load_discovery_execution_config
    from scripts.leverage_policy import get_max_allowed_leverage
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import normalize_ticker
    from discovery_execution_config import load_discovery_execution_config
    from leverage_policy import get_max_allowed_leverage


# Recon statuses that mean a stop-hit / close is RESOLVED (no exit debt).
CLOSED_RECON_STATES: frozenset[str] = frozenset(
    {"STOP_CLOSED", "CLOSED", "CLOSE_TRADE_SYNCED", "CLOSED_RECONCILED"}
)
# Actions whose presence demands a close.
CLOSE_REQUIRED_ACTIONS: frozenset[str] = frozenset(
    {"CLOSE_TRADE", "SELL_100%", "SELL_100", "STOP_HIT"}
)

# Discovery-mode classifications (never an execution unlock).
DISCOVERY_CLASSIFICATIONS: tuple[str, ...] = (
    "NOISE_OR_STALE",
    "WEAK_DISCOVERY",
    "DISCOVERED",
    "WATCHLIST",
    "STRONG_WATCHLIST",
    "CONDITIONAL_PROBE_CANDIDATE_EXECUTION_BLOCKED",
    "HIGH_CONVICTION_WATCHLIST_EXECUTION_BLOCKED",
    "PHANTOM_QUARANTINE",
)
# Execution-mode classifications (only when execution_allowed=true + proof).
EXECUTION_CLASSIFICATIONS: tuple[str, ...] = ("PROBE_BUY", "BUY")


def clamp01(value: Any) -> float:
    """clamp01(x) = min(1, max(0, x)). Non-numeric -> 0.0."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, num))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _norm(ticker: Any) -> str:
    try:
        return normalize_ticker(ticker)
    except Exception:  # pragma: no cover - normalize is defensive
        return str(ticker or "").strip().upper()


# ---------------------------------------------------------------------------
# 1. Price validity + coverage
# ---------------------------------------------------------------------------
def valid_price_flag(
    row: dict[str, Any],
    *,
    non_executable_sources: Iterable[str] | None = None,
    max_age_minutes: float | None = None,
    config: dict[str, Any] | None = None,
) -> bool:
    """valid_price(t): price>0, executable source, fresh enough.

    A static / unverified / mock / unknown source can NEVER be a valid price.
    An explicit ``valid_price=False`` on the row is always honoured.
    """
    cfg = config or load_discovery_execution_config()
    sources = {
        str(s).upper()
        for s in (non_executable_sources or cfg["non_executable_price_sources"])
    }
    if row.get("valid_price") is False:
        return False
    price = _safe_float(row.get("price"))
    if price is None or price <= 0:
        return False
    source = str(
        row.get("source") or row.get("provider") or row.get("source_health") or ""
    ).strip().upper()
    if source in sources:
        return False
    if max_age_minutes is not None:
        age = _safe_float(row.get("age_minutes"))
        if age is None or age > float(max_age_minutes):
            return False
    return True


def price_coverage(
    rows: list[dict[str, Any]],
    *,
    max_age_minutes: float | None = None,
    config: dict[str, Any] | None = None,
) -> float:
    """price_coverage(U) = |{t in U : valid_price(t)=1}| / max(1, |U|)."""
    cfg = config or load_discovery_execution_config()
    rows = list(rows or [])
    valid = sum(
        1
        for r in rows
        if valid_price_flag(r, max_age_minutes=max_age_minutes, config=cfg)
    )
    return round(valid / max(1, len(rows)), 4)


# ---------------------------------------------------------------------------
# 2. Portfolio truth / open-position reconciliation
# ---------------------------------------------------------------------------
def resolve_open_positions(
    sheet_rows: list[dict[str, Any]],
    verified_open_tickers: Iterable[str],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Canonical open-position resolver (Acceptance B).

    ``sheet_rows`` are sheet / trade-ledger rows carrying a ticker and a
    ``trade_state`` (or ``status``). Verified holdings are canonical truth.

    Returns canonical/sheet/verified open sets, the symmetric difference
    ``Delta_open = U_S /_\\ U_H``, phantom-open violations, the closed rows
    excluded from open exposure, and ``reconciliation_clean``.
    """
    cfg = config or load_discovery_execution_config()
    open_like = {s.upper() for s in cfg["open_like_states"]}
    closed_states = {s.upper() for s in cfg["closed_states"]}
    phantom_set = {_norm(t) for t in cfg["default_phantom_tickers"]}

    verified = {_norm(t) for t in (verified_open_tickers or []) if _norm(t)}
    sheet_open: set[str] = set()
    closed_excluded: list[str] = []
    for row in sheet_rows or []:
        ticker = _norm(row.get("ticker") or row.get("symbol") or row.get("normalized_ticker"))
        if not ticker:
            continue
        state = str(
            row.get("trade_state") or row.get("status") or row.get("state") or ""
        ).strip().upper()
        if state in closed_states:
            closed_excluded.append(ticker)
            continue
        # Default (no state) is treated as open-like for a sheet row.
        if state == "" or state in open_like:
            sheet_open.add(ticker)

    symmetric_difference = sorted(sheet_open ^ verified)
    phantom_open_violations = sorted(t for t in sheet_open if t in phantom_set)
    closed_rows_in_sheet_open = sorted(t for t in sheet_open if t in set(closed_excluded))
    reconciliation_clean = (
        not symmetric_difference
        and not phantom_open_violations
        and not closed_rows_in_sheet_open
    )
    return {
        "canonical_open_tickers": sorted(verified),
        "sheet_open_tickers": sorted(sheet_open),
        "verified_open_tickers": sorted(verified),
        "symmetric_difference": symmetric_difference,
        "phantom_open_violations": phantom_open_violations,
        "closed_rows_excluded": sorted(set(closed_excluded)),
        "reconciliation_clean": reconciliation_clean,
    }


def phantom_open_violations(
    rows: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phantom rows that are still marked open-like (Section 3).

    phantom_open_violation(r) = 1[ ticker(r) in P AND trade_state(r) in OPEN_LIKE ].
    Phantom rows are excluded from open exposure; they remain valid in history.
    """
    cfg = config or load_discovery_execution_config()
    open_like = {s.upper() for s in cfg["open_like_states"]}
    phantom_set = {_norm(t) for t in cfg["default_phantom_tickers"]}
    violations: list[str] = []
    for row in rows or []:
        ticker = _norm(row.get("ticker") or row.get("symbol"))
        if not ticker or ticker not in phantom_set:
            continue
        state = str(
            row.get("trade_state") or row.get("status") or row.get("state") or ""
        ).strip().upper()
        if state == "" or state in open_like:
            violations.append(ticker)
    violations = sorted(set(violations))
    return {
        "phantom_violation_count": len(violations),
        "phantom_open_violations": violations,
        "phantom_clean": len(violations) == 0,
        "phantom_set": sorted(phantom_set),
    }


# ---------------------------------------------------------------------------
# 3. Leverage truth conflict
# ---------------------------------------------------------------------------
def leverage_truth(
    holdings: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare sheet leverage vs policy/payload leverage (Section 4).

    NEVER picks a side on a conflict — a divergence between two sources is
    surfaced as ``LEVERAGE_TRUTH_CONFLICT`` for human resolution. An out-of-max
    or missing leverage is also surfaced. leverage_clean requires every holding
    to have a known sheet leverage within the per-instrument ceiling AND, when a
    policy value exists, exact agreement.
    """
    conflicts: list[dict[str, Any]] = []
    over_max: list[dict[str, Any]] = []
    unknown: list[str] = []
    for h in holdings or []:
        ticker = _norm(h.get("ticker") or h.get("normalized_ticker") or h.get("symbol"))
        country = h.get("country")
        allowed = get_max_allowed_leverage(
            h.get("ticker") or h.get("normalized_ticker"), country
        )
        lev_sheet = _safe_float(
            h.get("leverage_sheet") if h.get("leverage_sheet") is not None else h.get("leverage")
        )
        lev_policy = _safe_float(
            h.get("leverage_policy")
            if h.get("leverage_policy") is not None
            else h.get("leverage_payload")
        )
        if lev_sheet is None:
            unknown.append(ticker)
            continue
        if lev_sheet < 1.0 or lev_sheet > allowed:
            over_max.append(
                {
                    "ticker": ticker,
                    "leverage_sheet": lev_sheet,
                    "allowed_max_leverage": allowed,
                    "status": "LEVERAGE_POLICY_VIOLATION",
                }
            )
        if lev_policy is not None and lev_policy != lev_sheet:
            conflicts.append(
                {
                    "ticker": ticker,
                    "leverage_sheet": lev_sheet,
                    "leverage_policy": lev_policy,
                    "allowed_max_leverage": allowed,
                    "status": "LEVERAGE_TRUTH_CONFLICT",
                    "resolution": "UNRESOLVED_HUMAN_REVIEW_REQUIRED",
                }
            )
    leverage_clean = not conflicts and not over_max and not unknown
    return {
        "leverage_clean": leverage_clean,
        "conflicts": conflicts,
        "leverage_conflict_set": sorted({c["ticker"] for c in conflicts}),
        "over_max": over_max,
        "unknown_leverage": sorted(set(unknown)),
        "has_leverage_truth_conflict": bool(conflicts),
    }


# ---------------------------------------------------------------------------
# 4. Exit debt
# ---------------------------------------------------------------------------
def _has_stop_hit(row: dict[str, Any]) -> bool:
    for key in ("exit_stage", "trade_state", "close_reason"):
        if "STOP_HIT" in str(row.get(key) or "").strip().upper():
            return True
    return False


def exit_debt(
    rows: list[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Exit-debt counter (Section 5).

    For each row: exit_debt(r) = max(stop_hit_unresolved, close_required_unresolved,
    moltbook_missing). Closed/reconciled stop-hits (CVX/XOM STOP_CLOSED) do NOT
    count; an open-like unresolved stop-hit (ZIM) does. ``moltbook_missing`` is
    only counted when a closed/stopped row is explicitly flagged
    ``moltbook_event_present=False``.
    """
    cfg = config or load_discovery_execution_config()
    d_max = float(cfg.get("exit_debt_d_max", 5)) or 5.0
    closed_states = {s.upper() for s in cfg["closed_states"]}

    count = 0
    detail: list[dict[str, Any]] = []
    for row in rows or []:
        ticker = _norm(row.get("ticker") or row.get("symbol"))
        trade_state = str(
            row.get("trade_state") or row.get("status") or row.get("state") or ""
        ).strip().upper()
        recon = str(row.get("mvp_recon_status") or row.get("recon_status") or "").strip().upper()
        action = str(row.get("action_required") or "").strip().upper()
        is_closed = trade_state in closed_states
        stopped = _has_stop_hit(row)

        stop_hit_unresolved = int(stopped and recon not in CLOSED_RECON_STATES and not is_closed)
        close_required_unresolved = int(
            action in CLOSE_REQUIRED_ACTIONS and trade_state not in closed_states
        )
        moltbook_missing = int(
            (is_closed or stopped) and row.get("moltbook_event_present") is False
        )
        debt = max(stop_hit_unresolved, close_required_unresolved, moltbook_missing)
        if debt:
            count += debt
            detail.append(
                {
                    "ticker": ticker,
                    "stop_hit_unresolved": bool(stop_hit_unresolved),
                    "close_required_unresolved": bool(close_required_unresolved),
                    "moltbook_missing": bool(moltbook_missing),
                }
            )
    return {
        "exit_debt_count": count,
        "exit_debt_score": round(min(1.0, count / d_max), 4),
        "exit_debt_clean": count == 0,
        "exit_debt_rows": detail,
    }


# ---------------------------------------------------------------------------
# 5. BUY_SCORE + tiering
# ---------------------------------------------------------------------------
def compute_buy_score(
    components: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
) -> float:
    """BUY_SCORE(c) = sum_i w_i * clamp01(x_i), weights sum to 1.

        0.30*why_today + 0.25*price_confirmation + 0.20*source_quality
        + 0.15*cross_model_agreement + 0.10*portfolio_fit
    """
    cfg = config or load_discovery_execution_config()
    weights = cfg["buy_score_weights"]
    components = dict(components or {})
    score = sum(
        float(w) * clamp01(components.get(name, 0.0)) for name, w in weights.items()
    )
    return round(score, 4)


def why_today_tier(
    score: Any,
    *,
    config: dict[str, Any] | None = None,
) -> str:
    """Tiered WHY_TODAY classification (replaces the single 0.70 hard filter)."""
    cfg = config or load_discovery_execution_config()
    s = clamp01(score)
    if s < cfg["why_today_noise_max"]:
        return "NOISE_OR_STALE"
    if s < cfg["why_today_discovery_min"]:
        return "WEAK_DISCOVERY"
    if s < cfg["why_today_watchlist_min"]:
        return "VALID_DISCOVERY"
    if s < cfg["why_today_probe_min"]:
        return "STRONG_WATCHLIST"
    if s < cfg["why_today_buy_min"]:
        return "PROBE_CANDIDATE"
    return "HIGH_CONVICTION"


def _proof_ok_probe(proof: dict[str, Any], cfg: dict[str, Any]) -> bool:
    return (
        clamp01(proof.get("price_confirmation")) >= cfg["probe_price_confirmation_min"]
        and clamp01(proof.get("volume_confirmation")) >= cfg["probe_volume_confirmation_min"]
        and clamp01(proof.get("source_quality")) >= cfg["probe_source_quality_min"]
    )


def _proof_ok_buy(proof: dict[str, Any], cfg: dict[str, Any]) -> bool:
    return (
        clamp01(proof.get("price_confirmation")) >= cfg["buy_price_confirmation_min"]
        and clamp01(proof.get("volume_confirmation")) >= cfg["buy_volume_confirmation_min"]
        and clamp01(proof.get("source_quality")) >= cfg["buy_source_quality_min"]
        and clamp01(proof.get("portfolio_fit")) >= cfg["buy_portfolio_fit_min"]
    )


def classify_candidate(
    buy_score: Any,
    *,
    execution_allowed: bool,
    proof: dict[str, Any] | None = None,
    phantom: bool = False,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a candidate by BUY_SCORE band, gated by execution + proof.

    DISCOVERED / WATCHLIST / *_EXECUTION_BLOCKED are discovery-mode labels only.
    PROBE_BUY / BUY appear ONLY when ``execution_allowed`` is true AND the
    per-candidate proof floors pass. A phantom candidate is quarantined.
    """
    cfg = config or load_discovery_execution_config()
    proof = dict(proof or {})
    s = clamp01(buy_score)

    if phantom:
        return _verdict("PHANTOM_QUARANTINE", s, "PHANTOM_QUARANTINE")

    disc = cfg["buy_score_discovery_min"]
    watch = cfg["buy_score_watchlist_min"]
    probe = cfg["buy_score_probe_min"]
    buy = cfg["buy_score_buy_min"]

    if s < cfg["why_today_noise_max"]:
        return _verdict("NOISE_OR_STALE", s, None)
    if s < disc:
        return _verdict("WEAK_DISCOVERY", s, None)
    if s < watch:
        return _verdict("DISCOVERED", s, None)
    if s < probe:
        return _verdict("WATCHLIST", s, None)

    probe_ok = _proof_ok_probe(proof, cfg)
    buy_ok = _proof_ok_buy(proof, cfg)

    if s < buy:  # PROBE band [0.73, 0.80)
        if not execution_allowed:
            return _verdict(
                "CONDITIONAL_PROBE_CANDIDATE_EXECUTION_BLOCKED", s, "EXECUTION_GATES_NOT_PASSED"
            )
        if probe_ok:
            return _verdict("PROBE_BUY", s, None)
        return _verdict("WATCHLIST", s, "PRICE_VOLUME_CONFIRMATION_MISSING")

    # BUY band [0.80, 1.0]
    if not execution_allowed:
        return _verdict(
            "HIGH_CONVICTION_WATCHLIST_EXECUTION_BLOCKED", s, "EXECUTION_GATES_NOT_PASSED"
        )
    if buy_ok:
        return _verdict("BUY", s, None)
    if probe_ok:
        return _verdict("PROBE_BUY", s, "BUY_PROOF_PARTIAL_PROBE_ONLY")
    return _verdict("WATCHLIST", s, "PRICE_VOLUME_CONFIRMATION_MISSING")


def _verdict(classification: str, buy_score: float, blocked_reason: str | None) -> dict[str, Any]:
    return {
        "classification": classification,
        "buy_score": round(buy_score, 4),
        "execution_blocked_reason": blocked_reason,
        "is_executable_classification": classification in EXECUTION_CLASSIFICATIONS,
    }


# ---------------------------------------------------------------------------
# 6. Mode state
# ---------------------------------------------------------------------------
def compute_mode_state(
    *,
    holdings_price_coverage: float,
    candidate_price_coverage: float,
    portfolio_truth_clean: bool,
    phantom_clean: bool,
    leverage_clean: bool,
    exit_debt_clean: bool,
    source_health_ok: bool,
    advisory_safety_lock_intact: bool = True,
    candidate_source_available: bool = True,
    system_can_parse_candidates: bool = True,
    candidate_quality_ok: bool = True,
    risk_budget_available: bool = True,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the three-lane mode_state.

    discovery_allowed depends ONLY on candidate-source availability, parseability,
    and the advisory safety lock — never on price / recon / leverage / exit-debt.
    execution_allowed requires every hygiene gate. new_risk_allowed additionally
    requires candidate quality + risk budget. survival_attention_required flags a
    dirty open-risk surface.
    """
    cfg = config or load_discovery_execution_config()
    h_min = float(cfg["min_holdings_price_coverage_for_execution"])
    c_min = float(cfg["min_candidate_price_coverage_for_execution"])
    h_ok = float(holdings_price_coverage) >= h_min
    c_ok = float(candidate_price_coverage) >= c_min

    blockers: list[str] = []
    if not h_ok:
        blockers.append("H_PRICE_COVERAGE_BELOW_0_80")
    if not c_ok:
        blockers.append("C_PRICE_COVERAGE_BELOW_0_80")
    if not portfolio_truth_clean:
        blockers.append("PORTFOLIO_TRUTH_MISMATCH")
    if not phantom_clean:
        blockers.append("PHANTOM_OPEN_VIOLATION")
    if not leverage_clean:
        blockers.append("LEVERAGE_TRUTH_CONFLICT")
    if not exit_debt_clean:
        blockers.append("EXIT_DEBT_UNRESOLVED")
    if not source_health_ok:
        blockers.append("SOURCE_HEALTH_DEGRADED")
    if not advisory_safety_lock_intact:
        blockers.append("ADVISORY_SAFETY_LOCK_BROKEN")

    execution_allowed = bool(
        h_ok
        and c_ok
        and portfolio_truth_clean
        and phantom_clean
        and leverage_clean
        and exit_debt_clean
        and source_health_ok
        and advisory_safety_lock_intact
    )
    discovery_allowed = bool(
        candidate_source_available
        and system_can_parse_candidates
        and advisory_safety_lock_intact
    )
    new_risk_allowed = bool(
        execution_allowed and candidate_quality_ok and risk_budget_available
    )
    survival_attention_required = bool(
        (not h_ok)
        or (not portfolio_truth_clean)
        or (not phantom_clean)
        or (not leverage_clean)
        or (not exit_debt_clean)
    )
    return {
        "discovery_allowed": discovery_allowed,
        "execution_allowed": execution_allowed,
        "new_risk_allowed": new_risk_allowed,
        "survival_attention_required": survival_attention_required,
        "candidate_board_allowed": discovery_allowed,
        "buy_board_allowed": execution_allowed,
        "blockers": blockers,
    }


# ---------------------------------------------------------------------------
# 7. Report assembly
# ---------------------------------------------------------------------------
def build_discovery_execution_report(
    *,
    mode_state: dict[str, Any],
    holdings_price_coverage: float,
    candidate_price_coverage: float,
    discovery_board: list[dict[str, Any]] | None = None,
    survival_board: list[dict[str, Any]] | None = None,
    execution_board: list[dict[str, Any]] | None = None,
    quarantine_board: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble the boards + mode summary into the advisory report object."""
    execution_allowed = bool(mode_state.get("execution_allowed"))
    execution_board = execution_board or []
    if not execution_allowed:
        execution_board = []  # never surface executable buys when blocked
    message = (
        "Executable buys available for human review."
        if execution_allowed and execution_board
        else "Discovery is active, but execution is blocked."
    )
    return {
        "report": "discovery_execution_mode",
        "mode_state": mode_state,
        "coverage": {
            "holdings_price_coverage": round(float(holdings_price_coverage), 4),
            "candidate_price_coverage": round(float(candidate_price_coverage), 4),
        },
        "survival_board": survival_board or [],
        "discovery_board": discovery_board or [],
        "execution_board": execution_board,
        "quarantine_board": quarantine_board or [],
        "message": message,
        # Advisory-only invariants — execution permission is never granted here.
        "real_money_sizing_impact": "PROHIBITED",
        "human_execution_required": True,
        "operator_execution_required": True,
        "safety": advisory_safety_stamps(),
        **advisory_safety_stamps(),
    }


__all__ = [
    "CLOSED_RECON_STATES",
    "CLOSE_REQUIRED_ACTIONS",
    "DISCOVERY_CLASSIFICATIONS",
    "EXECUTION_CLASSIFICATIONS",
    "clamp01",
    "valid_price_flag",
    "price_coverage",
    "resolve_open_positions",
    "phantom_open_violations",
    "leverage_truth",
    "exit_debt",
    "compute_buy_score",
    "why_today_tier",
    "classify_candidate",
    "compute_mode_state",
    "build_discovery_execution_report",
]
