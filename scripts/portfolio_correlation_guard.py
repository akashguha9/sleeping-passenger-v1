"""Real Evidence Sprint — Phase 5: cross-position correlation / portfolio guard.

Extends the per-position capacity guard to a PORTFOLIO-level exposure and
correlation risk check.  It is pure and advisory-only: it returns a verdict and
metadata so a human can avoid concentration / correlation risk.  It NEVER
executes and can NEVER unlock execution.

Math::

    sigma_p^2 = w^T Σ w                 (portfolio variance)
    rho_ij    = Cov(r_i, r_j)/(σ_i σ_j) (pairwise correlation)
    w'        = normalize(w_existing + w_candidate)

    CorrelationGuardOK = I(max_j |rho_cj| <= rho_max)
                       · I(w'^T Σ w' <= sigma2_max)
                       · I(sector_exposure_after  <= sector_cap)
                       · I(country_exposure_after <= country_cap)
                       · I(single_name_exposure_after <= single_name_cap)

Conservative defaults: rho_max=0.80, single_name_cap=0.10, sector_cap=0.30,
country_cap_india=0.50, country_cap_other=0.25.

If covariance/correlation data is missing, ``correlation_status = "UNKNOWN"``
and ``correlation_guard_ok = False`` — missing risk data NEVER promotes a
candidate.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

try:  # package layout
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.leverage_policy import is_india_instrument
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from leverage_policy import is_india_instrument  # type: ignore[no-redef]

DEFAULT_RHO_MAX: float = 0.80
DEFAULT_SINGLE_NAME_CAP: float = 0.10
DEFAULT_SECTOR_CAP: float = 0.30
DEFAULT_COUNTRY_CAP_INDIA: float = 0.50
DEFAULT_COUNTRY_CAP_OTHER: float = 0.25

# Correlation status labels.
STATUS_OK = "OK"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_BLOCKED = "BLOCKED"
STATUS_NOT_EVALUATED = "NOT_EVALUATED"

# Advisory class hints (no execution wording).
CORRELATION_OK = "CORRELATION_OK"
BLOCKED_BY_CORRELATION = "BLOCKED_BY_CORRELATION"
WATCHLIST_CORRELATION_UNKNOWN = "WATCHLIST_CORRELATION_UNKNOWN"


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cov(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx, my = _mean(xs[:n]), _mean(ys[:n])
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / (n - 1)


def _std(xs: Sequence[float]) -> float | None:
    v = _cov(xs, xs)
    if v is None or v < 0:
        return None
    return math.sqrt(v)


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    c = _cov(xs, ys)
    sx, sy = _std(xs), _std(ys)
    if c is None or not sx or not sy:
        return None
    return c / (sx * sy)


def _portfolio_variance(
    tickers: Sequence[str],
    weights: Mapping[str, float],
    returns_by_ticker: Mapping[str, Sequence[float]] | None,
    covariance: Mapping[tuple[str, str], float] | None,
) -> float | None:
    """w^T Σ w over ``tickers``.  Returns None when any needed entry is missing."""
    total = 0.0
    for i in tickers:
        wi = weights.get(i, 0.0)
        for j in tickers:
            wj = weights.get(j, 0.0)
            cov_ij: float | None
            if covariance is not None:
                cov_ij = covariance.get((i, j), covariance.get((j, i)))
            elif returns_by_ticker is not None:
                ri, rj = returns_by_ticker.get(i), returns_by_ticker.get(j)
                cov_ij = _cov(ri, rj) if (ri is not None and rj is not None) else None
            else:
                cov_ij = None
            if cov_ij is None:
                return None
            total += wi * wj * cov_ij
    return total


def evaluate_correlation_guard(
    *,
    candidate: Mapping[str, Any],
    existing_positions: Sequence[Mapping[str, Any]] | None = None,
    returns_by_ticker: Mapping[str, Sequence[float]] | None = None,
    correlation_matrix: Mapping[tuple[str, str], float] | None = None,
    covariance_matrix: Mapping[tuple[str, str], float] | None = None,
    rho_max: float = DEFAULT_RHO_MAX,
    sigma2_max: float | None = None,
    single_name_cap: float = DEFAULT_SINGLE_NAME_CAP,
    sector_cap: float = DEFAULT_SECTOR_CAP,
    country_cap_india: float = DEFAULT_COUNTRY_CAP_INDIA,
    country_cap_other: float = DEFAULT_COUNTRY_CAP_OTHER,
) -> dict[str, Any]:
    """Return a portfolio correlation/exposure verdict.  Never executes.

    ``candidate`` and each existing position carry ``ticker``, ``weight``
    (notional fraction of capital), ``sector`` and ``country``.
    """
    stamps = advisory_safety_stamps()
    existing = [dict(p) for p in (existing_positions or [])]
    reasons: list[str] = []

    c_ticker = str(candidate.get("ticker") or "").strip()
    c_sector = candidate.get("sector")
    c_country = candidate.get("country")
    c_weight = max(0.0, float(candidate.get("weight") or 0.0))

    # ----- weights after adding the candidate (normalized) --------------- #
    raw: dict[str, float] = {}
    for p in existing:
        raw[str(p.get("ticker"))] = raw.get(str(p.get("ticker")), 0.0) + max(0.0, float(p.get("weight") or 0.0))
    raw[c_ticker] = raw.get(c_ticker, 0.0) + c_weight
    total_w = sum(raw.values())
    weights = {t: (w / total_w if total_w > 0 else 0.0) for t, w in raw.items()}

    # ----- exposures after ------------------------------------------------ #
    single_name_after = weights.get(c_ticker, 0.0)
    sector_after = sum(
        weights.get(str(p.get("ticker")), 0.0)
        for p in existing
        if p.get("sector") == c_sector
    ) + (weights.get(c_ticker, 0.0) if c_sector is not None else 0.0)
    country_after = sum(
        weights.get(str(p.get("ticker")), 0.0)
        for p in existing
        if p.get("country") == c_country
    ) + (weights.get(c_ticker, 0.0) if c_country is not None else 0.0)

    is_india = is_india_instrument(c_ticker, c_country)
    country_cap = country_cap_india if is_india else country_cap_other

    single_ok = single_name_after <= single_name_cap + 1e-9
    sector_ok = sector_after <= sector_cap + 1e-9
    country_ok = country_after <= country_cap + 1e-9
    if not single_ok:
        reasons.append(f"single-name exposure {single_name_after:.4f} > cap {single_name_cap}")
    if not sector_ok:
        reasons.append(f"sector exposure {sector_after:.4f} > cap {sector_cap}")
    if not country_ok:
        reasons.append(f"country exposure {country_after:.4f} > cap {country_cap}")

    # ----- correlation + variance (need data) ---------------------------- #
    tickers = list(weights.keys())
    has_corr_source = bool(returns_by_ticker or correlation_matrix or covariance_matrix)

    max_pairwise: float | None = None
    corr_ok = True
    variance_after: float | None = None
    variance_before: float | None = None
    data_missing = False

    if not has_corr_source and existing:
        # We have a real multi-asset portfolio but NO covariance data.
        data_missing = True
    elif has_corr_source:
        # Max |rho| between the candidate and each existing position.
        pair_rhos: list[float] = []
        for p in existing:
            j = str(p.get("ticker"))
            if j == c_ticker:
                continue
            rho: float | None = None
            if correlation_matrix is not None:
                rho = correlation_matrix.get((c_ticker, j), correlation_matrix.get((j, c_ticker)))
            elif covariance_matrix is not None:
                cij = covariance_matrix.get((c_ticker, j), covariance_matrix.get((j, c_ticker)))
                cii = covariance_matrix.get((c_ticker, c_ticker))
                cjj = covariance_matrix.get((j, j))
                if cij is not None and cii and cjj and cii > 0 and cjj > 0:
                    rho = cij / math.sqrt(cii * cjj)
            elif returns_by_ticker is not None:
                rc, rj = returns_by_ticker.get(c_ticker), returns_by_ticker.get(j)
                if rc is not None and rj is not None:
                    rho = _correlation(rc, rj)
            if rho is None:
                data_missing = True
            else:
                pair_rhos.append(abs(rho))
        if pair_rhos:
            max_pairwise = max(pair_rhos)
            corr_ok = max_pairwise <= rho_max + 1e-9
            if not corr_ok:
                reasons.append(f"max pairwise correlation {max_pairwise:.4f} > rho_max {rho_max}")

        # Portfolio variance (needs covariance for every pair in ``tickers``).
        cov_source = covariance_matrix
        variance_after = _portfolio_variance(tickers, weights, returns_by_ticker, cov_source)
        if variance_after is None:
            data_missing = data_missing or (sigma2_max is not None)
        elif sigma2_max is not None and variance_after > sigma2_max + 1e-12:
            corr_ok = False
            reasons.append(f"portfolio variance {variance_after:.6g} > sigma2_max {sigma2_max:g}")

    # ----- resolve status ------------------------------------------------- #
    exposure_ok = single_ok and sector_ok and country_ok
    if data_missing:
        status = STATUS_UNKNOWN
        guard_ok = False
        if "correlation/covariance data missing" not in reasons:
            reasons.append("correlation/covariance data missing; cannot clear risk")
        advisory_class = WATCHLIST_CORRELATION_UNKNOWN
    elif not has_corr_source and not existing:
        # First position into an empty book: no pairwise risk yet; clear ONLY on
        # the exposure caps (variance check is skipped when no data is supplied).
        status = STATUS_OK if exposure_ok else STATUS_BLOCKED
        guard_ok = exposure_ok
        advisory_class = CORRELATION_OK if guard_ok else BLOCKED_BY_CORRELATION
    else:
        guard_ok = bool(corr_ok and exposure_ok)
        status = STATUS_OK if guard_ok else STATUS_BLOCKED
        advisory_class = CORRELATION_OK if guard_ok else BLOCKED_BY_CORRELATION

    return {
        "correlation_status": status,
        "correlation_guard_ok": bool(guard_ok),
        "max_pairwise_correlation": (
            round(max_pairwise, 6) if max_pairwise is not None else None
        ),
        "rho_max": rho_max,
        "portfolio_variance_before": (
            round(variance_before, 9) if variance_before is not None else None
        ),
        "portfolio_variance_after": (
            round(variance_after, 9) if variance_after is not None else None
        ),
        "sigma2_max": sigma2_max,
        "sector_exposure_after": round(sector_after, 6),
        "sector_cap": sector_cap,
        "country_exposure_after": round(country_after, 6),
        "country_cap": country_cap,
        "is_india_instrument": is_india,
        "single_name_exposure_after": round(single_name_after, 6),
        "single_name_cap": single_name_cap,
        "correlation_block_reason": "; ".join(reasons),
        "advisory_class": advisory_class,
        # Advisory-only invariants — present on every verdict; never unlock.
        "advisory_status": stamps.get("advisory_status", "ADVISORY_ONLY"),
        "execution_gate": stamps["execution_gate"],
        "broker_api_called": stamps["broker_api_called"],
        "ai_execution_count": stamps["ai_execution_count"],
        "human_execution_required": True,
        "executes_trade": False,
    }


__all__ = [
    "DEFAULT_RHO_MAX",
    "DEFAULT_SINGLE_NAME_CAP",
    "DEFAULT_SECTOR_CAP",
    "DEFAULT_COUNTRY_CAP_INDIA",
    "DEFAULT_COUNTRY_CAP_OTHER",
    "STATUS_OK",
    "STATUS_UNKNOWN",
    "STATUS_BLOCKED",
    "STATUS_NOT_EVALUATED",
    "CORRELATION_OK",
    "BLOCKED_BY_CORRELATION",
    "WATCHLIST_CORRELATION_UNKNOWN",
    "evaluate_correlation_guard",
]
