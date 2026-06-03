"""Portfolio diversification cap — country & sector tiebreaker.

Pure module. Inputs: a list of already-quality-passing candidates ranked by
composite score (highest first), each with ``country`` and ``sector`` tags.

Applies, in order:
    1. Per-country cap   (default 2 picks per country)
    2. Per-sector cap    (default 2 picks per sector)
    3. Overall daily cap (default 10 picks per day)

This is a TIEBREAKER, not a quota. A name is dropped only if it would exceed a
cap among names that already passed the entry-quality gate; we never inject
weaker names to satisfy a "minimum distinct countries" target. The aspirational
``target_distinct_countries`` is logged for visibility, not enforced.

Also enforces ``country_eligibility``: candidates from countries not on the
allowlist are excluded with reason ``country_not_eligible`` (e.g. RU under
sanctions).
"""
from __future__ import annotations

from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from runtime_common import REPO_ROOT


DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "max_picks_per_day": 10,
    "max_picks_per_country": 2,
    "max_picks_per_sector": 2,
    "target_distinct_countries": 5,
    # 25 of the 30 largest-GDP set. RU excluded (sanctions); TR/ID/SA/AE
    # excluded (no clean single-name access — would require ETF-only entries
    # that the entry-quality gate cannot evaluate).
    "country_eligibility": [
        "US", "CN", "DE", "JP", "GB", "IN", "FR", "IT", "BR", "CA",
        "AU", "MX", "ES", "KR", "NL", "CH", "PL", "TW", "IE", "BE",
        "SE", "IL", "AR", "SG", "AT",
    ],
}

_THRESHOLDS_PATH = REPO_ROOT / "config" / "thresholds.yaml"


def load_diversification_config() -> dict[str, Any]:
    """Return ``portfolio_diversification`` config merged over defaults."""
    merged: dict[str, Any] = {
        k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULTS.items()
    }
    try:
        from src.utils.config_loader import load_yaml_config

        config = load_yaml_config(_THRESHOLDS_PATH)
    except Exception:
        return merged
    block = config.get("portfolio_diversification") if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return merged
    for key, value in block.items():
        merged[key] = list(value) if isinstance(value, list) else value
    return merged


def apply_diversification_cap(
    ranked_candidates: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply country/sector/day caps to a pre-ranked list.

    Each candidate must carry at least: ``ticker``, ``country``, ``sector``.
    Optional ``composite_score`` is preserved as-is (input order is treated as
    the ranking — highest first).

    Returns:
        {
            "picks":       list of selected candidates (capped),
            "dropped":     list of {ticker, reason}
                           reason ∈ {country_cap, sector_cap, day_cap,
                                     country_not_eligible},
            "distribution": {
                "picks_per_country": {country: n},
                "picks_per_sector":  {sector: n},
                "distinct_countries": int,
                "target_distinct_countries": int,
                "target_distinct_countries_met": bool,
            },
            "config_used": cfg,
        }
    """
    cfg = config or load_diversification_config()
    if not cfg.get("enabled", True):
        picks = list(ranked_candidates)
        return {
            "picks": picks,
            "dropped": [],
            "distribution": _distribution(picks, cfg),
            "config_used": cfg,
        }

    max_day = int(cfg["max_picks_per_day"])
    max_country = int(cfg["max_picks_per_country"])
    max_sector = int(cfg["max_picks_per_sector"])
    allowed_countries = {str(c).upper() for c in (cfg.get("country_eligibility") or [])}

    picks: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    per_country: dict[str, int] = {}
    per_sector: dict[str, int] = {}

    for cand in ranked_candidates:
        ticker = str(cand.get("ticker") or "").strip()
        country = str(cand.get("country") or "").strip().upper()
        sector = str(cand.get("sector") or "").strip()

        if allowed_countries and country and country not in allowed_countries:
            dropped.append({"ticker": ticker, "country": country, "sector": sector,
                            "reason": "country_not_eligible"})
            continue
        if len(picks) >= max_day:
            dropped.append({"ticker": ticker, "country": country, "sector": sector,
                            "reason": "day_cap"})
            continue
        if country and per_country.get(country, 0) >= max_country:
            dropped.append({"ticker": ticker, "country": country, "sector": sector,
                            "reason": "country_cap"})
            continue
        if sector and per_sector.get(sector, 0) >= max_sector:
            dropped.append({"ticker": ticker, "country": country, "sector": sector,
                            "reason": "sector_cap"})
            continue

        picks.append(cand)
        if country:
            per_country[country] = per_country.get(country, 0) + 1
        if sector:
            per_sector[sector] = per_sector.get(sector, 0) + 1

    return {
        "picks": picks,
        "dropped": dropped,
        "distribution": _distribution(picks, cfg),
        "config_used": cfg,
    }


def _distribution(picks: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    per_country: dict[str, int] = {}
    per_sector: dict[str, int] = {}
    for p in picks:
        c = str(p.get("country") or "").upper()
        s = str(p.get("sector") or "")
        if c:
            per_country[c] = per_country.get(c, 0) + 1
        if s:
            per_sector[s] = per_sector.get(s, 0) + 1
    target = int(cfg.get("target_distinct_countries", 0) or 0)
    return {
        "picks_per_country": per_country,
        "picks_per_sector": per_sector,
        "distinct_countries": len(per_country),
        "target_distinct_countries": target,
        "target_distinct_countries_met": len(per_country) >= target,
    }


__all__ = [
    "DEFAULTS",
    "load_diversification_config",
    "apply_diversification_cap",
]
