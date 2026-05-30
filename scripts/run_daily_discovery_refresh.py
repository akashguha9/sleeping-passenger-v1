"""Operator-run daily discovery refresh — populate inputs before synthesis.

Safe orchestration flow (advisory-only, no broker, no execution):

    refresh price marks (real or mock provider, network-gated)
    -> attempt UK RNS / Companies House disclosures (network-gated)
    -> rebuild the five regenerable daily payloads from persisted rows
    -> compute country coverage (C_global, C_price, C_news, C_filings, C_mapping)
    -> compute H_price_coverage + the advisory new-risk gate
    -> write an honest report to data/daily_payload/daily_refresh_report.json

It NEVER calls a broker, NEVER places or modifies an order, NEVER runs
autonomous execution. Network is touched ONLY when ``--allow-network`` is set;
``--use-mock-providers`` runs a deterministic offline fixture; the default and
``--skip-network`` modes never make an external request. Credential values are
never logged — only ``*_present`` booleans and provider status strings.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.country_coverage_proof import (
        build_proof_from_payload,
        write_country_coverage_proof,
    )
    from scripts.global_filings_loader import (
        fetch_companies_house_filings,
        fetch_uk_rns_filings,
    )
    from scripts.provider_secret_redaction import assert_no_secret, collect_secret_values
    from scripts.real_price_provider import (
        build_mock_price_transport,
        resolve_price_provider,
    )
    from scripts.refresh_live_price_marks import (
        PRICE_PROVIDER_NOT_CONFIGURED,
        build_price_coverage,
        evaluate_new_risk_gate,
        refresh_price_marks,
    )
    from scripts.runtime_common import REPO_ROOT, ensure_directory, utc_timestamp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from country_coverage_proof import (
        build_proof_from_payload,
        write_country_coverage_proof,
    )
    from global_filings_loader import (
        fetch_companies_house_filings,
        fetch_uk_rns_filings,
    )
    from provider_secret_redaction import assert_no_secret, collect_secret_values
    from real_price_provider import build_mock_price_transport, resolve_price_provider
    from refresh_live_price_marks import (
        PRICE_PROVIDER_NOT_CONFIGURED,
        build_price_coverage,
        evaluate_new_risk_gate,
        refresh_price_marks,
    )
    from runtime_common import REPO_ROOT, ensure_directory, utc_timestamp


DAILY_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"
DAILY_REFRESH_REPORT_PATH = DAILY_PAYLOAD_DIR / "daily_refresh_report.json"

# Canonical existing holdings (portfolio truth) used for H_price_coverage.
DEFAULT_HOLDINGS: tuple[str, ...] = (
    "ANET", "ASML", "CVX", "HDFCBANK.NS", "LMT",
    "MSFT", "RELIANCE.NS", "RTX", "TSM", "XOM",
)

# Country-focus seed tickers — included in T_refresh when a country is focused.
COUNTRY_FOCUS_SEEDS: dict[str, tuple[str, ...]] = {
    "Germany": ("RHM.DE", "SAP.DE"),
    "United Kingdom": ("SHEL.L", "BP.L"),
    "India": ("RELIANCE.NS", "HDFCBANK.NS"),
    "Japan": ("7203.T",),
    "United States": ("MSFT", "AAPL"),
}

# Env names whose values must never leak into the report / logs.
_SECRET_ENVS: tuple[str, ...] = (
    "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "POLYGON_API_KEY",
    "COMPANIES_HOUSE_API_KEY", "LSE_RNS_API_KEY", "LSE_RNS_SOURCE_URL",
    "RNS_SOURCE_URL",
)


def _mock_price_provider(now_utc: datetime) -> Callable[[str], "dict[str, Any] | None"]:
    """Deterministic offline provider for tests / --use-mock-providers (legacy).

    Preserved for backward compatibility with the original price-only flow.
    Delegates to the shared mock transport used by the real-provider resolver.
    """
    return build_mock_price_transport(now_utc)


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
    """Run the safe price-refresh flow and return an honest report dict.

    Backward-compatible entry point (price marks + C_price + H_price_coverage +
    advisory new-risk gate). For the full discovery flow (payload rebuild +
    country coverage + provider statuses), use :func:`run_daily_refresh`.
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
        report["synthesis_skipped_reason"] = (
            "synthesis hand-off requested; run scripts/daily_synthesis_pipeline.py "
            "separately (advisory-only, human-execution-required)."
        )
    return report


def _persist_raw_rows(
    source_name: str,
    raw_rows: list[dict[str, Any]] | None,
    db_path: Path | None,
    now_utc: datetime,
    event_type: str = "filing",
) -> int:
    """Persist genuinely-fetched disclosure/news raw rows as signal_events.

    Idempotent on a deterministic event_id. Never fabricates rows (a None /
    empty input writes nothing). The canonical news/filings bridge re-normalizes
    and country-enriches these on payload rebuild. Read-only / advisory; no
    broker.
    """
    if not raw_rows:
        return 0
    try:
        import scripts.persistence as _persistence
    except ModuleNotFoundError:  # pragma: no cover
        import persistence as _persistence  # type: ignore
    fetched_at = now_utc.replace(microsecond=0).isoformat()
    written = 0
    for idx, raw in enumerate(raw_rows):
        if not isinstance(raw, dict):
            continue
        published = str(raw.get("published_at_utc") or raw.get("published_at") or fetched_at)
        ident = str(raw.get("ticker") or raw.get("company_number") or raw.get("entity_name") or idx)
        event_id = f"{source_name}_{ident}_{published}"
        payload = dict(raw)
        payload.setdefault("source_name", source_name)
        payload.setdefault("event_type", event_type)
        try:
            if _persistence.insert_signal_event(
                event_id, source_name, payload, fetched_at, db_path=db_path
            ):
                written += 1
        except Exception:  # noqa: BLE001 - persistence failure is non-fatal
            continue
    return written


def _build_refresh_universe(
    *,
    holdings: list[str],
    candidate_tickers: list[str],
    country_focus: str | None,
    target_ticker: str | None,
    max_rows: int,
) -> list[str]:
    """Assemble T_refresh = H union candidates union universe union focus seeds."""
    try:
        from scripts.minimum_daily_universe import minimum_universe_tickers
    except ModuleNotFoundError:  # pragma: no cover
        from minimum_daily_universe import minimum_universe_tickers
    seeds: list[str] = [*holdings, *candidate_tickers]
    if target_ticker:
        seeds.append(target_ticker)
    if country_focus:
        seeds.extend(COUNTRY_FOCUS_SEEDS.get(country_focus, ()))
    seeds.extend(minimum_universe_tickers())
    out: list[str] = []
    for t in seeds:
        key = str(t).strip().upper()
        if key and key not in out:
            out.append(key)
        if len(out) >= max_rows:
            break
    return out


def run_daily_refresh(
    *,
    db_path: Path | None = None,
    payload_dir: Path | None = None,
    allow_network: bool = False,
    use_mock_providers: bool = False,
    dry_run: bool = False,
    provider: str | None = None,
    max_rows: int = 100,
    country_focus: str | None = None,
    target_ticker: str | None = None,
    holdings: list[str] | None = None,
    candidate_tickers: list[str] | None = None,
    holding_countries: dict[str, str] | None = None,
    now_utc: datetime | None = None,
    market_state: str = "unknown",
    no_secrets_in_logs: bool = True,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Full operator daily-refresh flow. Returns the honest report dict.

    Network is touched only when ``allow_network`` is True. ``use_mock_providers``
    runs a deterministic offline fixture (no network). ``dry_run`` computes the
    plan/coverage but persists no marks and rebuilds no payloads.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    payload_dir = payload_dir or DAILY_PAYLOAD_DIR
    holdings = list(holdings) if holdings is not None else list(DEFAULT_HOLDINGS)
    candidate_tickers = list(candidate_tickers or [])
    warnings: list[str] = []

    # --- Resolve the read-only price provider (priority Yahoo->keyed). ---
    transports = None
    if use_mock_providers:
        transports = {"yahoo": build_mock_price_transport(now_utc)}
    price_res = resolve_price_provider(
        allow_network=allow_network,
        prefer=provider,
        env=env,
        transports=transports,
        now_utc=now_utc,
    )
    price_provider = price_res["callable"]

    universe = _build_refresh_universe(
        holdings=holdings,
        candidate_tickers=candidate_tickers,
        country_focus=country_focus,
        target_ticker=target_ticker,
        max_rows=max_rows,
    )

    # --- Persist price marks (skipped on dry_run / no provider). ---
    if dry_run or price_provider is None:
        price_refresh = {
            "attempted": False,
            "written": 0,
            "symbols_requested": len(universe),
            "status": price_res["status"],
            "results": [],
        }
    else:
        price_refresh = refresh_price_marks(
            universe, provider=price_provider, db_path=db_path, now_utc=now_utc
        )

    # --- Attempt UK RNS / Companies House disclosures (network-gated). ---
    uk_rns_rows = None
    uk_ch_rows = None
    mock_news_rows = None
    if use_mock_providers:
        iso = now_utc.replace(microsecond=0).isoformat()
        uk_rns_rows = [
            {"entity_name": "Shell", "ticker": "SHEL.L",
             "headline": "Shell plc trading update", "published_at_utc": iso,
             "freshness_score": 1.0},
        ]
        uk_ch_rows = [
            {"entity_name": "Acme Private Holdings Ltd", "company_number": "00000001",
             "headline": "Annual accounts", "published_at_utc": iso,
             "freshness_score": 1.0},
        ]
        # Deterministic Germany news (offline fixture) so the FULL flow can prove
        # coverage(Germany)=1 end-to-end under --use-mock-providers. This is a
        # labelled offline fixture, NEVER a real-network claim.
        mock_news_rows = [
            {"entity_name": "Rheinmetall", "ticker": "RHM.DE", "country": "Germany",
             "headline": "Rheinmetall confirms expanded defense order backlog",
             "published_at_utc": iso, "freshness_score": 1.0},
        ]
    rns_events, rns_meta = fetch_uk_rns_filings(
        allow_network=allow_network, env=env, fixture_rows=uk_rns_rows, now_utc=now_utc
    )
    ch_events, ch_meta = fetch_companies_house_filings(
        allow_network=allow_network, env=env, fixture_rows=uk_ch_rows, now_utc=now_utc
    )

    # --- Persist fetched UK disclosure raw rows so the canonical filings bridge
    #     (signal_events -> today_filings_events) consumes them on rebuild. Only
    #     genuinely-fetched rows are persisted; never fabricated. ---
    if not dry_run:
        _persist_raw_rows("lse_rns", uk_rns_rows, db_path, now_utc, event_type="filing")
        _persist_raw_rows("uk_companies_house", uk_ch_rows, db_path, now_utc, event_type="filing")
        _persist_raw_rows("gdelt", mock_news_rows, db_path, now_utc, event_type="news")

    # --- Rebuild the five regenerable payloads (skipped on dry_run). ---
    payloads_rebuilt = False
    payload_summary: dict[str, Any] = {}
    if not dry_run:
        try:
            from scripts.build_daily_payloads import build_all_daily_payloads
        except ModuleNotFoundError:  # pragma: no cover
            from build_daily_payloads import build_all_daily_payloads
        payload_summary = build_all_daily_payloads(
            payload_dir=payload_dir,
            db_path=db_path,
            now_utc=now_utc,
            market_state=market_state,
        )
        payloads_rebuilt = True

    # --- Coverage + price metrics from persisted marks. ---
    coverage = build_price_coverage(
        db_path,
        holdings=holdings,
        candidate_tickers=universe,
        holding_countries=holding_countries,
        now_utc=now_utc,
        market_state=market_state,
    )
    gate = evaluate_new_risk_gate(coverage["H_price_coverage"], coverage["C_price"])

    # --- Full country coverage from the rebuilt payload (or current on dry). ---
    try:
        from scripts.daily_payload import load_daily_payload
    except ModuleNotFoundError:  # pragma: no cover
        from daily_payload import load_daily_payload
    try:
        payload = load_daily_payload(payload_dir=payload_dir)
    except Exception:  # noqa: BLE001 - missing payload degrades honestly
        payload = {}
    # Mapping rows come from EVERY mapped event consumed by synthesis (news +
    # filings) in the rebuilt payload — that is what proves mapping_support(c).
    payload_news = (payload.get("news_events", {}) or {}).get("events", []) if isinstance(payload, dict) else []
    payload_filings = (payload.get("filings_events", {}) or {}).get("events", []) if isinstance(payload, dict) else []
    mapping_rows = [
        {"mapping_confidence": e.get("mapping_confidence"), "country": e.get("country"),
         "ticker": e.get("ticker")}
        for e in (list(payload_news) + list(payload_filings) + rns_events + ch_events)
        if e.get("ticker") and str(e.get("mapping_status", "")).upper() == "MAPPED"
    ]
    coverage_proof = build_proof_from_payload(
        payload if isinstance(payload, dict) else {},
        price_rows=coverage["price_rows"],
        mapping_rows=mapping_rows or None,
        proof_kind="REAL_RUN" if not dry_run else "DRY_RUN_PLAN",
    )

    # --- L_today: fresh consumed event rows in the rebuilt payload. ---
    def _fresh(rows: list[dict[str, Any]]) -> int:
        return sum(1 for r in rows if r.get("is_live"))
    l_today_count = _fresh(payload_news) + _fresh(payload_filings)

    # --- Provider status roll-up (secret-safe). ---
    provider_statuses = [
        {"provider": "price:" + (price_res["provider"] or "none"), "status": price_res["status"]},
        {"provider": rns_meta["provider"], "status": rns_meta["status"], "is_live": rns_meta["is_live"]},
        {"provider": ch_meta["provider"], "status": ch_meta["status"], "is_live": ch_meta["is_live"]},
    ]
    providers_configured = sum(
        1 for d in price_res["configured_providers"] if d["configured"]
    ) + sum(1 for m in (rns_meta, ch_meta) if m["config"]["configured"])
    providers_live_verified = (
        (1 if price_refresh.get("status") == "LIVE_PRICE_VERIFIED" else 0)
        + (1 if rns_meta["is_live"] else 0)
        + (1 if ch_meta["is_live"] else 0)
    )

    if coverage["H_price_coverage"] < 0.80:
        warnings.append("EXISTING_RISK_VISIBILITY_DEGRADED")
    if coverage["C_price"] < 0.10:
        warnings.append("GLOBAL_PRICE_COVERAGE_THIN")
    if coverage_proof["C_global"] <= 0.0:
        warnings.append("C_GLOBAL_ZERO_NO_FULL_COUNTRY")

    report: dict[str, Any] = {
        "operation": "run_daily_discovery_refresh",
        "run_timestamp_utc": utc_timestamp(),
        "dry_run": bool(dry_run),
        "network_allowed": bool(allow_network),
        "use_mock_providers": bool(use_mock_providers),
        "providers_attempted": provider_statuses,
        "providers_configured": providers_configured,
        "providers_live_verified": providers_live_verified,
        "rows_fetched": len(rns_events) + len(ch_events),
        "rows_written_signal_events": price_refresh.get("written", 0),
        "price_marks_written": price_refresh.get("written", 0),
        "price_status": price_refresh.get("status", price_res["status"]),
        "price_provider": price_res["provider"],
        "payloads_rebuilt": payloads_rebuilt,
        "L_today_count": l_today_count,
        "country_coverage_summary": {
            "C_global": coverage_proof["C_global"],
            "covered_country_count": coverage_proof["covered_country_count"],
            "first_covered_country": coverage_proof["first_covered_country"],
            "global_status": coverage_proof["global_status"],
        },
        "C_global": coverage_proof["C_global"],
        "C_price": coverage["C_price"],
        "C_news": coverage_proof["C_news"],
        "C_filings": coverage_proof["C_filings"],
        "C_mapping": coverage_proof["C_mapping"],
        "C_synthesis": coverage_proof["C_synthesis"],
        "H_price_coverage": coverage["H_price_coverage"],
        "new_risk_gate": gate,
        "uk_filings": {"rns": rns_meta, "companies_house": ch_meta},
        "price_provider_diagnostics": price_res["configured_providers"],
        "payload_summary": payload_summary,
        "warnings": warnings,
        # Hard advisory safety stamps — refresh is never an execution path.
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
        "execution_mode": "HUMAN_ONLY",
        "broker_api_called": False,
        "ai_execution_count": 0,
        "execution_permission": False,
        "can_execute": False,
        "safety_stamps": advisory_safety_stamps(),
    }

    # refresh_success contract (advisory; never an execution authorization).
    report["refresh_success"] = bool(
        (payloads_rebuilt or dry_run)
        and report["advisory_status"] == "ADVISORY_ONLY"
        and report["broker_api_called"] is False
        and report["ai_execution_count"] == 0
    )

    # Defensive secret-leak guard: the report must not contain any raw secret.
    if no_secrets_in_logs:
        secrets = collect_secret_values(_SECRET_ENVS, env)
        if not assert_no_secret(report, secrets):  # pragma: no cover - never expected
            raise RuntimeError("aborting: secret value detected in refresh report")
        report["no_secret_leak"] = True
    return report


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(
        prog="run_daily_discovery_refresh.py",
        description=(
            "Refresh advisory discovery inputs (price marks, UK disclosures, "
            "payloads, country coverage) before synthesis. Never calls a broker, "
            "never places an order, never executes."
        ),
    )
    parser.add_argument("--db-path", type=str, default=None)
    parser.add_argument("--output-dir", type=str, default=None)
    parser.add_argument("--provider", type=str, default=None,
                        help="Prefer a specific read-only price provider.")
    parser.add_argument("--max-rows", type=int, default=100)
    parser.add_argument("--country-focus", type=str, default=None)
    parser.add_argument("--target-ticker", type=str, default=None)
    parser.add_argument("--use-mock-providers", action="store_true",
                        help="Deterministic offline fixture providers (no network).")
    parser.add_argument("--skip-network", action="store_true",
                        help="Never attempt a network provider (default-safe).")
    parser.add_argument("--allow-network", action="store_true",
                        help="Allow read-only data-provider network calls (never broker).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Plan only; persist no marks and rebuild no payloads.")
    parser.add_argument("--skip-synthesis", action="store_true", default=True)
    parser.add_argument("--no-secrets-in-logs", action="store_true", default=True)
    parser.add_argument("--holdings", default="", help="Comma-separated holding tickers.")
    parser.add_argument("--candidates", default="", help="Comma-separated candidate tickers.")
    parser.add_argument("--market-state", default="unknown",
                        choices=["open", "closed", "unknown"])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--legacy-price-only", action="store_true",
                        help="Run the legacy price-only flow (run_refresh).")
    args = parser.parse_args(argv)

    now_utc = datetime.now(timezone.utc)
    db_path = Path(args.db_path) if args.db_path else None
    out_dir = Path(args.output_dir) if args.output_dir else None
    holdings = [t for t in args.holdings.split(",") if t.strip()] or None
    candidates = [t for t in args.candidates.split(",") if t.strip()] or None

    # --skip-network wins over --allow-network for safety.
    allow_network = bool(args.allow_network) and not args.skip_network

    if args.legacy_price_only:
        provider = _mock_price_provider(now_utc) if args.use_mock_providers else None
        report = run_refresh(
            db_path=db_path, price_provider=provider, holdings=holdings or [],
            candidate_tickers=candidates or [], now_utc=now_utc,
        )
    else:
        report = run_daily_refresh(
            db_path=db_path,
            payload_dir=out_dir,  # --output-dir directs payloads + report together
            allow_network=allow_network,
            use_mock_providers=args.use_mock_providers,
            dry_run=args.dry_run,
            provider=args.provider,
            max_rows=args.max_rows,
            country_focus=args.country_focus,
            target_ticker=args.target_ticker,
            holdings=holdings,
            candidate_tickers=candidates,
            now_utc=now_utc,
            market_state=args.market_state,
            no_secrets_in_logs=args.no_secrets_in_logs,
        )

    report_dir = out_dir or DAILY_PAYLOAD_DIR
    ensure_directory(report_dir)
    (report_dir / "daily_refresh_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"price_status        : {report.get('price_status')}")
        print(f"price_marks_written : {report.get('price_marks_written', report.get('price_refresh', {}).get('written'))}")
        print(f"payloads_rebuilt    : {report.get('payloads_rebuilt')}")
        print(f"C_global            : {report.get('C_global')}")
        print(f"C_price             : {report.get('C_price')}")
        print(f"H_price_coverage    : {report.get('H_price_coverage')}")
        print(f"providers_live      : {report.get('providers_live_verified')}")
    return 0


__all__ = ["run_refresh", "run_daily_refresh", "_mock_price_provider", "DEFAULT_HOLDINGS"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
