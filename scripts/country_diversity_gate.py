"""Country / region discovery-diversity gate (advisory-only).

The discovery engine must *look* globally without *forcing* trades.  This gate:

* buckets discovery candidates into regions using ``config/discovery_quotas.yaml``,
* reports whether each bucket met its ``min_discovery_names`` quota (and the
  shortfall) — WITHOUT fabricating any ticker,
* computes country-share concentration (``p_c = n_c / N``), HHI, normalized
  entropy, and a diversity score,
* raises concentration warnings at the configured thresholds, and
* applies the per-country ``max_trade_candidates`` cap by downgrading the
  weakest excess promotions to ``WATCH_CAP_LIMITED`` (never deletes a name).

Contract — pure module / advisory-only
--------------------------------------
No DB, no network, no broker calls, no AI execution.  Never emits BUY/SELL or
any execution instruction.  Diversity NEVER forces a trade and NEVER invents a
country or ticker.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts.advisory_contract import advisory_safety_stamps
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import sys

    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]

DEFAULT_QUOTAS_PATH = _REPO_ROOT / "config" / "discovery_quotas.yaml"

COUNTRY_CONCENTRATION_WARNING = "COUNTRY_CONCENTRATION_WARNING"
COUNTRY_OVERCONCENTRATION_BLOCK = "COUNTRY_OVERCONCENTRATION_BLOCK"
DISCOVERY_TOO_CONCENTRATED = "DISCOVERY_TOO_CONCENTRATED"

WATCH_CAP_LIMITED = "WATCH_CAP_LIMITED"
TRADE_CANDIDATE = "TRADE_CANDIDATE_FOR_MANUAL_REVIEW"

# Embedded defaults — used when the YAML file is missing/unparseable so
# discovery is never starved (mirrors config/discovery_quotas.yaml).
DEFAULT_QUOTAS: dict[str, Any] = {
    "daily_discovery_buckets": {
        "US": {"min_discovery_names": 5, "max_trade_candidates": 2},
        "India": {"min_discovery_names": 5, "max_trade_candidates": 2},
        "UK": {"min_discovery_names": 3, "max_trade_candidates": 1},
        "Europe": {"min_discovery_names": 5, "max_trade_candidates": 2},
        "Japan": {"min_discovery_names": 5, "max_trade_candidates": 2},
        "South Korea": {"min_discovery_names": 5, "max_trade_candidates": 2},
        "Australia_Canada": {"min_discovery_names": 3, "max_trade_candidates": 1},
        "Brazil_LatAm_EM": {"min_discovery_names": 3, "max_trade_candidates": 1},
    },
    "concentration_thresholds": {
        "country_share_warning": 0.40,
        "country_share_block": 0.60,
        "hhi_warning": 0.35,
    },
    "region_map": {
        "United States": "US", "USA": "US", "US": "US",
        "India": "India",
        "United Kingdom": "UK", "UK": "UK",
        "Germany": "Europe", "France": "Europe", "Netherlands": "Europe",
        "Spain": "Europe", "Italy": "Europe", "Switzerland": "Europe",
        "Japan": "Japan",
        "South Korea": "South Korea", "Korea": "South Korea",
        "Australia": "Australia_Canada", "Canada": "Australia_Canada",
        "Brazil": "Brazil_LatAm_EM", "Mexico": "Brazil_LatAm_EM",
        "Taiwan": "Brazil_LatAm_EM", "South Africa": "Brazil_LatAm_EM",
    },
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_quotas(path: str | Path | None = None) -> dict[str, Any]:
    """Load quota config; fall back to embedded defaults if missing/invalid."""
    p = Path(path) if path is not None else DEFAULT_QUOTAS_PATH
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("daily_discovery_buckets"):
            # Merge over defaults so a partial file still works.
            merged = {**DEFAULT_QUOTAS, **data}
            for k in ("concentration_thresholds", "region_map", "daily_discovery_buckets"):
                if k in data and isinstance(data[k], dict):
                    merged[k] = {**DEFAULT_QUOTAS.get(k, {}), **data[k]}
            return merged
    except Exception:
        pass
    return DEFAULT_QUOTAS


# --------------------------------------------------------------------------- #
# Accessors (duck-typed: dict or dataclass)
# --------------------------------------------------------------------------- #
def _get(cand: Any, name: str, default: Any = None) -> Any:
    if isinstance(cand, dict):
        return cand.get(name, default)
    return getattr(cand, name, default)


def region_for_country(country: str, quotas: dict[str, Any]) -> str:
    region_map = quotas.get("region_map", {})
    return region_map.get(str(country or "").strip(), "Other")


# --------------------------------------------------------------------------- #
# Diversity math
# --------------------------------------------------------------------------- #
def compute_diversity(candidates: Sequence[Any], quotas: dict[str, Any]) -> dict[str, Any]:
    """Country-share concentration (p_c = n_c/N), HHI, entropy, warnings."""
    countries = [str(_get(c, "country", "") or "UNKNOWN").strip() or "UNKNOWN" for c in candidates]
    n = len(countries)
    counts: dict[str, int] = {}
    for c in countries:
        counts[c] = counts.get(c, 0) + 1

    shares = {c: cnt / n for c, cnt in counts.items()} if n else {}
    hhi = sum(p * p for p in shares.values()) if n else 0.0
    k = len(counts)
    if k > 1 and n:
        h = -sum(p * math.log(p) for p in shares.values() if p > 0)
        entropy_norm = h / math.log(k)
    else:
        entropy_norm = 0.0
    diversity_score = max(0.0, min(100.0, 100.0 * entropy_norm * (1 - hhi)))

    th = quotas.get("concentration_thresholds", DEFAULT_QUOTAS["concentration_thresholds"])
    warn_th = th["country_share_warning"]
    block_th = th["country_share_block"]
    hhi_th = th["hhi_warning"]

    max_share = max(shares.values()) if shares else 0.0
    warnings: list[str] = []
    if any(p > block_th for p in shares.values()):
        warnings.append(COUNTRY_OVERCONCENTRATION_BLOCK)
    if any(p > warn_th for p in shares.values()):
        warnings.append(COUNTRY_CONCENTRATION_WARNING)
    if hhi > hhi_th:
        warnings.append(DISCOVERY_TOO_CONCENTRATED)

    return {
        "n_candidates": n,
        "country_count": k,
        "counts": dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
        "shares": {c: round(p, 4) for c, p in shares.items()},
        "max_country_share": round(max_share, 4),
        "hhi": round(hhi, 4),
        "entropy_norm": round(entropy_norm, 4),
        "diversity_score": round(diversity_score, 2),
        "concentration_warnings": warnings,
    }


# --------------------------------------------------------------------------- #
# Quota check (never fabricates)
# --------------------------------------------------------------------------- #
def check_quota(candidates: Sequence[Any], quotas: dict[str, Any]) -> dict[str, Any]:
    buckets = quotas.get("daily_discovery_buckets", {})
    by_region: dict[str, int] = {region: 0 for region in buckets}
    for c in candidates:
        region = region_for_country(_get(c, "country", ""), quotas)
        if region in by_region:
            by_region[region] += 1

    per_region: dict[str, Any] = {}
    all_met = True
    for region, cfg in buckets.items():
        discovered = by_region.get(region, 0)
        needed = int(cfg.get("min_discovery_names", 0))
        met = discovered >= needed
        all_met = all_met and met
        per_region[region] = {
            "discovered": discovered,
            "min_discovery_names": needed,
            "max_trade_candidates": int(cfg.get("max_trade_candidates", 0)),
            "quota_met": met,
            "shortfall": max(0, needed - discovered),
        }
    return {
        "per_region": per_region,
        "global_discovery_target_met": all_met,
        "regions_meeting_quota": sum(1 for r in per_region.values() if r["quota_met"]),
        "regions_total": len(per_region),
        "fabrication": "NONE — shortfalls reported, never invented",
    }


# --------------------------------------------------------------------------- #
# Per-country trade-candidate cap
# --------------------------------------------------------------------------- #
def _cap_sort_key(cand: Any) -> tuple:
    """Brief ordering: score desc, chaos asc, contra asc, liq desc, fresh desc."""
    return (
        -float(_get(cand, "discovery_score", 0.0) or 0.0),
        float(_get(cand, "chaos_risk", 0.0) or 0.0),
        float(_get(cand, "contradiction_score", 0.0) or 0.0),
        -float(_get(cand, "liquidity_score", 0.0) or 0.0),
        -float(_get(cand, "data_freshness_score", 0.0) or 0.0),
    )


def apply_trade_candidate_cap(
    candidates: Sequence[Any], quotas: dict[str, Any]
) -> list[dict[str, Any]]:
    """Cap promotions per region.  Returns one row per candidate with a final
    ``promotion_status``; excess promotions are downgraded to WATCH_CAP_LIMITED.
    """
    buckets = quotas.get("daily_discovery_buckets", {})
    promoted_by_region: dict[str, int] = {region: 0 for region in buckets}

    # Process promotion-eligible candidates strongest-first, per region.
    indexed = list(enumerate(candidates))
    eligible = [
        (i, c)
        for i, c in indexed
        if str(_get(c, "promotion_status", "") or "").upper() == TRADE_CANDIDATE
    ]
    eligible.sort(key=lambda ic: _cap_sort_key(ic[1]))

    capped_status: dict[int, str] = {}
    for i, c in eligible:
        region = region_for_country(_get(c, "country", ""), quotas)
        cap = int(buckets.get(region, {}).get("max_trade_candidates", 0))
        used = promoted_by_region.get(region, 0)
        if region in buckets and used < cap:
            promoted_by_region[region] = used + 1
            capped_status[i] = TRADE_CANDIDATE
        else:
            # Over the cap (or region outside quota table) -> downgrade.
            capped_status[i] = WATCH_CAP_LIMITED

    out: list[dict[str, Any]] = []
    for i, c in indexed:
        status = capped_status.get(i, str(_get(c, "promotion_status", "") or ""))
        out.append(
            {
                "ticker": _get(c, "ticker", ""),
                "country": _get(c, "country", ""),
                "region": region_for_country(_get(c, "country", ""), quotas),
                "discovery_score": _get(c, "discovery_score", None),
                "promotion_status": status,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Combined report
# --------------------------------------------------------------------------- #
def build_diversity_report(
    candidates: Sequence[Any], quotas: dict[str, Any] | None = None
) -> dict[str, Any]:
    q = quotas if quotas is not None else load_quotas()
    diversity = compute_diversity(candidates, q)
    quota = check_quota(candidates, q)
    capped = apply_trade_candidate_cap(candidates, q)
    n_promoted = sum(1 for r in capped if r["promotion_status"] == TRADE_CANDIDATE)
    n_cap_limited = sum(1 for r in capped if r["promotion_status"] == WATCH_CAP_LIMITED)

    report: dict[str, Any] = {
        "diversity": diversity,
        "quota": quota,
        "capped_candidates": capped,
        "promoted_count": n_promoted,
        "cap_limited_count": n_cap_limited,
        "diversity_forces_trades": False,
    }
    report.update(advisory_safety_stamps())
    report["human_execution_required"] = True
    return report


__all__ = [
    "COUNTRY_CONCENTRATION_WARNING",
    "COUNTRY_OVERCONCENTRATION_BLOCK",
    "DISCOVERY_TOO_CONCENTRATED",
    "WATCH_CAP_LIMITED",
    "TRADE_CANDIDATE",
    "DEFAULT_QUOTAS",
    "load_quotas",
    "region_for_country",
    "compute_diversity",
    "check_quota",
    "apply_trade_candidate_cap",
    "build_diversity_report",
]
