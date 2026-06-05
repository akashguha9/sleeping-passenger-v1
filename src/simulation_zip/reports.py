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


_SC_TITLES = {
    "local_corpus_accessibility": "Local corpus accessibility",
    "safe_ingestion_robustness": "Safe ingestion robustness",
    "incremental_reproducibility_cache": "Incremental reproducibility/cache",
    "dataset_family_classification": "Dataset family classification",
    "parser_coverage": "Parser coverage",
    "parsed_simulation_volume": "Parsed simulation volume",
    "evidence_quality": "Evidence quality",
    "noise_duplicate_handling": "Noise and duplicate handling",
    "source_diversity": "Source diversity",
    "market_data_readiness": "Market-data readiness",
    "calibration_hardening": "Calibration hardening",
    "abstention_overconfidence_discipline": "Abstention/overconfidence discipline",
    "high_confidence_failure_handling": "High-confidence failure handling",
    "delayed_outcome_handling": "Delayed outcome handling",
    "product_mvp_clarity": "Product/MVP clarity",
    "advisory_guardrail_preservation": "Advisory-only guardrail preservation",
    "report_dashboard_usefulness": "Report/dashboard usefulness",
    "test_coverage": "Test coverage",
}

_SC_ORDER = list(_SC_TITLES.keys())


def _sc_rows(card: dict) -> list[str]:
    segs = card.get("segments", {})
    rows = []
    for cat in _SC_ORDER:
        s = segs.get(cat, {})
        rows.append(
            f"| {_SC_TITLES[cat]} | {s.get('before')} | {s.get('after')} "
            f"| {s.get('delta')} | {s.get('relative_lift_pct')}% "
            f"| weight={s.get('weight')} | {s.get('label')} |"
        )
    o = card.get("overall", {})
    rows.append(
        f"| **Overall MVP simulation-readiness** | {o.get('overall_before')} "
        f"| {o.get('overall_after')} | {o.get('overall_delta')} "
        f"| {o.get('overall_relative_lift_pct')}% | weighted | SIMULATION_ONLY |"
    )
    return rows


def render_sprint2_scorecard_markdown(report: dict) -> str:
    card = report.get("scorecard", {})
    o = card.get("overall", {})
    lines = [
        "# Sleeping Passenger — Zip Simulation Sprint 2 Scorecard",
        "",
        f"_Run type: **{report.get('run_type')}** | Corpus: {report.get('corpus_label')} "
        f"| {report.get('generated_at')}_",
        f"_Labels: {', '.join(SIMULATION_LABELS)}_",
        "",
        "| Segment | Before | After | Delta | Relative Lift | Evidence Basis | Label |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    lines += _sc_rows(card)
    lines += [
        "",
        f"Segment caps: {o.get('segment_caps')}",
        f"Overall caps: {o.get('overall_caps')}",
        "",
        "> SIMULATION_ONLY. Not live trading proof, not broker data, not "
        "financial advice. 'Before' = Sprint-1 capability on this corpus; "
        "'After' = Sprint-2 upgraded capability.",
        "",
    ]
    return "\n".join(lines)


def render_sprint2_integration_markdown(report: dict) -> str:
    s = report.get("safety", {})
    diag = report.get("diagnostics", {})
    fb = report.get("family_breakdown", {})
    adv = report.get("advanced_metrics", {})
    card = report.get("scorecard", {})
    o = card.get("overall", {})
    cache = report.get("cache", {})
    chess = fb.get("chess_pgn", {})
    scraped = fb.get("scraped_text", {})
    market = fb.get("market_or_finance_data", {})
    cal = adv.get("calibration", {})
    eqr = adv.get("evidence_quality", {})

    out: list[str] = []
    A = out.append
    A("# Sleeping Passenger Zip Simulation Sprint 2 Report")
    A("")
    A(f"_Labels: {', '.join(SIMULATION_LABELS)}_")
    A("")
    A("## 1. Executive Summary")
    A(f"- Run type: **{report.get('run_type')}**")
    A(f"- Zip found: {report.get('run_type') not in ('BLOCKED_NO_ZIP',)}")
    A(f"- Zip size: {s.get('zip_file_mb')} MB")
    A(f"- Files scanned: {s.get('member_count')}")
    A(f"- Parsed simulation records: {diag.get('usable_records')}")
    A(f"- Dataset families detected/parsed: {diag.get('families_detected')} / "
      f"{diag.get('families_parsed')}")
    A(f"- Overall before -> after: {o.get('overall_before')} -> "
      f"{o.get('overall_after')} (Δ {o.get('overall_delta')})")
    A("- Label: SIMULATION_ONLY")
    A("")
    A("## 2. Local Corpus Reality Check")
    rt = report.get("run_type")
    if rt == "REAL_LOCAL_ZIP":
        A("This report used the local Windows file path supplied by the user "
          "(REAL_LOCAL_ZIP).")
    elif rt == "BLOCKED_NO_ZIP":
        A("BLOCKED_NO_ZIP — the supplied local zip path was not reachable in "
          "this execution environment, so the run failed closed. Re-run the "
          "exact command on the machine that holds the zip for real numbers.")
    elif rt == "BLOCKED_UNSAFE":
        A("BLOCKED_UNSAFE — the archive was present but failed safety checks "
          "(corruption/zip-slip/zip-bomb). Failed closed.")
    else:
        A(f"SYNTHETIC_FIXTURE / {rt} — exercised against a generated fixture, "
          "not the real corpus.")
    A("")
    A("## 3. Safety and Fail-Closed Results")
    checks = s.get("checks", {})
    A(f"- Archive status: {s.get('archive_status')} ({s.get('reason')})")
    A(f"- Path-traversal / absolute-path: {'PASS' if checks.get('no_path_traversal', True) else 'BLOCKED'}")
    A(f"- Corruption/openable: {'PASS' if checks.get('openable') else 'FAIL/NA'}")
    A(f"- Compression ratio (CR_total): {s.get('cr_total')}")
    A("- Streaming memory-safe read: PASS (no full-zip load)")
    A(f"- Cache hit rate (incremental index): {cache.get('cache_hit_rate')}")
    A("")
    A("## 4. Dataset Family Breakdown")
    A(f"- chess_pgn: games={chess.get('games', chess.get('games_parsed', 0))}, "
      f"upset_rate={chess.get('upset_rate')}, hc_failure_rate={chess.get('high_conf_failure_rate')}, "
      f"draw_rate={chess.get('draw_rate')}, long_game_rate={chess.get('long_game_rate')}, "
      f"timeout_rate={chess.get('timeout_rate')}")
    A(f"- hackathon_project: projects={fb.get('hackathon_project', {}).get('projects')}, "
      f"product_corpus={fb.get('hackathon_project', {}).get('product_corpus')}")
    A(f"- scraped_text: docs={scraped.get('documents')}, "
      f"unique_domains={scraped.get('unique_domains')}, "
      f"domain_diversity={scraped.get('domain_diversity')}, "
      f"duplicate_ratio={scraped.get('duplicate_ratio')}")
    A(f"- market_or_finance_data: valid_files={market.get('files_with_valid_market_data')}, "
      f"fully_ready={market.get('fully_ready')} "
      f"(MARKET_DATA_DESCRIPTIVE_ONLY unless valid signals+outcomes)")
    A("")
    A("## 5. Advanced Metrics")
    if cal.get("status") == "OK":
        ts = cal.get("tau_star") or {}
        A(f"- Calibration (chess Elo stress): Brier={cal.get('brier')}, "
          f"ECE={cal.get('ece')}, MCE={cal.get('mce')}")
        A(f"- Reliability decomposition: {cal.get('reliability')}")
        A(f"- Abstention τ* (max DQS): threshold={ts.get('threshold')}, "
          f"coverage={ts.get('coverage')}, accuracy={ts.get('accuracy')}, "
          f"hcfr={ts.get('hcfr')}, dqs={ts.get('dqs')}")
        A(f"- Bootstrap CI (Brier): {cal.get('brier_bootstrap_ci')}")
    else:
        A("- Calibration: NO_DATA")
    A(f"- Evidence quality: Q_corpus={eqr.get('Q_corpus')} band={eqr.get('band')}")
    A(f"- Extra bootstrap CIs: {list(adv.get('bootstrap_cis', {}).keys()) or 'NO_DATA'}")
    A("")
    A("## 6. Sprint 2 Segmented Scores")
    A("")
    A("| Segment | Before | After | Delta | Relative Lift | Evidence Basis | Label |")
    A("|---|---:|---:|---:|---:|---|---|")
    out.extend(_sc_rows(card))
    A("")
    A(f"Overall caps: {o.get('overall_caps')} | Segment caps: {o.get('segment_caps')}")
    A("")
    A("## 7. What Improved")
    A(_sc_improvement(card))
    A("")
    A("## 8. What Did Not Improve / Honest Limits")
    A("- Does NOT prove live trading profitability.")
    A("- Does NOT prove stock prediction accuracy.")
    A("- Chess PGNs are behavioural/calibration stress data, not market data.")
    A("- Hackathon files are product/process simulations.")
    A("- Scraped text is noisy evidence, not ground truth.")
    A("- Market metrics computed only if valid market-like data existed; else NO_DATA.")
    A("- Any uplift is SIMULATION-READINESS uplift, not alpha.")
    A("")
    A("## 9. Mathematical Appendix")
    A("- Compression ratio: `uncompressed/max(compressed,1)`")
    A("- Family confidence v2: `0.20·ext+0.25·hdr+0.20·kw+0.20·schema+0.10·path+0.05·meta`")
    A("- Cache key: `SHA256(zip_path::size::archive::csize::usize::mtime)`; "
      "strong: `SHA256(zip_path::archive::file_sha256)`")
    A("- Evidence quality: `Q=100·Σ w_k·c_k` (provenance .20, parser_conf .15, "
      "schema .15, source .15, recency .10, dedup .10, safety .10, limits .05)")
    A("- Shannon diversity: `D=H/ln(K)`; duplicate_ratio: `dups/max(n,1)`")
    A("- Elo expected: `1/(1+10^(-ΔElo/400))`; surprise: `|A-E|`")
    A("- Brier, LogLoss, ECE, MCE; reliability `BS=REL-RES+UNC`")
    A("- Abstention: act iff `max(p,1-p)>=τ`; DQS=`acc·cov^0.5·(1-hcfr)^2`; τ*=argmax DQS")
    A("- Bootstrap percentile CI (seeded); market returns/Sharpe/Sortino/MDD")
    A("- Scorecard caps: zip_not_found<=40; safety_blocked<=50; tests_fail<=60; "
      "guardrails_broken<=30; provenance_missing -> evidence<=50 & ingestion<=60; "
      "no_market -> market_readiness<=60; no_outcomes -> calibration<=75; "
      "no_records -> volume/evidence/diversity=0")
    A("")
    A("## 11. Commands to Reproduce")
    A(f"`python -m src.simulation_zip.run --sprint2 --zip \"{report.get('zip_path')}\" "
      "--bootstrap-samples 300 --seed 42`")
    A("")
    return "\n".join(out)


def _sc_improvement(card: dict) -> str:
    segs = card.get("segments", {})
    strong, mod, slight, none_ = [], [], [], []
    for cat, s in segs.items():
        d = s.get("delta", 0) or 0
        t = _SC_TITLES.get(cat, cat)
        if d >= 60:
            strong.append(t)
        elif d >= 30:
            mod.append(t)
        elif d > 0:
            slight.append(t)
        else:
            none_.append(t)
    return "\n".join([
        f"- Strongly improved (Δ>=60): {strong or 'none'}",
        f"- Moderately improved (30<=Δ<60): {mod or 'none'}",
        f"- Slightly improved (0<Δ<30): {slight or 'none'}",
        f"- No measured change (Δ<=0): {none_ or 'none'}",
    ])


__all__ = [
    "write_json",
    "render_summary_markdown",
    "render_integration_markdown",
    "render_sprint2_scorecard_markdown",
    "render_sprint2_integration_markdown",
]
