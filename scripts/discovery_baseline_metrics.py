"""Single-call discovery metrics aggregator (coverage + bias + mapping).

Composes the three existing advisory engines into ONE report so the sprint's
"before/after" table can be produced from real repo state:

    * top-30 country coverage  -> C_global / C_universe / C_price / C_news /
                                  C_filings / C_mapping / C_synthesis
    * USA-bias                 -> B_US / B_US_venue / USA_bias_violation
    * fallback contamination   -> R_live / R_static / R_memory / R_phantom
    * entity->ticker mapping   -> mapped_events_count / unmapped_events_count

It is pure/advisory: no broker, no execution, no network. It reads the already
built daily payload and runs the (read-only) mapper over its news+filings rows.

Baseline honesty: there is no persisted pre-sprint snapshot in the repo, so a
true before/after cannot be reconstructed. When no ``baseline`` is supplied the
report sets ``baseline_available=False`` and reports current metrics only.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.discovery_bias_metrics import (
        compute_contamination_ratios,
        compute_usa_bias,
        global_breadth_claim_allowed,
    )
    from scripts.entity_ticker_mapper import map_event_to_tickers
    from scripts.runtime_common import utc_timestamp
    from scripts.top30_country_coverage import build_country_coverage_from_payload
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from advisory_contract import advisory_safety_stamps
    from discovery_bias_metrics import (
        compute_contamination_ratios,
        compute_usa_bias,
        global_breadth_claim_allowed,
    )
    from entity_ticker_mapper import map_event_to_tickers
    from runtime_common import utc_timestamp
    from top30_country_coverage import build_country_coverage_from_payload


REQUIRED_METRIC_KEYS: tuple[str, ...] = (
    "C_global", "C_universe", "C_price", "C_news", "C_filings",
    "C_mapping", "C_synthesis",
    "B_US", "B_US_venue", "USA_bias_violation",
    "R_live", "R_static", "R_memory", "R_phantom",
    "mapped_events_count", "unmapped_events_count",
    "H_price_coverage",
)


def _event_candidate(event: dict[str, Any], best: dict[str, Any]) -> dict[str, Any]:
    """Build a contamination/bias candidate row from an event + its mapping."""
    is_live = bool(event.get("is_live"))
    return {
        "country": best.get("country") or event.get("country"),
        "ticker": best.get("ticker") or event.get("ticker"),
        "exchange": best.get("exchange") or event.get("exchange"),
        "source_class": "LIVE" if is_live else "MEMORY_OR_STALE",
        "in_l_today": is_live,
        "phantom": bool(best.get("phantom")),
    }


def discovery_guard_status() -> dict[str, Any]:
    """Lightweight, read-only guard/release status for the metrics report.

    Reports whether the external-evidence backfill is guarded and the derived
    mutation-guard release impact, without running the full (artifact-heavy)
    release gate. Degrades to UNKNOWN rather than raising.
    """
    try:
        from scripts.local_deploy_preflight import (
            classify_mutation_script_severity,
            evaluate_mutation_guard_impact,
            scan_mutation_script_guarding,
        )
    except Exception:  # pragma: no cover - defensive
        return {
            "external_evidence_guard_status": "UNKNOWN",
            "mutation_guard_unguarded": [],
            "release_gate_status": "UNKNOWN",
        }
    cov = scan_mutation_script_guarding()
    backfill = "external_evidence_calibration_backfill.py"
    ee_status = "GUARDED" if backfill in cov["guarded"] else (
        "UNGUARDED" if backfill in cov["unguarded"] else "ABSENT"
    )
    high = sum(
        1 for n in cov["unguarded"]
        if classify_mutation_script_severity(n) == "HIGH"
    )
    impact = evaluate_mutation_guard_impact(
        len(cov["guarded"]), cov["unguarded"], high_severity_count=high
    )
    return {
        "external_evidence_guard_status": ee_status,
        "mutation_guard_unguarded": cov["unguarded"],
        "release_gate_status": impact["mutation_guard_release_impact"],
    }


def compute_discovery_metrics(
    payload: dict[str, Any] | None = None,
    *,
    db_path: Any = None,
    price_rows: list[dict[str, Any]] | None = None,
    baseline: dict[str, Any] | None = None,
    include_guards: bool = False,
) -> dict[str, Any]:
    """Compute the full discovery metric set from a daily payload.

    Runs the read-only entity->ticker mapper over the payload's news + filings
    rows to obtain mapping rows and mapped/unmapped counts, then derives country
    coverage, USA-bias, and contamination ratios. When ``baseline`` (a prior
    metrics dict) is supplied, per-metric deltas are included.
    """
    if payload is None:
        try:
            from scripts.daily_payload import load_daily_payload
        except ModuleNotFoundError:  # pragma: no cover
            from daily_payload import load_daily_payload
        payload = load_daily_payload()

    news = payload.get("news_events", {}).get("events", []) or []
    filings = payload.get("filings_events", {}).get("events", []) or []
    events = list(news) + list(filings)

    mapping_rows: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    mapped_n = unmapped_n = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        rows = map_event_to_tickers(event, db_path=db_path)
        best = max(rows, key=lambda m: float(m.get("mapping_confidence") or 0.0))
        mapping_rows.append(best)
        if best.get("mapping_status") == "MAPPED":
            mapped_n += 1
        else:
            unmapped_n += 1
        candidates.append(_event_candidate(event, best))

    if price_rows is None:
        price_rows = payload.get("price_movers", {}).get("movers", []) or []
    coverage = build_country_coverage_from_payload(
        payload, mapping_rows=mapping_rows, price_rows=price_rows
    )
    bias = compute_usa_bias(candidates)
    contamination = compute_contamination_ratios(candidates)

    holding_rows = [
        r for r in price_rows
        if str(r.get("row_class") or "").upper() == "EXISTING_POSITION_REVIEW"
    ]
    if holding_rows:
        h_valid = sum(1 for r in holding_rows if r.get("valid_price"))
        h_price_coverage = round(h_valid / max(1, len(holding_rows)), 4)
    else:
        h_price_coverage = 0.0

    covered_country_count = sum(
        1 for row in coverage.get("countries", []) if isinstance(row, dict) and row.get("coverage") == 1
    )
    breadth = global_breadth_claim_allowed(
        bias,
        c_global=coverage["ratios"].get("C_global", 0.0),
        covered_country_count=covered_country_count,
    )

    metrics: dict[str, Any] = {}
    metrics.update(coverage["ratios"])  # C_*
    metrics["B_US"] = bias["B_US"]
    metrics["B_US_venue"] = bias["B_US_venue"]
    metrics["B_non_US"] = bias["B_non_US"]
    metrics["USA_bias_violation"] = bias["USA_bias_violation"]
    metrics["country_concentration_hhi"] = bias["country_concentration_hhi"]
    metrics["effective_country_count"] = bias["effective_country_count"]
    metrics["global_breadth_claim_allowed"] = breadth["global_breadth_claim_allowed"]
    metrics["R_live"] = contamination["R_live"]
    metrics["R_static"] = contamination["R_static"]
    metrics["R_memory"] = contamination["R_memory"]
    metrics["R_phantom"] = contamination["R_phantom"]
    metrics["mapped_events_count"] = mapped_n
    metrics["unmapped_events_count"] = unmapped_n
    metrics["H_price_coverage"] = h_price_coverage

    report: dict[str, Any] = {
        "generated_at_utc": utc_timestamp(),
        "baseline_available": baseline is not None,
        "event_count": len(events),
        "news_event_count": len(news),
        "filings_event_count": len(filings),
        "metrics": metrics,
        "global_discovery_status": coverage["global_discovery_status"],
        "global_breadth_claim_allowed": breadth["global_breadth_claim_allowed"],
        "global_breadth_claim_statement": breadth["claim_statement"],
        "usa_bias_status": bias["status"],
        "contamination_warnings": contamination["warnings"],
        "safety": advisory_safety_stamps(),
    }
    if include_guards:
        report["guards"] = discovery_guard_status()
    if baseline is not None:
        base_metrics = baseline.get("metrics", baseline)
        deltas: dict[str, Any] = {}
        for key in REQUIRED_METRIC_KEYS:
            if key in base_metrics and key in metrics:
                try:
                    deltas[key] = round(metrics[key] - base_metrics[key], 4)
                except TypeError:
                    deltas[key] = None
        report["deltas"] = deltas
    return report


def render_metrics_markdown(report: dict[str, Any]) -> str:
    m = report["metrics"]
    lines = [
        "DISCOVERY METRICS (advisory-only)",
        f"baseline_available: {report['baseline_available']} | events: {report['event_count']}",
        f"global_discovery_status: {report['global_discovery_status']}",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]
    for key in REQUIRED_METRIC_KEYS:
        lines.append(f"| {key} | {m.get(key)} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description="Compute discovery coverage/bias/mapping metrics.")
    parser.add_argument("--markdown", action="store_true", help="print the markdown table")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    report = compute_discovery_metrics()
    if args.markdown:
        sys.stdout.write(render_metrics_markdown(report) + "\n")
    else:
        sys.stdout.write(json.dumps(report["metrics"], indent=2) + "\n")
    return 0


__all__ = [
    "REQUIRED_METRIC_KEYS",
    "compute_discovery_metrics",
    "discovery_guard_status",
    "render_metrics_markdown",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
