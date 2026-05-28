"""USA-bias + fallback-contamination metrics for the discovery output.

The audit found B_US ~= 0.64 but nothing in code measured it, and the spec's
contamination ratios (R_static / R_memory / R_phantom / R_live) were never
computed. This module computes both, honestly, over the candidate output set.

It is pure/advisory — it never blocks a candidate merely for being US. It
surfaces bias and lets the synthesis downgrade discovery confidence.

USA bias::

    N_US        = #{c : country(c) = "United States"}
    B_US        = N_US / max(1, N_total)
    B_US_cap    = 0.35
    USA_bias_violation = max(0, B_US - B_US_cap)
    N_US_listed = #{c : US-listed venue}
    B_US_venue  = N_US_listed / max(1, N_total)
    country_concentration_hhi = sum_k (N_k / N_total)^2

Contamination::

    R_static  = #{c : source_class = STATIC_FALLBACK} / max(1, |O|)
    R_memory  = #{c : source_class = MEMORY_OR_STALE} / max(1, |O|)
    R_phantom = #{c : c in phantom/closed/sold}        / max(1, |O|)
    R_live    = #{c : c in L_today}                     / max(1, |O|)
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.top30_country_coverage import canonical_country, country_from_ticker
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from top30_country_coverage import canonical_country, country_from_ticker


B_US_CAP = 0.35
B_US_VENUE_CAP = 0.60
R_STATIC_HIGH = 0.50

_US_EXCHANGES = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "NYSEARCA"}

# Recognised source classes for contamination accounting.
SOURCE_CLASSES = ("LIVE", "STATIC_FALLBACK", "MEMORY_OR_STALE", "PHANTOM")


def _candidate_country(cand: dict[str, Any]) -> str | None:
    return (
        canonical_country(cand.get("country"))
        or canonical_country(cand.get("jurisdiction"))
        or country_from_ticker(cand.get("ticker") or cand.get("symbol"))
    )


def _is_us_listed(cand: dict[str, Any]) -> bool:
    exchange = str(cand.get("exchange") or "").strip().upper()
    if exchange in _US_EXCHANGES:
        return True
    listing_country = canonical_country(cand.get("primary_listing_country") or cand.get("listing_country"))
    if listing_country == "United States":
        return True
    ticker = str(cand.get("ticker") or cand.get("symbol") or "").strip().upper()
    # A bare ticker (no foreign suffix) tagged US is US-listed.
    if country_from_ticker(ticker) is None and _candidate_country(cand) == "United States":
        return True
    return False


def compute_usa_bias(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute B_US, venue bias, concentration HHI, and status flags."""
    cands = list(candidates)
    n_total = len(cands)
    denom = max(1, n_total)
    n_us = 0
    n_us_listed = 0
    country_counts: dict[str, int] = {}
    for cand in cands:
        country = _candidate_country(cand) or "UNKNOWN"
        country_counts[country] = country_counts.get(country, 0) + 1
        if country == "United States":
            n_us += 1
        if _is_us_listed(cand):
            n_us_listed += 1

    b_us = round(n_us / denom, 4)
    b_us_venue = round(n_us_listed / denom, 4)
    usa_bias_violation = round(max(0.0, b_us - B_US_CAP), 4)
    hhi = round(sum((cnt / denom) ** 2 for cnt in country_counts.values()), 4) if n_total else 0.0

    status: list[str] = []
    if usa_bias_violation > 0:
        status.append("USA_BIAS_ELEVATED")
    if b_us_venue > B_US_VENUE_CAP:
        status.append("US_LISTING_VENUE_BIAS_ELEVATED")

    return {
        "N_total": n_total,
        "N_US": n_us,
        "B_US": b_us,
        "B_US_cap": B_US_CAP,
        "USA_bias_violation": usa_bias_violation,
        "N_US_listed": n_us_listed,
        "B_US_venue": b_us_venue,
        "country_concentration_hhi": hhi,
        "country_counts": dict(sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "status": status,
    }


def compute_contamination_ratios(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute R_static / R_memory / R_phantom / R_live + warnings.

    Each candidate should carry ``source_class`` (one of SOURCE_CLASSES). The
    in-L_today set is identified by ``source_class == "LIVE"`` or an explicit
    ``in_l_today`` truthy flag; phantom by ``source_class == "PHANTOM"`` or a
    ``phantom`` truthy flag.
    """
    cands = list(candidates)
    n = len(cands)
    denom = max(1, n)
    static_n = memory_n = phantom_n = live_n = 0
    for cand in cands:
        source_class = str(cand.get("source_class") or "").strip().upper()
        is_phantom = source_class == "PHANTOM" or bool(cand.get("phantom"))
        is_live = source_class == "LIVE" or bool(cand.get("in_l_today"))
        if is_phantom:
            phantom_n += 1
        if is_live:
            live_n += 1
        if source_class == "STATIC_FALLBACK":
            static_n += 1
        elif source_class == "MEMORY_OR_STALE":
            memory_n += 1

    r_static = round(static_n / denom, 4)
    r_memory = round(memory_n / denom, 4)
    r_phantom = round(phantom_n / denom, 4)
    r_live = round(live_n / denom, 4)

    warnings: list[str] = []
    if r_static >= R_STATIC_HIGH:
        warnings.append("STATIC_CONTAMINATION_HIGH")
    if live_n == 0:
        warnings.append("NO_LIVE_DISCOVERED_CANDIDATES")
    if r_phantom > 0:
        warnings.append("PHANTOM_CONTAMINATION_PRESENT")

    return {
        "candidate_count": n,
        "R_static": r_static,
        "R_memory": r_memory,
        "R_phantom": r_phantom,
        "R_live": r_live,
        "warnings": warnings,
    }


def render_bias_markdown(usa_bias: dict[str, Any], contamination: dict[str, Any]) -> str:
    """Render bias + contamination metrics as a markdown block for prompts."""
    lines: list[str] = []
    lines.append("USA BIAS + FALLBACK CONTAMINATION METRICS")
    lines.append(
        "B_US={B_US} (cap {B_US_cap}) violation={USA_bias_violation} "
        "B_US_venue={B_US_venue} HHI={country_concentration_hhi} N_total={N_total}".format(**usa_bias)
    )
    if usa_bias["status"]:
        lines.append("usa_bias_status: " + ", ".join(usa_bias["status"]))
    lines.append(
        "R_static={R_static} R_memory={R_memory} R_phantom={R_phantom} "
        "R_live={R_live}".format(**contamination)
    )
    if contamination["warnings"]:
        lines.append("contamination_warnings: " + ", ".join(contamination["warnings"]))
    lines.append(
        "Note: a US name is never blocked merely for being US; bias only "
        "downgrades the claim of global discovery and must be proven, not assumed."
    )
    return "\n".join(lines)


__all__ = [
    "B_US_CAP",
    "B_US_VENUE_CAP",
    "SOURCE_CLASSES",
    "compute_usa_bias",
    "compute_contamination_ratios",
    "render_bias_markdown",
]
