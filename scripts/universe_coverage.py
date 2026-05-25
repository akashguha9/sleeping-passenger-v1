"""Universe coverage — provider/jurisdiction/leverage metadata + score.

Sprint 3 — Part 6.  Encodes the 44-ticker advisory universe (with bucket,
jurisdiction, leverage policy, and per-provider mapping) so the release
gate can confirm the same universe the daily-signal pipeline operates on.

Pure module: no broker, no execution, no network.  Reads no DB.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover
    import advisory_contract as _contract  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_PATH = (
    REPO_ROOT / "runtime" / "release" / "universe_coverage_summary.json"
)

# Required jurisdiction set the operator wants visibility into.  EU equities
# are not in this MVP universe yet (no European tickers are currently mapped
# to provider feeds); honest coverage covers US, India, and Global macro
# proxies only.  Adding EU later requires both a yfinance symbol mapping and
# an SEC/filings equivalent (EU disclosures), which is a separate sprint.
REQUIRED_JURISDICTIONS: tuple[str, ...] = ("US", "IN", "GLOBAL")
# Required buckets — a candidate must come from one of these.
REQUIRED_BUCKETS: tuple[str, ...] = (
    "us_megacap_tech", "us_financials", "us_energy",
    "us_consumer", "us_health", "us_industrials",
    "us_index_etf", "global_macro", "india_equity",
    "crypto_proxy",
)
REQUIRED_TICKER_COUNT = 44


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Universe definition (44 tickers).  All entries are public and advisory-only.
# ---------------------------------------------------------------------------


def _build_universe() -> list[dict[str, Any]]:
    """Return the 44-ticker universe with full provider metadata.

    The yfinance / SEC CIK / news term fields are intentionally explicit so
    the operator-run live refresh and provider compliance trace can be
    reproduced deterministically.
    """
    tickers: list[dict[str, Any]] = []

    def add(symbol: str, exchange: str, country: str, currency: str,
            bucket: str, *,
            yf_symbol: str | None = None,
            sec_cik: str | None = None,
            news_terms: list[str] | None = None,
            eligible_filing: bool = True,
            eligible_news: bool = True,
            leverage: str = "spot_only") -> None:
        tickers.append({
            "symbol": symbol,
            "exchange": exchange,
            "country": country,
            "currency": currency,
            "bucket": bucket,
            "provider_symbol_yfinance": yf_symbol or symbol,
            "sec_cik": sec_cik,
            "gdelt_query_terms": news_terms or [symbol],
            "eligible_for_price_provider": True,
            "eligible_for_filing_provider": bool(eligible_filing and sec_cik),
            "eligible_for_news_provider": bool(eligible_news),
            "leverage_policy": leverage,
            "advisory_only": True,
        })

    # us_megacap_tech — 7
    add("AAPL", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0000320193", news_terms=["Apple", "AAPL"])
    add("MSFT", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0000789019", news_terms=["Microsoft", "MSFT"])
    add("NVDA", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0001045810", news_terms=["NVIDIA", "Nvidia", "NVDA"])
    add("AMZN", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0001018724", news_terms=["Amazon", "AMZN"])
    add("GOOGL", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0001652044", news_terms=["Alphabet", "Google", "GOOGL"])
    add("META", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0001326801", news_terms=["Meta", "Facebook", "META"])
    add("TSLA", "NASDAQ", "US", "USD", "us_megacap_tech",
        sec_cik="0001318605", news_terms=["Tesla", "TSLA"])

    # us_financials — 5
    add("JPM", "NYSE", "US", "USD", "us_financials",
        sec_cik="0000019617", news_terms=["JPMorgan", "JPM"])
    add("BAC", "NYSE", "US", "USD", "us_financials",
        sec_cik="0000070858", news_terms=["Bank of America", "BAC"])
    add("WFC", "NYSE", "US", "USD", "us_financials",
        sec_cik="0000072971", news_terms=["Wells Fargo", "WFC"])
    add("GS", "NYSE", "US", "USD", "us_financials",
        sec_cik="0000886982", news_terms=["Goldman Sachs", "GS"])
    add("MS", "NYSE", "US", "USD", "us_financials",
        sec_cik="0000895421", news_terms=["Morgan Stanley", "MS"])

    # us_energy — 4
    add("XOM", "NYSE", "US", "USD", "us_energy",
        sec_cik="0000034088", news_terms=["Exxon", "XOM"])
    add("CVX", "NYSE", "US", "USD", "us_energy",
        sec_cik="0000093410", news_terms=["Chevron", "CVX"])
    add("COP", "NYSE", "US", "USD", "us_energy",
        sec_cik="0001163165", news_terms=["ConocoPhillips", "COP"])
    add("SLB", "NYSE", "US", "USD", "us_energy",
        sec_cik="0000087347", news_terms=["Schlumberger", "SLB"])

    # us_consumer — 4
    add("WMT", "NYSE", "US", "USD", "us_consumer",
        sec_cik="0000104169", news_terms=["Walmart", "WMT"])
    add("KO", "NYSE", "US", "USD", "us_consumer",
        sec_cik="0000021344", news_terms=["Coca-Cola", "KO"])
    add("PEP", "NASDAQ", "US", "USD", "us_consumer",
        sec_cik="0000077476", news_terms=["PepsiCo", "PEP"])
    add("COST", "NASDAQ", "US", "USD", "us_consumer",
        sec_cik="0000909832", news_terms=["Costco", "COST"])

    # us_health — 4
    add("JNJ", "NYSE", "US", "USD", "us_health",
        sec_cik="0000200406", news_terms=["Johnson & Johnson", "JNJ"])
    add("UNH", "NYSE", "US", "USD", "us_health",
        sec_cik="0000731766", news_terms=["UnitedHealth", "UNH"])
    add("PFE", "NYSE", "US", "USD", "us_health",
        sec_cik="0000078003", news_terms=["Pfizer", "PFE"])
    add("LLY", "NYSE", "US", "USD", "us_health",
        sec_cik="0000059478", news_terms=["Eli Lilly", "LLY"])

    # us_industrials — 4
    add("CAT", "NYSE", "US", "USD", "us_industrials",
        sec_cik="0000018230", news_terms=["Caterpillar", "CAT"])
    add("BA", "NYSE", "US", "USD", "us_industrials",
        sec_cik="0000012927", news_terms=["Boeing", "BA"])
    add("HON", "NASDAQ", "US", "USD", "us_industrials",
        sec_cik="0000773840", news_terms=["Honeywell", "HON"])
    add("GE", "NYSE", "US", "USD", "us_industrials",
        sec_cik="0000040545", news_terms=["GE", "General Electric"])

    # us_index_etf — 4
    add("SPY", "NYSEARCA", "US", "USD", "us_index_etf",
        news_terms=["S&P 500", "SPY"], eligible_filing=False)
    add("QQQ", "NASDAQ", "US", "USD", "us_index_etf",
        news_terms=["NASDAQ-100", "QQQ"], eligible_filing=False)
    add("IWM", "NYSEARCA", "US", "USD", "us_index_etf",
        news_terms=["Russell 2000", "IWM"], eligible_filing=False)
    add("DIA", "NYSEARCA", "US", "USD", "us_index_etf",
        news_terms=["Dow Jones", "DIA"], eligible_filing=False)

    # global_macro — 4
    add("GLD", "NYSEARCA", "GLOBAL", "USD", "global_macro",
        news_terms=["gold", "GLD"], eligible_filing=False)
    add("TLT", "NASDAQ", "US", "USD", "global_macro",
        news_terms=["treasury", "TLT"], eligible_filing=False)
    add("EFA", "NYSEARCA", "GLOBAL", "USD", "global_macro",
        news_terms=["EAFE", "EFA"], eligible_filing=False)
    add("EEM", "NYSEARCA", "GLOBAL", "USD", "global_macro",
        news_terms=["emerging markets", "EEM"], eligible_filing=False)

    # india_equity — 5 (India spot OR up to 4x leverage allowed)
    add("RELIANCE.NS", "NSE", "IN", "INR", "india_equity",
        yf_symbol="RELIANCE.NS",
        news_terms=["Reliance Industries"],
        eligible_filing=False, leverage="india_max_4x")
    add("TCS.NS", "NSE", "IN", "INR", "india_equity",
        yf_symbol="TCS.NS",
        news_terms=["Tata Consultancy", "TCS"],
        eligible_filing=False, leverage="india_max_4x")
    add("INFY.NS", "NSE", "IN", "INR", "india_equity",
        yf_symbol="INFY.NS",
        news_terms=["Infosys"],
        eligible_filing=False, leverage="india_max_4x")
    add("HDFCBANK.NS", "NSE", "IN", "INR", "india_equity",
        yf_symbol="HDFCBANK.NS",
        news_terms=["HDFC Bank"],
        eligible_filing=False, leverage="india_max_4x")
    add("ICICIBANK.NS", "NSE", "IN", "INR", "india_equity",
        yf_symbol="ICICIBANK.NS",
        news_terms=["ICICI Bank"],
        eligible_filing=False, leverage="india_max_4x")

    # crypto_proxy — 3 (price tracked via ETF / coin proxies; spot-only)
    add("IBIT", "NASDAQ", "US", "USD", "crypto_proxy",
        news_terms=["bitcoin ETF", "IBIT"], eligible_filing=False)
    add("FBTC", "NYSEARCA", "US", "USD", "crypto_proxy",
        news_terms=["bitcoin ETF", "FBTC"], eligible_filing=False)
    add("ETHE", "NYSEARCA", "US", "USD", "crypto_proxy",
        news_terms=["Ethereum ETF", "ETHE"], eligible_filing=False)

    return tickers


UNIVERSE: list[dict[str, Any]] = _build_universe()
assert len(UNIVERSE) == REQUIRED_TICKER_COUNT, (
    f"universe must hold {REQUIRED_TICKER_COUNT} tickers; got {len(UNIVERSE)}"
)


def universe_coverage_score(
    *,
    ticker_count: int,
    covered_buckets: int,
    mapped_provider_fields: int,
    covered_jurisdictions: int,
    leverage_policy_present: bool,
    required_provider_fields: int,
    required_buckets: int = len(REQUIRED_BUCKETS),
    required_jurisdictions: int = len(REQUIRED_JURISDICTIONS),
    required_ticker_count: int = REQUIRED_TICKER_COUNT,
) -> float:
    def _ratio(n: int, d: int) -> float:
        if d <= 0:
            return 0.0
        return min(1.0, max(0.0, n / d))
    raw = (
        0.25 * _ratio(ticker_count, required_ticker_count)
        + 0.25 * _ratio(covered_buckets, required_buckets)
        + 0.25 * _ratio(mapped_provider_fields, required_provider_fields)
        + 0.15 * _ratio(covered_jurisdictions, required_jurisdictions)
        + 0.10 * (1.0 if leverage_policy_present else 0.0)
    )
    return round(10.0 * max(0.0, min(1.0, raw)), 4)


def build_summary() -> dict[str, Any]:
    universe = list(UNIVERSE)
    n = len(universe)
    buckets_present = {row["bucket"] for row in universe}
    jurisdictions_present = {row["country"] for row in universe}
    yf_mapped = sum(1 for row in universe if row.get("provider_symbol_yfinance"))
    news_mapped = sum(1 for row in universe if row.get("gdelt_query_terms"))
    leverage_present = all(row.get("leverage_policy") for row in universe)

    india_spot_violations = [
        row["symbol"] for row in universe
        if row["country"] != "IN" and row.get("leverage_policy") != "spot_only"
    ]
    sec_eligible = sum(1 for row in universe if row["eligible_for_filing_provider"])

    score = universe_coverage_score(
        ticker_count=n,
        covered_buckets=len(buckets_present & set(REQUIRED_BUCKETS)),
        mapped_provider_fields=yf_mapped + news_mapped,
        covered_jurisdictions=len(jurisdictions_present & set(REQUIRED_JURISDICTIONS)),
        leverage_policy_present=leverage_present,
        required_provider_fields=n + n,
    )
    return {
        "report": "universe_coverage_summary",
        "ok": (score >= 9.5 and not india_spot_violations
               and len(buckets_present & set(REQUIRED_BUCKETS)) == len(REQUIRED_BUCKETS)),
        "generated_at_utc": _utc_iso(),
        "ticker_count": n,
        "required_ticker_count": REQUIRED_TICKER_COUNT,
        "buckets_present": sorted(buckets_present),
        "required_buckets": list(REQUIRED_BUCKETS),
        "jurisdictions_present": sorted(jurisdictions_present),
        "required_jurisdictions": list(REQUIRED_JURISDICTIONS),
        "yfinance_mapped_count": yf_mapped,
        "news_mapped_count": news_mapped,
        "filing_eligible_count": sec_eligible,
        "leverage_policy_present_for_all": bool(leverage_present),
        "india_spot_policy_violations": india_spot_violations,
        "universe": universe,
        "universe_coverage_score": score,
        "advisory_only": True,
        **_contract.advisory_safety_stamps(),
    }


def write_summary(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_SUMMARY_PATH
    summary = build_summary()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    summary["summary_path"] = str(target)
    return summary


def read_summary(path: Path | None = None) -> dict[str, Any] | None:
    target = path or DEFAULT_SUMMARY_PATH
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="universe_coverage.py")
    p.add_argument("--write-summary", action="store_true")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = write_summary() if args.write_summary else build_summary()
    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"universe_coverage_score = {summary['universe_coverage_score']}")
        print(f"  tickers     : {summary['ticker_count']}/"
              f"{summary['required_ticker_count']}")
        print(f"  buckets     : {summary['buckets_present']}")
        print(f"  jurisdictions: {summary['jurisdictions_present']}")
    return 0


__all__ = [
    "DEFAULT_SUMMARY_PATH",
    "REQUIRED_BUCKETS", "REQUIRED_JURISDICTIONS", "REQUIRED_TICKER_COUNT",
    "UNIVERSE",
    "universe_coverage_score",
    "build_summary", "write_summary", "read_summary",
]


if __name__ == "__main__":
    raise SystemExit(main())
