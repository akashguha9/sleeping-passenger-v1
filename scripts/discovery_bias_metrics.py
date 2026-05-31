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
# Below this many effective countries, an output set of >= this many names is
# too concentrated to be called "global discovery".
EFFECTIVE_COUNTRY_MIN = 2.0
CONCENTRATION_MIN_N = 5
# Floor for the 1/HHI inversion so an empty set never divides by zero.
_HHI_EPSILON = 1e-9

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

    n_non_us = n_total - n_us
    b_us = round(n_us / denom, 4)
    b_us_venue = round(n_us_listed / denom, 4)
    b_non_us = round(n_non_us / denom, 4)
    usa_bias_violation = round(max(0.0, b_us - B_US_CAP), 4)
    # HHI over the realized country distribution (raw fractions, not rounded
    # counts) so effective_country_count = 1/HHI is faithful.
    hhi_raw = sum((cnt / denom) ** 2 for cnt in country_counts.values()) if n_total else 0.0
    hhi = round(hhi_raw, 4)
    # Effective number of distinct countries (inverse-Simpson). 1 country -> 1.0;
    # a perfectly even spread over k countries -> k. Floored against epsilon so an
    # empty output set yields a large-but-finite number rather than dividing by 0.
    effective_country_count = round(1.0 / max(hhi_raw, _HHI_EPSILON), 4) if n_total else 0.0

    status: list[str] = []
    if usa_bias_violation > 0:
        status.append("USA_BIAS_ELEVATED")
    if b_us_venue > B_US_VENUE_CAP:
        status.append("US_LISTING_VENUE_BIAS_ELEVATED")
    if n_total >= CONCENTRATION_MIN_N and effective_country_count < EFFECTIVE_COUNTRY_MIN:
        status.append("COUNTRY_CONCENTRATION_HIGH")

    return {
        "N_total": n_total,
        "N_US": n_us,
        "N_non_US": n_non_us,
        "B_US": b_us,
        "B_non_US": b_non_us,
        "B_US_cap": B_US_CAP,
        "USA_bias_violation": usa_bias_violation,
        "N_US_listed": n_us_listed,
        "B_US_venue": b_us_venue,
        "country_concentration_hhi": hhi,
        "effective_country_count": effective_country_count,
        "country_counts": dict(sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "status": status,
    }


def global_breadth_claim_allowed(
    usa_bias: dict[str, Any],
    *,
    c_global: float,
    covered_country_count: int,
) -> dict[str, Any]:
    """Whether the discovery output may claim proven *global* breadth.

    A truthful gate — it never fabricates candidates, it only decides whether the
    synthesis is permitted to call the discovery "global". All four conditions
    must hold::

        global_breadth_claim_allowed =
            C_global > 0
            and covered_country_count >= 1
            and B_US <= B_US_cap
            and effective_country_count >= 2

    When ``C_global == 0`` the claim is always disallowed (no country was proven
    end-to-end), regardless of how low US bias happens to be.
    """
    try:
        c_global_val = float(c_global or 0.0)
    except (TypeError, ValueError):
        c_global_val = 0.0
    try:
        covered = int(covered_country_count or 0)
    except (TypeError, ValueError):
        covered = 0
    b_us = float(usa_bias.get("B_US", 0.0) or 0.0)
    eff = float(usa_bias.get("effective_country_count", 0.0) or 0.0)

    reasons: list[str] = []
    if c_global_val <= 0:
        reasons.append("C_global=0 (no country proven end-to-end)")
    if covered < 1:
        reasons.append("covered_country_count<1")
    if b_us > B_US_CAP:
        reasons.append("B_US>%.2f (US concentration too high)" % B_US_CAP)
    if eff < EFFECTIVE_COUNTRY_MIN:
        reasons.append("effective_country_count<%.0f" % EFFECTIVE_COUNTRY_MIN)

    allowed = not reasons
    return {
        "global_breadth_claim_allowed": allowed,
        "blocking_reasons": reasons,
        "C_global": round(c_global_val, 4),
        "covered_country_count": covered,
        "B_US": round(b_us, 4),
        "effective_country_count": round(eff, 4),
        # The mandated downgrade message when breadth is not yet proven.
        "claim_statement": (
            "Global discovery breadth is proven for at least one country."
            if allowed
            else "Global discovery breadth is not yet proven."
        ),
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


def render_bias_markdown(
    usa_bias: dict[str, Any],
    contamination: dict[str, Any],
    breadth: dict[str, Any] | None = None,
) -> str:
    """Render bias + contamination metrics as a markdown block for prompts."""
    lines: list[str] = []
    lines.append("USA BIAS + FALLBACK CONTAMINATION METRICS")
    lines.append(
        "B_US={B_US} (cap {B_US_cap}) violation={USA_bias_violation} "
        "B_US_venue={B_US_venue} B_non_US={B_non_US} HHI={country_concentration_hhi} "
        "effective_country_count={effective_country_count} N_total={N_total}".format(**usa_bias)
    )
    if usa_bias["status"]:
        lines.append("usa_bias_status: " + ", ".join(usa_bias["status"]))
    lines.append(
        "R_static={R_static} R_memory={R_memory} R_phantom={R_phantom} "
        "R_live={R_live}".format(**contamination)
    )
    if contamination["warnings"]:
        lines.append("contamination_warnings: " + ", ".join(contamination["warnings"]))
    if breadth is not None:
        lines.append(
            "global_breadth_claim_allowed: %s" % breadth.get("global_breadth_claim_allowed")
        )
        lines.append(breadth.get("claim_statement", ""))
        if breadth.get("blocking_reasons"):
            lines.append(
                "breadth_block_reasons: " + ", ".join(breadth["blocking_reasons"])
            )
    lines.append(
        "Note: a US name is never blocked merely for being US; bias only "
        "downgrades the claim of global discovery and must be proven, not assumed."
    )
    return "\n".join(lines)


__all__ = [
    "B_US_CAP",
    "B_US_VENUE_CAP",
    "EFFECTIVE_COUNTRY_MIN",
    "CONCENTRATION_MIN_N",
    "SOURCE_CLASSES",
    "compute_usa_bias",
    "compute_contamination_ratios",
    "global_breadth_claim_allowed",
    "render_bias_markdown",
]
