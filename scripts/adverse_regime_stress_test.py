"""Adverse Regime Stress Test (ARST) — P1 interpretation-defense module.

Ships the reflection thesis "stress reveals the hidden variable" — ask *what
happens under heat?* before a live signal is treated as high quality (see
docs/INTERPRETATION_DEFENSE_COMPONENT_MAP.md). Conceptual lineage:
scripts/regime_translation_tester.py (friction stressors) and
scripts/tail_loss_governor.py (chaos-loss bounding); ARST is the candidate-level
analog that works on the clean fresh-discovery payload (where balance-sheet
fundamentals are usually absent).

    SurvivalScore     = ResistanceCapacity / max(StressLoad, eps)
    StressFailureRisk = 100 * clamp(1 - min(SurvivalScore, 1), 0, 1)

Data honesty: fundamentals are usually missing for fresh discovery. ARST does
NOT fabricate resistance. With no fundamentals it returns ``INSUFFICIENT_DATA``
and floors the failure risk — it never claims a thesis is stress-robust without
evidence. Sector/theme priors are used only as *weak* stress-load diagnostics.

Never invents or promotes candidates. Advisory-only. Pure module.
"""
from __future__ import annotations

from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.daily_payload import normalize_ticker
    from scripts.fresh_discovery_contract import VERIFIED_LIVE
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from daily_payload import normalize_ticker
    from fresh_discovery_contract import VERIFIED_LIVE


GRADE_ROBUST = "ROBUST"
GRADE_WATCH = "WATCH_STRESS"
GRADE_FRAGILE = "FRAGILE"
GRADE_INSUFFICIENT = "INSUFFICIENT_DATA"

_EPS = 1e-6

# Sector/theme priors that raise specific stress loads (weak diagnostics only).
_REGULATORY_THEMES = ("SEMI", "CHIP", "DEFENSE", "DEFENCE", "BANK", "FINANC", "PHARMA", "TELECOM")
_GEOPOLITICAL_THEMES = ("DEFENSE", "DEFENCE", "ENERGY", "OIL", "CHINA", "SEMI", "CHIP", "URANIUM")
_SUPPLYCHAIN_THEMES = ("SEMI", "CHIP", "HARDWARE", "AUTO", "EV", "BATTERY")
_CROWDED_THEMES = ("AI", "MEME", "HYPE", "QUANTUM", "CRYPTO")

_SCENARIOS = (
    "recession", "liquidity_shock", "margin_compression",
    "rate_shock", "regulatory_shock", "geopolitical_shock",
)


def _clamp01(value: float) -> float:
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _theme_blob(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(k) or "").upper() for k in ("sector", "theme", "country", "region")
    )


def _stress_load(candidate: dict[str, Any], fundamentals: dict[str, Any]) -> tuple[float, dict[str, dict[str, Any]], list[str]]:
    blob = _theme_blob(candidate)
    flags: list[str] = []
    loads: dict[str, float] = {}

    leverage = float(fundamentals.get("leverage") or candidate.get("leverage") or 1.0)
    leverage_load = _clamp01((leverage - 1.0) / 3.0)  # 1x→0, 4x→1
    if leverage > 1.0:
        flags.append(f"leverage_{leverage}x")

    beta = fundamentals.get("beta")
    beta_load = _clamp01((float(beta) - 1.0) / 1.0) if beta is not None else (
        0.6 if any(t in blob for t in _CROWDED_THEMES) else 0.3
    )
    if any(t in blob for t in _CROWDED_THEMES):
        flags.append("crowded_or_high_beta_theme")

    regulatory = 0.6 if any(t in blob for t in _REGULATORY_THEMES) else 0.2
    geopolitical = 0.6 if any(t in blob for t in _GEOPOLITICAL_THEMES) else 0.2
    supply = 0.6 if any(t in blob for t in _SUPPLYCHAIN_THEMES) else 0.2
    fx = 0.5 if (str(candidate.get("ticker") or "").upper().endswith(".NS")
                 or (str(candidate.get("country") or "").upper() not in ("", "UNKNOWN", "UNITED STATES", "USA", "US"))) else 0.2

    loads = {
        "recession": _clamp01(0.5 * leverage_load + 0.5 * beta_load),
        "liquidity_shock": _clamp01(0.6 * leverage_load + 0.4 * beta_load),
        "margin_compression": _clamp01(fundamentals.get("margin_pressure", 0.4) if fundamentals else 0.4),
        "rate_shock": _clamp01(0.5 * leverage_load + 0.5 * fx),
        "regulatory_shock": regulatory,
        "geopolitical_shock": geopolitical,
    }
    # Extra named loads surfaced as scenarios via flags.
    if regulatory >= 0.6:
        flags.append("sector_regulatory_exposure")
    if geopolitical >= 0.6:
        flags.append("geopolitical_exposure")
    if supply >= 0.6:
        flags.append("supply_chain_exposure")

    scenarios = {s: {"load": round(loads[s], 4)} for s in _SCENARIOS}
    overall = sum(loads.values()) / len(loads)
    return _clamp01(overall), scenarios, flags


def _resistance(fundamentals: dict[str, Any]) -> tuple[float, bool, list[str]]:
    """ResistanceCapacity from fundamentals. Returns (capacity, sufficient, missing)."""
    indicators: list[float] = []
    missing: list[str] = []

    def take(key: str, transform) -> None:
        value = fundamentals.get(key)
        if value is None:
            missing.append(key)
        else:
            indicators.append(_clamp01(transform(float(value))))

    take("debt_to_equity", lambda v: 1.0 - _clamp01(v / 2.0))     # low debt → resistant
    take("gross_margin", lambda v: _clamp01(v))                   # 0..1
    take("current_ratio", lambda v: _clamp01((v - 0.5) / 1.5))    # liquidity
    take("earnings_stability", lambda v: _clamp01(v))             # 0..1
    take("interest_coverage", lambda v: _clamp01(v / 5.0))        # debt service

    sufficient = len(indicators) >= 3
    capacity = sum(indicators) / len(indicators) if indicators else 0.0
    return _clamp01(capacity), sufficient, missing


def stress_test_candidate(
    candidate: dict[str, Any],
    *,
    fundamentals: dict[str, Any] | None = None,
    model_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the ARST record for one clean fresh-discovery candidate."""
    ticker = normalize_ticker(candidate.get("ticker"))
    fundamentals = dict(fundamentals or {})

    # A non-live candidate is never stress-tested as robust — diagnostic only.
    not_live = candidate.get("is_live") is not True or candidate.get("source_health") != VERIFIED_LIVE

    stress_load, scenarios, stress_flags = _stress_load(candidate, fundamentals)
    resistance, data_sufficient, missing = _resistance(fundamentals)

    survival = resistance / max(stress_load, _EPS)
    failure_risk = round(100.0 * _clamp01(1.0 - min(survival, 1.0)), 4)

    if not data_sufficient or not_live:
        grade = GRADE_INSUFFICIENT
        failure_risk = max(failure_risk, 60.0)
        if not_live:
            stress_flags.append("not_live_not_stress_tested")
    elif survival >= 1.25:
        grade = GRADE_ROBUST
    elif survival >= 1.00:
        grade = GRADE_WATCH
    else:
        grade = GRADE_FRAGILE

    return {
        "ticker": ticker,
        "survival_score": round(survival, 4),
        "stress_failure_risk": round(failure_risk, 4),
        "grade": grade,
        "resistance_capacity": round(resistance, 6),
        "stress_load": round(stress_load, 6),
        "data_sufficient": bool(data_sufficient and not not_live),
        "stress_flags": stress_flags,
        "missing_stress_fields": missing,
        "stress_scenarios": scenarios,
        "advisory_only": True,
    }


__all__ = [
    "GRADE_ROBUST",
    "GRADE_WATCH",
    "GRADE_FRAGILE",
    "GRADE_INSUFFICIENT",
    "stress_test_candidate",
]
