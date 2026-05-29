"""Operator-run daily discovery refresh — populate market_data before synthesis.

Safe orchestration flow (advisory-only, no broker, no execution):

    1. Load the advisory / no-execution safety stamps.
    2. (optional) refresh live price marks via an injected provider.
    3. Build the price-coverage view from persisted market_data marks.
    4. Compute C_price + H_price_coverage + the advisory new-risk gate.
    5. Optionally hand off to the five-model synthesis (default OFF).
    6. Return / write an honest report.

It NEVER calls a broker, NEVER places or modifies an order, NEVER runs
autonomous execution. Tests drive it with a mock provider (``--use-mock-
providers`` / the ``price_provider`` arg); no network and no API key required.
Without a provider it degrades honestly (C_price stays 0).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.refresh_live_price_marks import (
        PRICE_PROVIDER_NOT_CONFIGURED,
        build_price_coverage,
        evaluate_new_risk_gate,
        refresh_price_marks,
    )
    from scripts.runtime_common import utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from refresh_live_price_marks import (
        PRICE_PROVIDER_NOT_CONFIGURED,
        build_price_coverage,
        evaluate_new_risk_gate,
        refresh_price_marks,
    )
    from runtime_common import utc_timestamp


def _mock_price_provider(now_utc: datetime) -> Callable[[str], "dict[str, Any] | None"]:
    """Deterministic offline provider for tests / --use-mock-providers.

    Returns a fresh quote for a fixed multi-country fixture universe and None
    for anything else (honest 'symbol unsupported'). No network, no key.
    """
    iso = now_utc.replace(microsecond=0).isoformat()
    fixture = {
        "AAPL": ("USD", 190.0),
        "RELIANCE.NS": ("INR", 2900.0),
        "SAP.DE": ("EUR", 175.0),
        "SHEL.L": ("GBP", 28.0),
        "7203.T": ("JPY", 3100.0),
    }

    def _provider(ticker: str) -> "dict[str, Any] | None":
        key = str(ticker).strip().upper()
        if key not in fixture:
            return None
        currency, price = fixture[key]
        return {"price": price, "timestamp_utc": iso, "currency": currency, "volume": 1_000_000.0}

    return _provider


def run_refresh(
    *,
    db_path: Path | None = None,
    price_provider: Callable[[str], "dict[str, Any] | None"] | None = None,
    holdings: list[str] | None = None,
    candidate_tickers: list[str] | None = None,
    holding_countries: dict[str, str] | None = None,
    now_utc: datetime | None = None,
    market_state: str = "unknown",
    run_synthesis: bool = False,
) -> dict[str, Any]:
    """Run the safe refresh flow and return an honest report dict.

    ``price_provider`` is an injected read-only quote callable. With it None,
    no marks are written and the report honestly shows the not-configured
    status and C_price=0.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    holdings = holdings or []
    candidate_tickers = candidate_tickers or []
    all_tickers = list(dict.fromkeys([*holdings, *candidate_tickers]))

    refresh = refresh_price_marks(
        all_tickers, provider=price_provider, db_path=db_path, now_utc=now_utc
    )
    coverage = build_price_coverage(
        db_path,
        holdings=holdings,
        candidate_tickers=candidate_tickers,
        holding_countries=holding_countries,
        now_utc=now_utc,
        market_state=market_state,
    )
    gate = evaluate_new_risk_gate(coverage["H_price_coverage"], coverage["C_price"])

    report = {
        "operation": "run_daily_discovery_refresh",
        "generated_at_utc": utc_timestamp(),
        "price_refresh": refresh,
        "price_provider_configured": price_provider is not None,
        "C_price": coverage["C_price"],
        "H_price_coverage": coverage["H_price_coverage"],
        "valid_price_count": coverage["price_meta"].get("valid_price_count", 0),
        "new_risk_gate": gate,
        "synthesis_ran": False,
        "synthesis_skipped_reason": None if run_synthesis else "run_synthesis flag is off",
        # Hard advisory safety stamps — refresh is never an execution path.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "execution_mode": "HUMAN_ONLY",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "safety": advisory_safety_stamps(),
    }
    if not refresh.get("attempted"):
        report["price_status"] = PRICE_PROVIDER_NOT_CONFIGURED
    else:
        report["price_status"] = refresh.get("status")

    if run_synthesis:
        # Synthesis hand-off is intentionally explicit and advisory; it is left
        # to the operator's existing pipeline and never executes a trade.
        report["synthesis_skipped_reason"] = (
            "synthesis hand-off requested; run scripts/daily_synthesis_pipeline.py "
            "separately (advisory-only, human-execution-required)."
        )
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        prog="run_daily_discovery_refresh.py",
        description=(
            "Refresh advisory market_data price marks before discovery/synthesis. "
            "Never calls a broker, never places an order, never executes."
        ),
    )
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument("--use-mock-providers", action="store_true",
                        help="Use the deterministic offline fixture provider.")
    parser.add_argument("--skip-network", action="store_true",
                        help="Never attempt a network provider (forces no-provider).")
    parser.add_argument("--skip-synthesis", action="store_true", default=True)
    parser.add_argument("--run-synthesis", action="store_true",
                        help="Request the (separate) synthesis hand-off; advisory only.")
    parser.add_argument("--holdings", default="", help="Comma-separated holding tickers.")
    parser.add_argument("--candidates", default="", help="Comma-separated candidate tickers.")
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    now_utc = datetime.now(timezone.utc)
    provider = None
    if args.use_mock_providers and not args.skip_network:
        provider = _mock_price_provider(now_utc)

    db_path = Path(args.db_path) if args.db_path else None
    holdings = [t for t in args.holdings.split(",") if t.strip()]
    candidates = [t for t in args.candidates.split(",") if t.strip()]

    report = run_refresh(
        db_path=db_path,
        price_provider=provider,
        holdings=holdings,
        candidate_tickers=candidates,
        now_utc=now_utc,
        run_synthesis=args.run_synthesis,
    )

    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "daily_discovery_refresh_report.json").write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"price_status      : {report['price_status']}")
        print(f"marks_written     : {report['price_refresh']['written']}")
        print(f"C_price           : {report['C_price']}")
        print(f"H_price_coverage  : {report['H_price_coverage']}")
        print(f"new_risk_allowed  : {report['new_risk_gate']['new_risk_allowed']}")
    return 0


__all__ = ["run_refresh"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
