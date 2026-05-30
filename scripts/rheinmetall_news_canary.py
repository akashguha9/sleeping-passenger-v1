"""Rheinmetall news canary (Kanté P2) — safe operator read-only provider probe.

A tightly-scoped operator canary that presses the read-only news fallback chain
(``GDELT_PUBLIC -> NEWSAPI -> EVENT_REGISTRY``) for ONE entity (Rheinmetall ->
RHM.DE, Germany), records every provider attempt honestly, and classifies the
overall outcome. It is the news analogue of the price canary in
:mod:`scripts.kante_real_provider_canary`.

Operator CLI (Section 2 of the sprint)::

    python -m scripts.rheinmetall_news_canary \
        --country-focus Germany --target-ticker RHM.DE \
        --news-query Rheinmetall --allow-network --max-rows 10 --skip-synthesis

Status rules (verbatim from the spec):
    * timeout / host-unreachable -> PROVIDER_TIMEOUT or NETWORK_UNREACHABLE
    * auth failure               -> PROVIDER_AUTH_FAILED
    * empty response             -> OK_EMPTY
    * fresh rows                 -> LIVE_VERIFIED only when count(fresh_rows) > 0
                                    AND max freshness_score > 0

Hard safety contract (mirrors the rest of the MVP):
    * Read-of-news only. NEVER trades, NEVER places an order, NEVER reaches a
      broker / execution endpoint. ``--skip-synthesis`` is the default and the
      only supported mode — this canary never hands off to synthesis or sizing.
    * Network is OFF unless ``--allow-network`` is passed. Without it (and with
      no injected transport) every keyed provider degrades honestly and no row
      is fabricated.
    * Secrets are never logged. Only ``api_key_present`` booleans appear; a
      final :func:`provider_secret_redaction.assert_no_secret` guard proves no
      configured key value leaked into the rendered report.
    * A misbehaving / empty / timed-out / unauthorized provider degrades to an
      honest status. ``LIVE_VERIFIED`` is never claimed without a fresh row.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.news_provider_fallback_chain import (
        LIVE_VERIFIED,
        NEWS_PROVIDER_ENV,
        NEWS_PROVIDER_PRIORITY,
        OK_EMPTY,
        fetch_news_chain,
    )
    from scripts.provider_secret_redaction import (
        assert_no_secret,
        collect_secret_values,
    )
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from news_provider_fallback_chain import (
        LIVE_VERIFIED,
        NEWS_PROVIDER_ENV,
        NEWS_PROVIDER_PRIORITY,
        OK_EMPTY,
        fetch_news_chain,
    )
    from provider_secret_redaction import assert_no_secret, collect_secret_values
    from runtime_common import REPO_ROOT

RELEASE_DIR = REPO_ROOT / "runtime" / "release"
CANARY_REPORT_PATH = RELEASE_DIR / "rheinmetall_news_canary.json"

DEFAULT_TARGET_TICKER = "RHM.DE"
DEFAULT_COUNTRY_FOCUS = "Germany"
DEFAULT_NEWS_QUERIES: tuple[str, ...] = ("Rheinmetall",)
DEFAULT_MAX_ROWS = 10

# Overall-canary outcome vocabulary.
CANARY_LIVE_VERIFIED = "LIVE_VERIFIED"
CANARY_TARGET_NOT_FOUND = "TARGET_NOT_FOUND"      # providers OK but no fresh RHM.DE
CANARY_ALL_PROVIDERS_FAILED = "ALL_PROVIDERS_FAILED"
CANARY_NETWORK_DISABLED = "NETWORK_DISABLED"
CANARY_NO_PROVIDER_CONFIGURED = "NO_PROVIDER_CONFIGURED"

NewsTransport = Callable[[str], "list[dict[str, Any]]"]


def _target_evidence(
    rows: list[dict[str, Any]], target_ticker: str
) -> dict[str, Any]:
    """Fresh, mapped, positive-freshness rows for the target ticker (deduped)."""
    target = str(target_ticker).strip().upper()
    fresh_target: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        if str(r.get("ticker") or "").strip().upper() != target:
            continue
        if not r.get("is_live"):
            continue
        if float(r.get("freshness_score") or 0.0) <= 0:
            continue
        key = str(r.get("url") or r.get("headline") or r.get("published_at_utc") or "")
        if key in seen:
            continue
        seen.add(key)
        fresh_target.append(r)
    max_fresh = max((float(r.get("freshness_score") or 0.0) for r in fresh_target), default=0.0)
    max_conf = max((float(r.get("mapping_confidence") or 0.0) for r in fresh_target), default=0.0)
    countries = sorted({str(r.get("country") or "") for r in fresh_target if r.get("country")})
    return {
        "target_ticker": target,
        "fresh_target_rows": len(fresh_target),
        "max_freshness_score": round(max_fresh, 4),
        "max_mapping_confidence": round(max_conf, 4),
        "countries": countries,
        "live_verified": bool(fresh_target) and max_fresh > 0,
        # Compact, secret-free per-row evidence (headline + provenance only).
        "evidence_rows": [
            {
                "provider": r.get("provider"),
                "headline": r.get("headline"),
                "ticker": r.get("ticker"),
                "country": r.get("country"),
                "mapping_confidence": r.get("mapping_confidence"),
                "freshness_score": r.get("freshness_score"),
                "published_at_utc": r.get("published_at_utc"),
                "url": r.get("url"),
            }
            for r in fresh_target
        ],
    }


def _overall_status(
    *,
    allow_network: bool,
    have_transport: bool,
    provider_reports: list[dict[str, Any]],
    target_live: bool,
) -> str:
    """Reduce per-provider attempts + target evidence to one honest status."""
    if target_live:
        return CANARY_LIVE_VERIFIED
    attempted = [r for r in provider_reports if r.get("attempted")]
    configured = [r for r in provider_reports if r.get("configured")]
    if not attempted:
        if not have_transport and not allow_network:
            return CANARY_NETWORK_DISABLED
        if not configured:
            return CANARY_NO_PROVIDER_CONFIGURED
        return CANARY_NO_PROVIDER_CONFIGURED
    # Some provider was attempted. If every attempt errored (no OK response),
    # it is an all-providers-failed outcome; otherwise providers were reachable
    # but no fresh Rheinmetall->RHM.DE row was found.
    any_ok = any(r.get("response_ok") for r in attempted)
    return CANARY_TARGET_NOT_FOUND if any_ok else CANARY_ALL_PROVIDERS_FAILED


def run_canary(
    *,
    allow_network: bool = False,
    transports: Mapping[str, NewsTransport] | None = None,
    env: Mapping[str, str] | None = None,
    now_utc: datetime | None = None,
    target_ticker: str = DEFAULT_TARGET_TICKER,
    country_focus: str = DEFAULT_COUNTRY_FOCUS,
    news_queries: tuple[str, ...] = DEFAULT_NEWS_QUERIES,
    max_rows: int = DEFAULT_MAX_ROWS,
    db_path: Path | None = None,
    securities_master_path: Path | None = None,
) -> dict[str, Any]:
    """Run the Rheinmetall news canary and return an honest, secret-safe report.

    Never persists, never trades, never hands off to synthesis. With neither
    network nor an injected transport, the result is honestly NETWORK_DISABLED /
    NO_PROVIDER_CONFIGURED and no row is fabricated.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    max_rows = max(1, min(int(max_rows), 100))

    chain = fetch_news_chain(
        allow_network=allow_network,
        transports=transports,
        env=env,
        queries=tuple(news_queries),
        now_utc=now_utc,
        db_path=db_path,
        securities_master_path=securities_master_path,
        max_rows_per_provider=max_rows,
    )

    provider_reports = chain.get("provider_reports", [])
    target = _target_evidence(chain.get("rows", []), target_ticker)
    overall = _overall_status(
        allow_network=allow_network,
        have_transport=transports is not None,
        provider_reports=provider_reports,
        target_live=target["live_verified"],
    )

    # Honest "why" when the canary did not go live.
    missing_reason: str | None = None
    if overall != CANARY_LIVE_VERIFIED:
        missing_reason = "; ".join(
            f"{r.get('provider')}={r.get('status')}"
            + (f"({r.get('failure_reason')})" if r.get("failure_reason") else "")
            for r in provider_reports
        ) or "no provider attempted"

    report: dict[str, Any] = {
        "report": "rheinmetall_news_canary",
        "generated_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": chain.get("mode"),
        "allow_network": bool(allow_network),
        "target_ticker": str(target_ticker).strip().upper(),
        "country_focus": country_focus,
        "news_queries": list(news_queries),
        "max_rows": max_rows,
        "provider_priority": list(NEWS_PROVIDER_PRIORITY),
        "configured_providers": chain.get("configured_providers"),
        "provider_reports": provider_reports,
        "first_live_provider": chain.get("first_live_provider"),
        "canary_status": overall,
        "live_verified": overall == CANARY_LIVE_VERIFIED,
        "target_evidence": target,
        "missing_layer_reason": missing_reason,
        "missing_layers": chain.get("missing_layers"),
        "fresh_row_count": chain.get("fresh_row_count"),
        "mapped_row_count": chain.get("mapped_row_count"),
        # Hard advisory / no-execution posture. This canary never trades, never
        # persists, never hands off to synthesis or sizing.
        "skip_synthesis": True,
        "persisted_rows": 0,
        "advisory_only": True,
        "human_review_required": True,
        "human_execution_required": True,
        "executable_allowed": False,
        "real_money_sizing_impact": "PROHIBITED",
        "operator_execution_required": True,
        "external_adapter_execution_permission": "WATCH_ONLY",
        "external_adapter_decision_power": "EVIDENCE_ONLY",
        "proof_status": "ADVISORY_ONLY_CANARY_ARTIFACT",
        **advisory_safety_stamps(),
        "safety": advisory_safety_stamps(),
    }
    secret_values = collect_secret_values(
        [n for names in NEWS_PROVIDER_ENV.values() if names for n in names], env=env
    )
    report["secret_leak_check_passed"] = assert_no_secret(report, secret_values)
    return report


def write_report(report: dict[str, Any], path: Path | None = None) -> Path:
    target = path or CANARY_REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    tmp.replace(target)
    return target


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rheinmetall_news_canary.py",
        description=(
            "Read-only Rheinmetall news canary over GDELT -> NewsAPI -> Event "
            "Registry. Network OFF by default; advisory-only; never trades, "
            "never persists, never runs synthesis."
        ),
    )
    p.add_argument("--country-focus", type=str, default=DEFAULT_COUNTRY_FOCUS)
    p.add_argument("--target-ticker", type=str, default=DEFAULT_TARGET_TICKER)
    p.add_argument("--news-query", action="append", default=None,
                   help="News query (repeatable). Defaults to 'Rheinmetall'.")
    p.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS)
    p.add_argument("--allow-network", action="store_true",
                   help="opt in to real read-only news fetches (no key for GDELT).")
    p.add_argument("--skip-synthesis", action="store_true", default=True,
                   help="(always on) never hand off to synthesis — canary only.")
    p.add_argument("--write", action="store_true",
                   help="persist runtime/release/rheinmetall_news_canary.json")
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    queries = tuple(args.news_query) if args.news_query else DEFAULT_NEWS_QUERIES
    report = run_canary(
        allow_network=args.allow_network,
        target_ticker=args.target_ticker,
        country_focus=args.country_focus,
        news_queries=queries,
        max_rows=args.max_rows,
    )
    if args.write:
        write_report(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"rheinmetall_news_canary — mode={report['mode']}")
        print(f"  canary_status     : {report['canary_status']}")
        print(f"  first_live        : {report['first_live_provider']}")
        te = report["target_evidence"]
        print(f"  target {report['target_ticker']:8s} : fresh={te['fresh_target_rows']} "
              f"max_freshness={te['max_freshness_score']} conf={te['max_mapping_confidence']}")
        for r in report["provider_reports"]:
            print(f"    {str(r.get('provider')):16s} {str(r.get('status')):22s} "
                  f"fresh={r.get('fresh_rows')} mapped={r.get('mapped_rows')}")
        if report["missing_layer_reason"]:
            print(f"  why_not_live      : {report['missing_layer_reason']}")
        print(f"  secret_leak_check : {'PASS' if report['secret_leak_check_passed'] else 'FAIL'}")
    return 0 if report["secret_leak_check_passed"] else 2


__all__ = [
    "CANARY_REPORT_PATH",
    "DEFAULT_TARGET_TICKER",
    "DEFAULT_COUNTRY_FOCUS",
    "DEFAULT_NEWS_QUERIES",
    "CANARY_LIVE_VERIFIED",
    "CANARY_TARGET_NOT_FOUND",
    "CANARY_ALL_PROVIDERS_FAILED",
    "CANARY_NETWORK_DISABLED",
    "CANARY_NO_PROVIDER_CONFIGURED",
    "run_canary",
    "write_report",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
