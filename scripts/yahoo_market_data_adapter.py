from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.runtime_common import (
        EXTERNAL_MARKS_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
except ModuleNotFoundError:
    from runtime_common import (
        EXTERNAL_MARKS_PATH,
        load_current_pipeline_state,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )


AUTHORITY_BIAS_RISK = "medium"
VALIDATION_DEPENDENCY = "high"
PRIOR_WEIGHT_CAPPED = 0.35


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    number = _coerce_float(value)
    if number is None:
        return None
    return int(number)


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(
            microsecond=0
        ).isoformat()
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _freshness_classification(
    observed_at: str | None,
    fetched_at: str,
) -> str:
    observed_dt = _iso_timestamp(observed_at)
    fetched_dt = _iso_timestamp(fetched_at)
    if observed_dt is None or fetched_dt is None:
        return "unknown"
    observed = datetime.fromisoformat(observed_dt)
    fetched = datetime.fromisoformat(fetched_dt)
    age_seconds = (fetched - observed).total_seconds()
    if age_seconds < 0:
        return "clock_skew"
    if age_seconds <= 15 * 60:
        return "fresh"
    if age_seconds <= 24 * 60 * 60:
        return "delayed"
    return "stale"


def _pct_change(current: float | None, base: float | None) -> float | None:
    if current is None or base in {None, 0.0}:
        return None
    return round(((current / base) - 1.0) * 100.0, 4)


def _history_close_values(raw_history: Any) -> list[float]:
    if raw_history is None:
        return []
    if hasattr(raw_history, "__getitem__"):
        try:
            close_series = raw_history["Close"]
        except Exception:
            close_series = None
        if close_series is not None:
            try:
                return [
                    float(value)
                    for value in list(close_series)
                    if value is not None and not isinstance(value, bool)
                ]
            except Exception:
                pass
    if isinstance(raw_history, list):
        values: list[float] = []
        for row in raw_history:
            if isinstance(row, dict):
                close_value = _coerce_float(row.get("close"))
                if close_value is not None:
                    values.append(close_value)
        return values
    return []


def _history_context(raw_history: Any, last_price: float | None) -> dict[str, float | None]:
    closes = _history_close_values(raw_history)
    if not closes:
        return {
            "context_5d_change_pct": None,
            "context_1mo_change_pct": None,
        }
    last_close = closes[-1]
    anchor_5d = closes[-5] if len(closes) >= 5 else closes[0]
    anchor_1mo = closes[0]
    effective_last = last_price if last_price is not None else last_close
    return {
        "context_5d_change_pct": _pct_change(effective_last, anchor_5d),
        "context_1mo_change_pct": _pct_change(effective_last, anchor_1mo),
    }


def _fetch_symbol_with_yfinance(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - exercised via mocked failure
        raise RuntimeError("yfinance is not installed in this environment") from exc

    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker must be a non-empty string")

    instrument = yf.Ticker(symbol)
    fast_info = instrument.fast_info or {}
    info = instrument.info or {}
    history = instrument.history(period="1mo", interval="1d", auto_adjust=False)

    return {
        "last_price": _coerce_float(
            fast_info.get("lastPrice") or info.get("regularMarketPrice")
        ),
        "currency": str(
            fast_info.get("currency") or info.get("currency") or ""
        ).strip()
        or None,
        "previous_close": _coerce_float(
            fast_info.get("previousClose") or info.get("previousClose")
        ),
        "open": _coerce_float(
            fast_info.get("open") or info.get("regularMarketOpen")
        ),
        "day_high": _coerce_float(
            fast_info.get("dayHigh")
            or info.get("dayHigh")
            or info.get("regularMarketDayHigh")
        ),
        "day_low": _coerce_float(
            fast_info.get("dayLow")
            or info.get("dayLow")
            or info.get("regularMarketDayLow")
        ),
        "volume": _coerce_int(
            fast_info.get("lastVolume")
            or info.get("volume")
            or info.get("regularMarketVolume")
        ),
        "regular_market_time": _iso_timestamp(
            info.get("regularMarketTime") or info.get("currentTradingPeriod")
        ),
        "raw_history": history,
    }


def fetch_yahoo_mark_row(
    ticker: str,
    runtime_state: dict[str, Any],
    fetched_at: str | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fetch_timestamp = fetched_at or utc_timestamp()
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("ticker must be a non-empty string")
    mark_key = (
        fetch_timestamp.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("T", "_")
    )

    error_state: str | None = None
    raw_payload: dict[str, Any] = {}
    ok = False
    try:
        raw_payload = (fetcher or _fetch_symbol_with_yfinance)(symbol) or {}
        ok = True
    except Exception as exc:
        error_state = str(exc)

    last_price = _coerce_float(raw_payload.get("last_price"))
    history_context = _history_context(raw_payload.get("raw_history"), last_price)
    regular_market_time = _iso_timestamp(raw_payload.get("regular_market_time"))

    row = stamp_payload(
        {
            "artifact_kind": "external_market_mark",
            "mark_id": f"yahoo_mark_{symbol}_{mark_key}",
            "ticker": symbol,
            "fetched_at": fetch_timestamp,
            "observed_at": regular_market_time or fetch_timestamp,
            "source_name": "yahoo_finance",
            "source_type": "external_market_data",
            "source_truth_note": (
                "External Yahoo Finance observation for paper marking only; "
                "not a broker execution feed."
            ),
            "authority_bias_risk": AUTHORITY_BIAS_RISK,
            "validation_dependency": VALIDATION_DEPENDENCY,
            "prior_weight_capped": PRIOR_WEIGHT_CAPPED,
            "ok": bool(ok and last_price is not None),
            "retrieval_error": error_state if error_state else None,
            "last_price": last_price,
            "currency": raw_payload.get("currency"),
            "previous_close": _coerce_float(raw_payload.get("previous_close")),
            "open": _coerce_float(raw_payload.get("open")),
            "day_high": _coerce_float(raw_payload.get("day_high")),
            "day_low": _coerce_float(raw_payload.get("day_low")),
            "volume": _coerce_int(raw_payload.get("volume")),
            "regular_market_time": regular_market_time,
            "context_5d_change_pct": history_context["context_5d_change_pct"],
            "context_1mo_change_pct": history_context["context_1mo_change_pct"],
            "staleness_classification": _freshness_classification(
                observed_at=regular_market_time,
                fetched_at=fetch_timestamp,
            ),
        },
        runtime_state=runtime_state,
    )
    if row["ok"] is False and row["retrieval_error"] is None:
        row["retrieval_error"] = "no_last_price"
    return row


def build_external_market_marks_report(
    tickers: list[str],
    runtime_state: dict[str, Any] | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    base_state = runtime_state or load_current_pipeline_state()
    normalized_tickers = sorted({str(ticker or "").strip().upper() for ticker in tickers if str(ticker or "").strip()})
    fetch_timestamp = fetched_at or utc_timestamp()

    provisional_state = dict(base_state)
    provisional_state["external_observation_active"] = False
    provisional_state["external_observation_source"] = "yahoo_finance"
    provisional_state["external_observation_fetched_at"] = fetch_timestamp

    marks = [
        fetch_yahoo_mark_row(
            ticker=ticker,
            runtime_state=provisional_state,
            fetched_at=fetch_timestamp,
            fetcher=fetcher,
        )
        for ticker in normalized_tickers
    ]
    success_count = sum(1 for row in marks if row["ok"])
    failure_count = len(marks) - success_count

    effective_state = dict(base_state)
    effective_state["external_observation_active"] = success_count > 0
    effective_state["external_observation_source"] = "yahoo_finance"
    effective_state["external_observation_fetched_at"] = fetch_timestamp

    stamped_marks = []
    for row in marks:
        stamped_row = stamp_payload(row, runtime_state=effective_state)
        row_tags = [
            tag
            for tag in stamped_row.get("truth_origin_tags", [])
            if str(tag) == "placeholder"
        ]
        stamped_row["truth_origin"] = "external"
        stamped_row["truth_origin_tags"] = ["external", *row_tags]
        stamped_marks.append(stamped_row)

    payload = stamp_payload(
        {
            "artifact_kind": "external_market_marks",
            "fetched_at": fetch_timestamp,
            "source_name": "yahoo_finance",
            "source_type": "external_market_data",
            "external_observation_active": success_count > 0,
            "tracked_tickers": normalized_tickers,
            "success_count": success_count,
            "failure_count": failure_count,
            "marks": stamped_marks,
            "note": (
                "Yahoo Finance marks provide external observation for paper workflows only. "
                "They do not imply broker connectivity, live execution, or economic proof."
            ),
        },
        runtime_state=effective_state,
    )
    return payload


def write_external_market_marks_report(
    tickers: list[str],
    runtime_state: dict[str, Any] | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    output_path: Path | None = None,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    payload = build_external_market_marks_report(
        tickers=tickers,
        runtime_state=runtime_state,
        fetcher=fetcher,
        fetched_at=fetched_at,
    )
    write_json_atomic(output_path or EXTERNAL_MARKS_PATH, payload, stamp=False)
    return payload


def format_marks_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Yahoo Market Marks",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"tracked_ticker_count={len(report['tracked_tickers'])}",
            f"success_count={report['success_count']}",
            f"failure_count={report['failure_count']}",
            f"output_path={repo_relative(EXTERNAL_MARKS_PATH)}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch Yahoo Finance market marks for local paper workflows."
    )
    parser.add_argument(
        "--tickers",
        required=True,
        help="Comma-separated ticker list, e.g. RTX,ZIM,TLT",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    tickers = [item.strip().upper() for item in args.tickers.split(",") if item.strip()]
    report = write_external_market_marks_report(tickers=tickers)
    if args.summary:
        print(format_marks_summary(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
