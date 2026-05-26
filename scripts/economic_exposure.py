"""Economic-exposure normalization + Juego de Posición theme buckets.

Capital Rotation Engine — foundation module.

This module is the *single* place where two questions are answered:

1. **What is the canonical economic identity of a ticker?**
   - ``EPA:AIR``, ``ETR:AIR``, ``AIR.PA``, ``AIR.DE``  →  ``AIRBUS``
   - ``NASDAQ:GOOGL``, ``GOOG``, ``GOOGL``             →  ``ALPHABET``
   - ``NSE:HDFCBANK``, ``HDFCBANK.NS``                 →  ``HDFC_BANK``
   - ``NSE:RELIANCE``, ``RELIANCE.NS``                 →  ``RELIANCE_INDUSTRIES``

   The point is to detect duplicate economic exposure: holding both
   ``AIR.PA`` and ``ETR:AIR`` is *one* lane on the pitch, not two
   independent diversifiers.

2. **Which theme zones (Juego de Posición pitch zones) does a ticker
   occupy?**

   Theme buckets are the operator's positional-play vocabulary.  A
   ticker can occupy several zones (e.g. ``AMD`` is both
   ``AI_SEMIS_CLOUD`` and ``HIGH_BETA_SPECULATIVE``).  Unknown tickers
   degrade to ``OTHER`` — never to a fabricated theme.

Contract — pure module
----------------------
- No DB, no filesystem, no network, no broker calls, no AI execution.
- Importing this module has no side effects.
- Deterministic for a given build.
- All outputs are advisory; no execution permission is granted.
"""
from __future__ import annotations

from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Theme bucket vocabulary
# ---------------------------------------------------------------------------

THEME_AI_SEMIS_CLOUD = "AI_SEMIS_CLOUD"
THEME_MEGA_CAP_PLATFORM = "MEGA_CAP_PLATFORM"
THEME_DEFENSE = "DEFENSE"
THEME_INDIA_LEVERAGED = "INDIA_LEVERAGED"
THEME_ENERGY_MATERIALS = "ENERGY_MATERIALS"
THEME_EUROPE_INDUSTRIALS = "EUROPE_INDUSTRIALS"
THEME_HIGH_BETA_SPECULATIVE = "HIGH_BETA_SPECULATIVE"
THEME_MACRO_HEDGE = "MACRO_HEDGE"
THEME_CASH_OPTIONALITY = "CASH_OPTIONALITY"
THEME_OTHER = "OTHER"

ALL_THEMES: tuple[str, ...] = (
    THEME_AI_SEMIS_CLOUD,
    THEME_MEGA_CAP_PLATFORM,
    THEME_DEFENSE,
    THEME_INDIA_LEVERAGED,
    THEME_ENERGY_MATERIALS,
    THEME_EUROPE_INDUSTRIALS,
    THEME_HIGH_BETA_SPECULATIVE,
    THEME_MACRO_HEDGE,
    THEME_CASH_OPTIONALITY,
    THEME_OTHER,
)

# Default Juego de Posición caps.  warning_cap < hard_cap.
THEME_CAPS: dict[str, dict[str, int]] = {
    THEME_AI_SEMIS_CLOUD: {"warning_cap": 6, "hard_cap": 8},
    THEME_MEGA_CAP_PLATFORM: {"warning_cap": 5, "hard_cap": 7},
    THEME_DEFENSE: {"warning_cap": 3, "hard_cap": 4},
    THEME_INDIA_LEVERAGED: {"warning_cap": 2, "hard_cap": 3},
    THEME_ENERGY_MATERIALS: {"warning_cap": 3, "hard_cap": 4},
    THEME_EUROPE_INDUSTRIALS: {"warning_cap": 3, "hard_cap": 5},
    THEME_HIGH_BETA_SPECULATIVE: {"warning_cap": 2, "hard_cap": 3},
    THEME_MACRO_HEDGE: {"warning_cap": 2, "hard_cap": 4},
    THEME_CASH_OPTIONALITY: {"warning_cap": 99, "hard_cap": 99},
    THEME_OTHER: {"warning_cap": 4, "hard_cap": 6},
}


# ---------------------------------------------------------------------------
# Economic-exposure key registry
# ---------------------------------------------------------------------------

# Map ticker-form  →  canonical economic exposure key.  Many ticker
# variants (NASDAQ:, NYSE:, NSE:, ETR:, EPA:, suffix ``.PA``/``.DE``/
# ``.NS``/``.CO``) map to the same company.  We strip exchange prefixes
# and country suffixes when scanning so the same company is recognized
# regardless of how the user typed it.
#
# Keys are uppercase with no exchange prefix and no country suffix.
# Example: both ``AIR`` and ``AIRBUSSE`` would need a row here; the
# lookup function below normalises the input first.
_ECONOMIC_KEY_BY_BASE: dict[str, str] = {
    # Airbus — Paris primary, Frankfurt secondary, plus the bare ticker.
    "AIR": "AIRBUS",
    # Alphabet — both share classes are one economic exposure.
    "GOOG": "ALPHABET",
    "GOOGL": "ALPHABET",
    # SAP — listed in Frankfurt + multiple ADR forms.
    "SAP": "SAP",
    # HDFC Bank — NSE + ADR.
    "HDFCBANK": "HDFC_BANK",
    "HDB": "HDFC_BANK",
    # Reliance Industries — NSE + GDR forms.
    "RELIANCE": "RELIANCE_INDUSTRIES",
    # ICICI Bank.
    "ICICIBANK": "ICICI_BANK",
    "IBN": "ICICI_BANK",
    # Larsen & Toubro.
    "LT": "LARSEN_AND_TOUBRO",
    # Tata Consultancy.
    "TCS": "TATA_CONSULTANCY",
    # Bharti Airtel.
    "BHARTIARTL": "BHARTI_AIRTEL",
    # Infosys.
    "INFY": "INFOSYS",
    # Cash / Risk-Off — these are their own economic exposure key.
    "CASH": "CASH",
    "SGOV": "SGOV",
    "BIL": "BIL",
    "SHV": "SHV",
    "GLD": "GLD",
    # Defense.
    "RHM": "RHEINMETALL",
    "LMT": "LOCKHEED_MARTIN",
    "RTX": "RTX_CORP",
    "NOC": "NORTHROP_GRUMMAN",
    "GD": "GENERAL_DYNAMICS",
    "LHX": "L3HARRIS",
    "BA.L": "BAE_SYSTEMS",
    # Energy.
    "XOM": "EXXON_MOBIL",
    "CVX": "CHEVRON",
    "SHEL": "SHELL",
    "TTE": "TOTALENERGIES",
    "BP": "BP",
    # AI / semis / platforms.
    "NVDA": "NVIDIA",
    "AMD": "AMD",
    "TSM": "TAIWAN_SEMI",
    "ASML": "ASML",
    "MSFT": "MICROSOFT",
    "AMZN": "AMAZON",
    "META": "META",
    "AAPL": "APPLE",
    "AVGO": "BROADCOM",
    "ANET": "ARISTA_NETWORKS",
    "MU": "MICRON",
    "INTC": "INTEL",
    "ORCL": "ORACLE",
    "CRM": "SALESFORCE",
    "NFLX": "NETFLIX",
    # Commodities / mining.
    "VALE": "VALE",
    "BHP": "BHP",
    "RIO": "RIO_TINTO",
    "FCX": "FREEPORT_MCMORAN",
    "SCCO": "SOUTHERN_COPPER",
    # Shipping.
    "ZIM": "ZIM",
    "DAC": "DANAOS",
    "SBLK": "STAR_BULK",
    "MAERSK-B": "MAERSK",
    "HLAG": "HAPAG_LLOYD",
    "GSL": "GLOBAL_SHIP_LEASE",
}

# Country / exchange suffixes we strip when normalising the BASE form
# for economic-key lookup.  ``.NS`` is stripped here because NSE:HDFCBANK
# and HDFCBANK.NS are the same economic exposure — leverage/sizing rules
# are applied separately based on the position metadata (country=India).
_STRIPPABLE_SUFFIXES: tuple[str, ...] = (
    ".PA",  # Paris
    ".DE",  # Xetra
    ".AS",  # Amsterdam
    ".MI",  # Milan
    ".L",   # LSE (handled below — BAE etc. need full token preserved)
    ".CO",  # Copenhagen
    ".NS",  # NSE India
    ".BO",  # BSE India
    ".HK",  # Hong Kong
    ".TO",  # Toronto
    ".TW",  # Taiwan
    ".SW",  # Swiss
    ".VI",  # Vienna
    ".ST",  # Stockholm
    ".OL",  # Oslo
    ".HE",  # Helsinki
    ".LS",  # Lisbon
    ".BR",  # Brussels
)

# Exchange prefixes (``NASDAQ:GOOGL`` etc.) — stripped before lookup.
_PREFIX_DELIMITER = ":"


# ---------------------------------------------------------------------------
# Theme membership registry
# ---------------------------------------------------------------------------

# Map economic_exposure_key  →  tuple of theme buckets.  Pure-data table,
# avoid hard-coded branching.  Order does not matter; downstream uses sets.
_THEMES_BY_EXPOSURE: dict[str, tuple[str, ...]] = {
    "AIRBUS": (THEME_DEFENSE, THEME_EUROPE_INDUSTRIALS),
    "ALPHABET": (THEME_MEGA_CAP_PLATFORM, THEME_AI_SEMIS_CLOUD),
    "AMAZON": (THEME_MEGA_CAP_PLATFORM, THEME_AI_SEMIS_CLOUD),
    "MICROSOFT": (THEME_MEGA_CAP_PLATFORM, THEME_AI_SEMIS_CLOUD),
    "META": (THEME_MEGA_CAP_PLATFORM,),
    "APPLE": (THEME_MEGA_CAP_PLATFORM,),
    "NVIDIA": (THEME_AI_SEMIS_CLOUD,),
    "AMD": (THEME_AI_SEMIS_CLOUD, THEME_HIGH_BETA_SPECULATIVE),
    "TAIWAN_SEMI": (THEME_AI_SEMIS_CLOUD,),
    "ASML": (THEME_AI_SEMIS_CLOUD, THEME_EUROPE_INDUSTRIALS),
    "BROADCOM": (THEME_AI_SEMIS_CLOUD,),
    "ARISTA_NETWORKS": (THEME_AI_SEMIS_CLOUD,),
    "MICRON": (THEME_AI_SEMIS_CLOUD, THEME_HIGH_BETA_SPECULATIVE),
    "INTEL": (THEME_AI_SEMIS_CLOUD,),
    "ORACLE": (THEME_AI_SEMIS_CLOUD, THEME_MEGA_CAP_PLATFORM),
    "SALESFORCE": (THEME_MEGA_CAP_PLATFORM,),
    "NETFLIX": (THEME_MEGA_CAP_PLATFORM,),
    "SAP": (THEME_EUROPE_INDUSTRIALS,),
    "RHEINMETALL": (THEME_DEFENSE, THEME_EUROPE_INDUSTRIALS),
    "LOCKHEED_MARTIN": (THEME_DEFENSE,),
    "RTX_CORP": (THEME_DEFENSE,),
    "NORTHROP_GRUMMAN": (THEME_DEFENSE,),
    "GENERAL_DYNAMICS": (THEME_DEFENSE,),
    "L3HARRIS": (THEME_DEFENSE,),
    "BAE_SYSTEMS": (THEME_DEFENSE, THEME_EUROPE_INDUSTRIALS),
    "EXXON_MOBIL": (THEME_ENERGY_MATERIALS,),
    "CHEVRON": (THEME_ENERGY_MATERIALS,),
    "SHELL": (THEME_ENERGY_MATERIALS, THEME_EUROPE_INDUSTRIALS),
    "TOTALENERGIES": (THEME_ENERGY_MATERIALS, THEME_EUROPE_INDUSTRIALS),
    "BP": (THEME_ENERGY_MATERIALS, THEME_EUROPE_INDUSTRIALS),
    "VALE": (THEME_ENERGY_MATERIALS, THEME_HIGH_BETA_SPECULATIVE),
    "BHP": (THEME_ENERGY_MATERIALS,),
    "RIO_TINTO": (THEME_ENERGY_MATERIALS,),
    "FREEPORT_MCMORAN": (THEME_ENERGY_MATERIALS, THEME_HIGH_BETA_SPECULATIVE),
    "SOUTHERN_COPPER": (THEME_ENERGY_MATERIALS,),
    "ZIM": (THEME_HIGH_BETA_SPECULATIVE,),
    "DANAOS": (THEME_HIGH_BETA_SPECULATIVE,),
    "STAR_BULK": (THEME_HIGH_BETA_SPECULATIVE,),
    "MAERSK": (THEME_EUROPE_INDUSTRIALS,),
    "HAPAG_LLOYD": (THEME_EUROPE_INDUSTRIALS,),
    "GLOBAL_SHIP_LEASE": (THEME_HIGH_BETA_SPECULATIVE,),
    "HDFC_BANK": (THEME_INDIA_LEVERAGED,),
    "ICICI_BANK": (THEME_INDIA_LEVERAGED,),
    "RELIANCE_INDUSTRIES": (THEME_INDIA_LEVERAGED,),
    "LARSEN_AND_TOUBRO": (THEME_INDIA_LEVERAGED,),
    "TATA_CONSULTANCY": (THEME_INDIA_LEVERAGED,),
    "BHARTI_AIRTEL": (THEME_INDIA_LEVERAGED,),
    "INFOSYS": (THEME_INDIA_LEVERAGED,),
    "CASH": (THEME_CASH_OPTIONALITY,),
    "SGOV": (THEME_CASH_OPTIONALITY,),
    "BIL": (THEME_CASH_OPTIONALITY,),
    "SHV": (THEME_CASH_OPTIONALITY,),
    "GLD": (THEME_MACRO_HEDGE,),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _strip_exchange_prefix(text: str) -> str:
    """``NASDAQ:GOOGL`` → ``GOOGL``; bare tickers passed through."""
    if _PREFIX_DELIMITER in text:
        return text.rsplit(_PREFIX_DELIMITER, 1)[-1].strip()
    return text


def _strip_country_suffix(text: str) -> str:
    """``AIR.PA`` → ``AIR``; ``HDFCBANK.NS`` → ``HDFCBANK``."""
    for suffix in _STRIPPABLE_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def _normalise_for_lookup(ticker: Any) -> str:
    """Uppercase + strip both prefix and suffix.

    The result is the base-form key used to look up the economic exposure
    key.  Empty input → empty string (caller's responsibility).
    """
    if ticker is None:
        return ""
    text = str(ticker).strip().upper()
    if not text:
        return ""
    text = _strip_exchange_prefix(text)
    text = _strip_country_suffix(text)
    return text


def normalize_economic_exposure(ticker: Any) -> str:
    """Return the canonical economic-exposure key for ``ticker``.

    Unknown tickers degrade to the upper-cased base form (so duplicate
    detection still works for unregistered names — two identical
    unknowns collide on the same key).  Empty input → empty string.
    """
    base = _normalise_for_lookup(ticker)
    if not base:
        return ""
    return _ECONOMIC_KEY_BY_BASE.get(base, base)


def map_theme_buckets(ticker: Any, metadata: dict[str, Any] | None = None) -> list[str]:
    """Return the list of theme buckets a ticker occupies.

    ``metadata`` is consulted for soft hints:
    - ``country == 'India'``    → adds ``INDIA_LEVERAGED``
    - ``leverage`` > 1          → adds ``HIGH_BETA_SPECULATIVE``
    - ``sector == 'Defense'``   → adds ``DEFENSE``
    - ``sector == 'Energy'``    → adds ``ENERGY_MATERIALS``

    Unknown tickers with no metadata cues degrade to ``[OTHER]`` — never
    to a fabricated theme.
    """
    exposure = normalize_economic_exposure(ticker)
    themes: list[str] = list(_THEMES_BY_EXPOSURE.get(exposure, ()))

    md = metadata or {}
    country = str(md.get("country") or "").strip().lower()
    if country == "india" and THEME_INDIA_LEVERAGED not in themes:
        themes.append(THEME_INDIA_LEVERAGED)
    try:
        lev = float(md.get("leverage") or 1.0)
    except (TypeError, ValueError):
        lev = 1.0
    if lev > 1.0 and THEME_HIGH_BETA_SPECULATIVE not in themes:
        # Leveraged Indian exposure is *both* INDIA_LEVERAGED and
        # HIGH_BETA_SPECULATIVE — they're independent constraints.
        themes.append(THEME_HIGH_BETA_SPECULATIVE)
    sector = str(md.get("sector") or "").strip().lower()
    if sector == "defense" and THEME_DEFENSE not in themes:
        themes.append(THEME_DEFENSE)
    if sector == "energy" and THEME_ENERGY_MATERIALS not in themes:
        themes.append(THEME_ENERGY_MATERIALS)

    if not themes:
        themes.append(THEME_OTHER)
    return themes


def detect_duplicate_economic_exposure(
    positions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return one record per economic-exposure key held more than once.

    Each record has ``economic_exposure_key`` and ``ticker_variants`` so
    the operator can see which two (or more) rows collapse to the same
    company.
    """
    by_key: dict[str, list[str]] = {}
    for pos in positions or []:
        if not isinstance(pos, dict):
            continue
        ticker = (
            pos.get("ticker")
            or pos.get("symbol")
            or pos.get("normalized_ticker")
        )
        key = normalize_economic_exposure(ticker)
        if not key:
            continue
        by_key.setdefault(key, []).append(str(ticker))
    out: list[dict[str, Any]] = []
    for key, tickers in by_key.items():
        if len(tickers) >= 2:
            out.append(
                {
                    "economic_exposure_key": key,
                    "ticker_variants": tickers,
                    "duplicate_count": len(tickers),
                }
            )
    out.sort(key=lambda r: r["economic_exposure_key"])
    return out


def theme_caps(theme: str) -> dict[str, int]:
    """Return ``{warning_cap, hard_cap}`` for a theme; missing → OTHER."""
    return dict(THEME_CAPS.get(theme, THEME_CAPS[THEME_OTHER]))


__all__ = [
    "ALL_THEMES",
    "THEME_CAPS",
    "THEME_AI_SEMIS_CLOUD",
    "THEME_MEGA_CAP_PLATFORM",
    "THEME_DEFENSE",
    "THEME_INDIA_LEVERAGED",
    "THEME_ENERGY_MATERIALS",
    "THEME_EUROPE_INDUSTRIALS",
    "THEME_HIGH_BETA_SPECULATIVE",
    "THEME_MACRO_HEDGE",
    "THEME_CASH_OPTIONALITY",
    "THEME_OTHER",
    "normalize_economic_exposure",
    "map_theme_buckets",
    "detect_duplicate_economic_exposure",
    "theme_caps",
]
