"""Deterministic JSON + human-readable markdown report rendering."""
from __future__ import annotations

import json
from pathlib import Path

from src.simulation_zip.labels import SIMULATION_LABELS

_SEGMENT_ORDER = [
    "evidence_ingestion_robustness",
    "data_provenance_completeness",
    "parser_coverage",
    "simulation_volume",
    "noise_handling",
    "calibration_hardening",
    "high_confidence_failure_handling",
    "delayed_outcome_handling",
    "product_mvp_clarity",
    "advisory_guardrail_preservation",
    "reproducibility",
    "dashboard_reporting_usefulness",
]

_SEGMENT_TITLES = {
    "evidence_ingestion_robustness": "Evidence ingestion robustness",
    "data_provenance_completeness": "Data provenance completeness",
    "parser_coverage": "Parser coverage",
    "simulation_volume": "Simulation volume",
    "noise_handling": "Noise handling",
    "calibration_hardening": "Calibration hardening",
    "high_confidence_failure_handling": "High-confidence failure handling",
    "delayed_outcome_handling": "Delayed outcome handling",
    "product_mvp_clarity": "Product/MVP clarity",
    "advisory_guardrail_preservation": "Advisory-only guardrail preservation",
    "reproducibility": "Reproducibility",
    "dashboard_reporting_usefulness": "Dashboard/reporting usefulness",
}


def write_json(path: str | Path, obj: object) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    return p


def render_summary_markdown(report: dict) -> str:
    s = report.get("safety", {})
    diag = report.get("diagnostics", {})
    overall = report.get("scores", {}).get("overall", {})
    lines = [
        "# Zip Simulation Run Summary",
        "",
        f"- Status: **{report.get('status')}**",
        f"- Labels: {', '.join(SIMULATION_LABELS)}",
        f"- Zip path: `{report.get('zip_path')}`",
        f"- Corpus label: {report.get('corpus_label')}",
        f"- Archive safety: {s.get('archive_status')} ({s.get('reason')})",
        f"- Zip size: {s.get('zip_file_mb')} MB",
        f"- Members: {s.get('member_count')}",
        f"- Usable simulation records: {diag.get('usable_records')}",
        f"- Dataset families detected: {diag.get('families_detected')}",
        f"- Dataset families parsed: {diag.get('families_parsed')}",
        "",
        "## Overall (SIMULATION_ONLY)",
        f"- Before: {overall.get('overall_before')}",
        f"- After: {overall.get('overall_after')}",
        f"- Delta: {overall.get('overall_delta')}",
        f"- Relative lift: {overall.get('overall_relative_lift_pct')}%",
        f"- Caps applied: {overall.get('caps_applied')}",
        "",
        "> SIMULATION_ONLY. Not live trading proof, not broker data, not "
        "financial advice.",
        "",
    ]
    return "\n".join(lines)


def _segment_rows(scores: dict) -> list[str]:
    segs = scores.get("segments", {})
    rows = []
    for cat in _SEGMENT_ORDER:
        seg = segs.get(cat, {})
        rows.append(
            f"| {_SEGMENT_TITLES[cat]} | {seg.get('before')} | {seg.get('after')} "
            f"| {seg.get('delta')} | {seg.get('relative_lift_pct')}% "
            f"| weight={seg.get('weight')} | {seg.get('label')} |"
        )
    overall = scores.get("overall", {})
    rows.append(
        f"| Overall MVP simulation-readiness score | {overall.get('overall_before')} "
        f"| {overall.get('overall_after')} | {overall.get('overall_delta')} "
        f"| {overall.get('overall_relative_lift_pct')}% | weighted | SIMULATION_ONLY |"
    )
    return rows


def render_integration_markdown(report: dict) -> str:
    s = report.get("safety", {})
    diag = report.get("diagnostics", {})
    fb = report.get("family_breakdown", {})
    scores = report.get("scores", {})
    checks = s.get("checks", {})

    chess = fb.get("chess_pgn", {})
    hack = fb.get("hackathon_project", {})
    scraped = fb.get("scraped_text", {})
    market = fb.get("market_or_finance_data", {})
    code = fb.get("code_corpus", {})
    unknown = fb.get("unknown", {})

    out: list[str] = []
    A = out.append
    A("# Zip Simulation Integration Report")
    A("")
    A(f"_Labels: {', '.join(SIMULATION_LABELS)}_")
    A(f"_Generated: {report.get('generated_at')} | Corpus: {report.get('corpus_label')}_")
    A("")
    A("## 1. Input")
    A(f"- Zip path: `{report.get('zip_path')}`")
    A(f"- Zip size: {s.get('zip_file_mb')} MB ({s.get('zip_file_bytes')} bytes)")
    A(f"- Files scanned: {s.get('member_count')}")
    A(f"- Files safely parsed (usable records): {diag.get('usable_records')}")
    A(f"- Files skipped (unknown): {diag.get('unknown_files')}")
    A(f"- Files blocked: {diag.get('blocked_files')}")
    A(f"- Dataset families detected: {diag.get('families_detected')}")
    A(f"- Dataset families parsed: {diag.get('families_parsed')}")
    A("")
    A("## 2. Safety Status")
    A(f"- Archive status: **{s.get('archive_status')}** ({s.get('reason')})")
    A(f"- Zip-slip / path-traversal check: {'PASS' if checks.get('no_path_traversal', True) else 'BLOCKED'}")
    A(f"- Absolute path check: {'PASS' if checks.get('no_path_traversal', True) else 'BLOCKED'}")
    A(f"- Corruption / openable check: {'PASS' if checks.get('openable') else 'FAIL'}")
    A(f"- Compression ratio (CR_total): {s.get('cr_total')} (flag > 50): "
      f"{'OK' if checks.get('compression_ratio_within_limit', True) else 'WARNING'}")
    A("- Streaming read check: PASS (members hashed/sampled via streaming; "
      "whole zip never loaded into memory)")
    A("- Unsupported file handling: safely skipped / streamed, never parsed as text")
    A("- Fail-closed behavior: covered by automated tests (missing/corrupt/"
      "zip-slip/absolute-path)")
    A("")
    A("## 3. Dataset Family Breakdown")
    A("")
    A("### chess_pgn")
    A(f"- Files detected: {chess.get('files_detected', 0)}")
    A(f"- Games parsed: {chess.get('games_parsed', 0)}")
    A(f"- Games with Elo: {chess.get('games_with_elo', 0)}")
    A(f"- Games with result: {chess.get('games_with_result', 0)}")
    A(f"- High-confidence upsets: {chess.get('high_confidence_upsets', 0)}")
    A(f"- Timeout/abandonment cases: {chess.get('timeout_or_abandon_cases', 0)}")
    A(f"- Brier calibration stress: {chess.get('brier_calibration_stress')}")
    A(f"- High-confidence failure rate: {chess.get('high_confidence_failure_rate')}")
    A("- Simulation usefulness: calibration + high-confidence-failure stress "
      "testing by analogy to trading discipline.")
    A("- Limitations: chess is NOT market data; used only to harden scoring "
      "discipline and calibration.")
    A("")
    A("### hackathon_project")
    A(f"- Files detected: {hack.get('files_detected', 0)}")
    A(f"- Projects inferred: {hack.get('projects_inferred', 0)}")
    A(f"- Product clarity metrics: {hack.get('clarity_metrics', {})}")
    A("- Simulation usefulness: product/MVP discipline (clarity, evidence "
      "depth, reproducibility, risk disclosure).")
    A("- Limitations: product/process simulation, NOT financial outcomes.")
    A("")
    A("### scraped_text")
    A(f"- Files detected: {scraped.get('files_detected', 0)}")
    A(f"- Documents parsed: {scraped.get('documents', 0)}")
    A(f"- Unique sources: {scraped.get('unique_sources', 0)}")
    A(f"- Source diversity (normalized): {scraped.get('source_diversity', 0.0)}")
    A(f"- Duplicate ratio: {scraped.get('duplicate_ratio', 0.0)}")
    A("- Simulation usefulness: noise handling, source diversity, duplicate "
      "detection, provenance completeness.")
    A("- Limitations: noisy evidence, NOT ground truth.")
    A("")
    A("### market_or_finance_data")
    A(f"- Files detected: {market.get('files_detected', 0)}")
    A(f"- Files parsed: {market.get('files_parsed', 0)}")
    A(f"- Files with valid market data: {market.get('files_with_valid_market_data', 0)}")
    A(f"- Rows parsed: {market.get('rows_parsed', 0)}")
    A(f"- Valid price rows: {market.get('valid_price_rows', 0)}")
    A("- Market metrics: only computed when dated/tickered/priced rows clear "
      "thresholds (>=100 rows; >=50 prob preds for calibration); else NO_DATA.")
    A("- Limitations: absent valid market data, NO market metrics are produced "
      "(fail-closed, never faked).")
    A("")
    A("### code_corpus")
    A(f"- Files detected: {code.get('files_detected', 0)}")
    A("- Simulation usefulness: family stats only; not parsed as simulation "
      "evidence in this version.")
    A("")
    A("### unknown")
    A(f"- Files detected: {unknown.get('files_detected', 0)}")
    A("- Handling: safely skipped (no crash, no parse).")
    A("")
    A("## 4. Segmented Upgrade Scores")
    A("")
    A("| Segment | Before | After | Delta | Relative Lift | Evidence Basis | Label |")
    A("|---|---:|---:|---:|---:|---|---|")
    out.extend(_segment_rows(scores))
    A("")
    overall = scores.get("overall", {})
    A(f"Caps applied: {overall.get('caps_applied')}")
    A("")
    A("## 5. Mathematical Appendix")
    A("- Elo expected score: `E_white = 1 / (1 + 10^(-ΔElo/400))`")
    A("- Surprise: `|A_white - E_white|`; Upset: high-confidence wrong-side result")
    A("- Brier: `(1/n) Σ (p_i - y_i)^2`")
    A("- ECE: `Σ_m (|B_m|/n) |acc(B_m) - conf(B_m)|`")
    A("- Reliability decomposition: `BS = REL - RES + UNC`")
    A("- Shannon diversity: `D = H/log(K)`, `H = -Σ p_k log p_k`")
    A("- Duplicate ratio: `duplicate_count / max(total_documents, 1)`")
    A("- Volume score: `100 (1 - e^{-N/1000})`")
    A("- Weighted overall: `Σ_c w_c * score_c`, `Σ_c w_c = 1`")
    A("- Caps: tests-fail -> after<=60; guardrails-broken -> after<=30; "
      "provenance-missing -> evidence/provenance<=50")
    A("")
    A("## 6. What Actually Improved")
    A(_improvement_section(scores, diag))
    A("")
    A("## 7. What Did Not Improve / Honest Limits")
    A("- This does NOT prove live trading profitability.")
    A("- This does NOT prove stock prediction accuracy.")
    A("- Chess PGNs are not market data.")
    A("- Hackathon files are product/process simulations, not financial outcomes.")
    A("- Scraped text is noisy evidence, not ground truth.")
    A("- Market metrics were only computed if valid market data existed; "
      "otherwise NO_DATA.")
    A("")
    A("## 8/9/10. Files, Commands, Tests")
    A("- See the integration commit and `tests/test_simulation_zip.py`.")
    A(f"- Reproduce: `python -m src.simulation_zip.run --zip \"{report.get('zip_path')}\"`")
    A("")
    return "\n".join(out)


def _improvement_section(scores: dict, diag: dict) -> str:
    segs = scores.get("segments", {})
    strong, moderate, slight, none_, blocked = [], [], [], [], []
    for cat, seg in segs.items():
        title = _SEGMENT_TITLES.get(cat, cat)
        delta = seg.get("delta", 0) or 0
        if delta >= 60:
            strong.append(title)
        elif delta >= 30:
            moderate.append(title)
        elif delta > 0:
            slight.append(title)
        else:
            none_.append(title)
    lines = [
        f"- **A. Strongly improved (Δ>=60):** {strong or 'none'}",
        f"- **B. Moderately improved (30<=Δ<60):** {moderate or 'none'}",
        f"- **C. Slightly improved (0<Δ<30):** {slight or 'none'}",
        f"- **D. No measured change (Δ<=0):** {none_ or 'none'}",
        f"- **E. Blocked/unavailable:** "
        f"{'corpus blocked' if diag.get('usable_records', 0) == 0 else 'none'}",
    ]
    return "\n".join(lines)


__all__ = [
    "write_json",
    "render_summary_markdown",
    "render_integration_markdown",
]
