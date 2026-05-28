"""Top-30 GDP country coverage engine for the daily five-model synthesis.

Problem this fixes: the prompts name 30 countries, but nothing proved which
countries actually had a loaded universe / live price / live news / live filing
/ resolved ticker mapping, and whether those rows were consumed by synthesis.
This module computes that proof table honestly.

It is pure/advisory:
    * no broker, no execution, no network
    * reads only already-built daily-payload structures + a config override
    * never fabricates coverage — a missing layer is reported as missing

Country naming is normalized through :func:`canonical_country` so the static
universe (full names), the global securities master (ISO alpha-2), and the
asia/global disclosure loaders (mixed) all resolve to the same canonical name.

Coverage math (verbatim from the sprint spec)::

    universe_loaded(c)   = 1 if >=1 security/ticker from c is in the synthesis universe
    price_support(c)     = 1 if >=1 ticker from c has valid_price(t)=1
    news_support(c)      = 1 if >=1 fresh news/event row exists for c
    filings_support(c)   = 1 if >=1 fresh filing/disclosure row exists for c
    mapping_support(c)   = 1 if >=1 entity from c maps to a ticker with conf >= theta_map
    synthesis_consumed(c)= 1 if rows from c are in the daily payload consumed by synthesis

    coverage(c) = universe_loaded * price_support * news_support
                  * mapping_support * synthesis_consumed

    C_universe  = mean_c universe_loaded(c)
    C_price     = mean_c price_support(c)
    C_news      = mean_c news_support(c)
    C_filings   = mean_c filings_support(c)
    C_mapping   = mean_c mapping_support(c)
    C_synthesis = mean_c synthesis_consumed(c)
    C_global    = mean_c coverage(c)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
COUNTRY_COVERAGE_PATH = DAILY_PAYLOAD_DIR / "daily_country_coverage.json"
TOP30_CONFIG_PATH = REPO_ROOT / "config" / "top30_countries.yaml"

DEFAULT_THETA_MAP = 0.70

# Canonical top-30-GDP target set (ordered). This is an advisory target set,
# NOT an authoritative real-time GDP ranking. Operators may override it via
# ``config/top30_countries.yaml`` (``countries: [ ... ]``).
DEFAULT_TOP30_COUNTRIES: tuple[str, ...] = (
    "United States",
    "China",
    "Germany",
    "Japan",
    "United Kingdom",
    "India",
    "France",
    "Netherlands",
    "Taiwan",
    "Italy",
    "Russia",
    "Brazil",
    "Canada",
    "Australia",
    "Mexico",
    "Spain",
    "South Korea",
    "Turkey",
    "Indonesia",
    "Saudi Arabia",
    "Switzerland",
    "Poland",
    "Ireland",
    "Belgium",
    "Sweden",
    "Israel",
    "Argentina",
    "Singapore",
    "Austria",
    "United Arab Emirates",
)

# ISO-alpha-2 and common-alias -> canonical country name.
_COUNTRY_ALIASES: dict[str, str] = {
    "US": "United States", "USA": "United States", "U.S.": "United States",
    "UNITED STATES OF AMERICA": "United States", "AMERICA": "United States",
    "CN": "China", "PRC": "China", "MAINLAND CHINA": "China",
    "DE": "Germany", "GER": "Germany",
    "JP": "Japan", "JPN": "Japan",
    "GB": "United Kingdom", "UK": "United Kingdom", "GREAT BRITAIN": "United Kingdom",
    "ENGLAND": "United Kingdom",
    "IN": "India", "IND": "India",
    "FR": "France",
    "NL": "Netherlands", "HOLLAND": "Netherlands",
    "TW": "Taiwan", "CHINESE TAIPEI": "Taiwan",
    "IT": "Italy",
    "RU": "Russia", "RUSSIAN FEDERATION": "Russia",
    "BR": "Brazil",
    "CA": "Canada",
    "AU": "Australia",
    "MX": "Mexico",
    "ES": "Spain",
    "KR": "South Korea", "KOR": "South Korea", "KOREA": "South Korea",
    "REPUBLIC OF KOREA": "South Korea",
    "TR": "Turkey", "TURKIYE": "Turkey", "TÜRKIYE": "Turkey",
    "ID": "Indonesia",
    "SA": "Saudi Arabia", "KSA": "Saudi Arabia",
    "CH": "Switzerland",
    "PL": "Poland",
    "IE": "Ireland",
    "BE": "Belgium",
    "SE": "Sweden",
    "IL": "Israel",
    "AR": "Argentina",
    "SG": "Singapore",
    "AT": "Austria",
    "AE": "United Arab Emirates", "UAE": "United Arab Emirates",
}

# Ticker exchange suffix -> canonical country (major venues only).
_SUFFIX_COUNTRY: dict[str, str] = {
    ".NS": "India", ".BO": "India",
    ".T": "Japan",
    ".KS": "South Korea", ".KQ": "South Korea",
    ".L": "United Kingdom",
    ".DE": "Germany", ".F": "Germany",
    ".PA": "France",
    ".AS": "Netherlands",
    ".HK": "Hong Kong",
    ".TW": "Taiwan", ".TWO": "Taiwan",
    ".SS": "China", ".SZ": "China",
    ".TO": "Canada", ".V": "Canada",
    ".AX": "Australia",
    ".SA": "Brazil",
    ".MX": "Mexico",
    ".SR": "Saudi Arabia",
    ".SI": "Singapore",
    ".SW": "Switzerland",
    ".MI": "Italy",
    ".MC": "Spain",
    ".ST": "Sweden",
    ".BR": "Belgium",
    ".VI": "Austria",
    ".WA": "Poland",
    ".IS": "Turkey",
    ".TA": "Israel",
    ".BA": "Argentina",
}

# Bloc/region tokens that are NOT a single top-30 country.
_NON_COUNTRY_TOKENS = {"EU", "EUROPE", "GLOBAL", "WORLD", "INTERNATIONAL", "ROW", ""}


def canonical_country(value: Any) -> str | None:
    """Resolve a country code/name to its canonical top-30 name, or None.

    Returns None for blocs (EU/Europe/Global) and unknown values so the caller
    never silently miscounts coverage.
    """
    text = str(value or "").strip()
    if not text:
        return None
    upper = text.upper()
    if upper in _NON_COUNTRY_TOKENS:
        return None
    if upper in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[upper]
    # Title-case match against the canonical names.
    title = text.title()
    if title in DEFAULT_TOP30_COUNTRIES:
        return title
    # Special-case names that .title() mangles.
    if title in {"United States", "United Kingdom", "United Arab Emirates", "South Korea", "Saudi Arabia"}:
        return title
    return None


def country_from_ticker(ticker: Any) -> str | None:
    """Infer the canonical country from a ticker's exchange suffix, or None.

    A bare US-style ticker (no suffix) returns None here — country must come
    from explicit metadata for those, not be assumed.
    """
    text = str(ticker or "").strip().upper()
    if not text:
        return None
    for suffix, country in _SUFFIX_COUNTRY.items():
        if text.endswith(suffix.upper()):
            return country
    return None


def load_top30_countries(path: Path | None = None) -> list[str]:
    """Return the configured top-30 set, falling back to the embedded default."""
    target = path or TOP30_CONFIG_PATH
    if target.exists():
        try:
            try:
                from src.utils.config_loader import load_yaml_config
            except ModuleNotFoundError:  # pragma: no cover
                load_yaml_config = None  # type: ignore[assignment]
            if load_yaml_config is not None:
                data = load_yaml_config(target)
                if isinstance(data, dict):
                    raw = data.get("countries")
                    out: list[str] = []
                    for value in raw or []:
                        name = canonical_country(value) or str(value or "").strip()
                        if name and name not in out:
                            out.append(name)
                    if out:
                        return out
        except Exception:
            pass
    return list(DEFAULT_TOP30_COUNTRIES)


def _country_status(
    *,
    universe_loaded: int,
    price_support: int,
    news_support: int,
    filings_support: int,
    mapping_support: int,
    synthesis_consumed: int,
    coverage: int,
) -> tuple[str, str]:
    """Return (status, reason)."""
    if coverage == 1:
        return "LIVE_COVERED", "universe + price + news + mapping + consumed all present"
    if universe_loaded == 1 and synthesis_consumed == 1:
        missing = []
        if not price_support:
            missing.append("price")
        if not news_support:
            missing.append("news")
        if not filings_support:
            missing.append("filings")
        if not mapping_support:
            missing.append("mapping")
        reason = "consumed by synthesis but missing: " + ", ".join(missing) if missing else "partial"
        return "STATIC_OR_PARTIAL", reason
    if universe_loaded == 0:
        return "NOT_IN_UNIVERSE", "no security/ticker from this country in the synthesis universe"
    return "DEGRADED", "in universe but not consumed by synthesis"


def _global_discovery_status(c_global: float) -> str:
    if c_global >= 0.70:
        return "BROAD_LIVE_COVERAGE"
    if c_global >= 0.40:
        return "PARTIAL_LIVE_COVERAGE"
    if c_global > 0:
        return "THIN_LIVE_COVERAGE"
    return "NO_FULL_LIVE_COUNTRY_COVERAGE"


def compute_country_coverage(
    *,
    universe_countries: Iterable[str],
    price_countries: Iterable[str],
    news_countries: Iterable[str],
    filings_countries: Iterable[str],
    mapping_countries: Iterable[str],
    synthesis_countries: Iterable[str],
    top30: list[str] | None = None,
) -> dict[str, Any]:
    """Compute the full per-country coverage table + ratios.

    Each ``*_countries`` argument is an iterable of country names/codes already
    proven for that layer (duplicates and non-top30 values are ignored).
    """
    countries = top30 or load_top30_countries()
    n = len(countries) or 1

    def _canon_set(values: Iterable[str]) -> set[str]:
        out: set[str] = set()
        for value in values:
            name = canonical_country(value)
            if name:
                out.add(name)
        return out

    u_set = _canon_set(universe_countries)
    p_set = _canon_set(price_countries)
    news_set = _canon_set(news_countries)
    f_set = _canon_set(filings_countries)
    m_set = _canon_set(mapping_countries)
    s_set = _canon_set(synthesis_countries)

    rows: list[dict[str, Any]] = []
    sums = {"universe": 0, "price": 0, "news": 0, "filings": 0, "mapping": 0, "synthesis": 0, "coverage": 0}
    for country in countries:
        universe_loaded = 1 if country in u_set else 0
        price_support = 1 if country in p_set else 0
        news_support = 1 if country in news_set else 0
        filings_support = 1 if country in f_set else 0
        mapping_support = 1 if country in m_set else 0
        synthesis_consumed = 1 if country in s_set else 0
        coverage = (
            universe_loaded
            * price_support
            * news_support
            * mapping_support
            * synthesis_consumed
        )
        status, reason = _country_status(
            universe_loaded=universe_loaded,
            price_support=price_support,
            news_support=news_support,
            filings_support=filings_support,
            mapping_support=mapping_support,
            synthesis_consumed=synthesis_consumed,
            coverage=coverage,
        )
        sums["universe"] += universe_loaded
        sums["price"] += price_support
        sums["news"] += news_support
        sums["filings"] += filings_support
        sums["mapping"] += mapping_support
        sums["synthesis"] += synthesis_consumed
        sums["coverage"] += coverage
        rows.append(
            {
                "country": country,
                "universe_loaded": universe_loaded,
                "price_support": price_support,
                "news_support": news_support,
                "filings_support": filings_support,
                "mapping_support": mapping_support,
                "synthesis_consumed": synthesis_consumed,
                "coverage": coverage,
                "coverage_status": status,
                "reason": reason,
            }
        )

    ratios = {
        "C_universe": round(sums["universe"] / n, 4),
        "C_price": round(sums["price"] / n, 4),
        "C_news": round(sums["news"] / n, 4),
        "C_filings": round(sums["filings"] / n, 4),
        "C_mapping": round(sums["mapping"] / n, 4),
        "C_synthesis": round(sums["synthesis"] / n, 4),
        "C_global": round(sums["coverage"] / n, 4),
    }
    return {
        "top30_country_count": len(countries),
        "countries": rows,
        "ratios": ratios,
        "global_discovery_status": _global_discovery_status(ratios["C_global"]),
    }


def build_country_coverage_from_payload(
    payload: dict[str, Any],
    *,
    price_rows: list[dict[str, Any]] | None = None,
    mapping_rows: list[dict[str, Any]] | None = None,
    universe_records: list[dict[str, Any]] | None = None,
    theta_map: float = DEFAULT_THETA_MAP,
    top30: list[str] | None = None,
) -> dict[str, Any]:
    """Derive the coverage inputs from a loaded daily payload and compute coverage.

    * universe/synthesis countries come from the static universe + payload rows
      (all of which are consumed by synthesis).
    * price countries come from ``price_rows`` where ``valid_price`` is truthy.
    * news/filings countries come from fresh rows in the payload.
    * mapping countries come from ``mapping_rows`` with confidence >= theta_map.
    """
    universe_countries: list[str] = []
    synthesis_countries: list[str] = []
    news_countries: list[str] = []
    filings_countries: list[str] = []

    def _row_country(row: dict[str, Any]) -> str | None:
        return (
            canonical_country(row.get("country"))
            or canonical_country(row.get("jurisdiction"))
            or country_from_ticker(row.get("ticker") or row.get("symbol"))
        )

    if universe_records is None:
        try:
            from scripts.minimum_daily_universe import minimum_universe_records
        except ModuleNotFoundError:  # pragma: no cover
            from minimum_daily_universe import minimum_universe_records
        universe_records = minimum_universe_records()
    for row in universe_records or []:
        country = _row_country(row)
        if country:
            universe_countries.append(country)
            synthesis_countries.append(country)

    for row in payload.get("price_movers", {}).get("movers", []) or []:
        country = _row_country(row)
        if country:
            synthesis_countries.append(country)

    def _is_fresh_row(row: dict[str, Any]) -> bool:
        if row.get("is_live"):
            return True
        fr = str(row.get("freshness") or "").upper()
        return fr in {"FRESH_TODAY", "UPDATED_TODAY", "FRESH", "LIVE"}

    for row in payload.get("news_events", {}).get("events", []) or []:
        country = _row_country(row)
        if not country:
            continue
        synthesis_countries.append(country)
        if _is_fresh_row(row):
            news_countries.append(country)

    for row in payload.get("filings_events", {}).get("events", []) or []:
        country = _row_country(row)
        if not country:
            continue
        synthesis_countries.append(country)
        if _is_fresh_row(row):
            filings_countries.append(country)

    price_countries: list[str] = []
    for row in price_rows or []:
        if not row.get("valid_price"):
            continue
        country = _row_country(row)
        if country:
            price_countries.append(country)

    mapping_countries: list[str] = []
    for row in mapping_rows or []:
        try:
            conf = float(row.get("mapping_confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < theta_map:
            continue
        country = canonical_country(row.get("country")) or country_from_ticker(row.get("ticker"))
        if country:
            mapping_countries.append(country)

    result = compute_country_coverage(
        universe_countries=universe_countries,
        price_countries=price_countries,
        news_countries=news_countries,
        filings_countries=filings_countries,
        mapping_countries=mapping_countries,
        synthesis_countries=synthesis_countries,
        top30=top30,
    )
    result["theta_map"] = theta_map
    result["generated_at_utc"] = utc_timestamp()
    result["safety"] = advisory_safety_stamps()
    return result


def render_country_coverage_markdown(coverage: dict[str, Any]) -> str:
    """Render the country-coverage proof table as a markdown block for prompts."""
    ratios = coverage["ratios"]
    lines: list[str] = []
    lines.append("TOP-30 GDP COUNTRY COVERAGE PROOF")
    lines.append(
        f"global_discovery_status: {coverage['global_discovery_status']} "
        f"(C_global={ratios['C_global']})"
    )
    lines.append(
        "C_universe={C_universe} C_price={C_price} C_news={C_news} "
        "C_filings={C_filings} C_mapping={C_mapping} C_synthesis={C_synthesis}".format(**ratios)
    )
    lines.append("")
    lines.append("| Country | Universe | Price | News | Filings | Mapping | Consumed | Status | Reason |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|---|")
    yes = lambda v: "yes" if v else "no"  # noqa: E731
    for row in coverage["countries"]:
        lines.append(
            "| {country} | {u} | {p} | {n} | {f} | {m} | {s} | {status} | {reason} |".format(
                country=row["country"],
                u=yes(row["universe_loaded"]),
                p=yes(row["price_support"]),
                n=yes(row["news_support"]),
                f=yes(row["filings_support"]),
                m=yes(row["mapping_support"]),
                s=yes(row["synthesis_consumed"]),
                status=row["coverage_status"],
                reason=row["reason"],
            )
        )
    lines.append("")
    lines.append(
        "Note: low coverage downgrades discovery confidence and must be surfaced; "
        "it must NEVER create fake buys. Static-only countries are research-grade."
    )
    return "\n".join(lines)


def write_country_coverage(coverage: dict[str, Any], path: Path | None = None) -> Path:
    target = path or COUNTRY_COVERAGE_PATH
    ensure_directory(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="Compute top-30 GDP country coverage proof.")
    parser.add_argument("--write", action="store_true", help="write daily_country_coverage.json")
    parser.add_argument("--markdown", action="store_true", help="print the markdown table")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    try:
        from scripts.daily_payload import load_daily_payload
    except ModuleNotFoundError:
        from daily_payload import load_daily_payload
    payload = load_daily_payload()
    coverage = build_country_coverage_from_payload(payload)
    if args.write:
        write_country_coverage(coverage)
    if args.markdown:
        sys.stdout.write(render_country_coverage_markdown(coverage) + "\n")
    else:
        sys.stdout.write(json.dumps(coverage["ratios"], indent=2) + "\n")
    return 0


__all__ = [
    "DEFAULT_TOP30_COUNTRIES",
    "DEFAULT_THETA_MAP",
    "canonical_country",
    "country_from_ticker",
    "load_top30_countries",
    "compute_country_coverage",
    "build_country_coverage_from_payload",
    "render_country_coverage_markdown",
    "write_country_coverage",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
