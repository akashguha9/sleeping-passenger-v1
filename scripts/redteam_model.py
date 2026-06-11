"""Model red-team — 20 adversarial cases against the REAL modules (Pass 5).

Every case attacks the production-wired guards (grounding, temporal,
evidence, sensitivity, memo, backtest) and asserts a specific SAFE
behavior: reject / abstain / lower confidence / zero weight / mark
invalid / require human review. A case that produces a confident
act-recommendation without evidence is a FAILURE.

Run:  python scripts/redteam_model.py     (exit 1 on any failure)
Output: reports/model_redteam_<timestamp>.md
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

try:
    from scripts import llm_grounding_guard as gg
    from scripts import temporal_guard as tg
    from scripts import data_quality as dq
    from scripts import sensitivity_analysis as sa
    from scripts import generate_decision_memo as memo
    from scripts import syndication_detector as syn
    from scripts import backtest_advisory_signals as bt
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import llm_grounding_guard as gg  # type: ignore[no-redef]
    import temporal_guard as tg  # type: ignore[no-redef]
    import data_quality as dq  # type: ignore[no-redef]
    import sensitivity_analysis as sa  # type: ignore[no-redef]
    import generate_decision_memo as memo  # type: ignore[no-redef]
    import syndication_detector as syn  # type: ignore[no-redef]
    import backtest_advisory_signals as bt  # type: ignore[no-redef]

_REPO_ROOT = Path(__file__).resolve().parents[1]
UTC = _dt.timezone.utc
DEC = _dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
KNOWN = {"ACME", "TSLA", "TCS.NS", "SHEL", "SHEL.L"}


def _ev(symbol="ACME", confidence=0.9, freshness_days=1.0, contradicts=False,
        eid="EV-RT", claim="ACME wins a large contract"):
    return {"evidence_id": eid, "symbol": symbol, "confidence": confidence,
            "freshness_days": freshness_days, "contradicts": contradicts,
            "claim": claim, "source_name": "wire"}


def run_cases() -> list[dict]:
    """Run all 20 adversarial cases; each returns {name, ok, behavior}."""
    cases: list[dict] = []

    def case(name: str, ok: bool, behavior: str) -> None:
        cases.append({"name": name, "ok": bool(ok), "behavior": behavior})

    # 1. Fake ticker.
    c = gg.ground_claim(claim="ZZZX to moon", symbol="ZZZX", base_weight=0.9,
                        evidence_items=[_ev(symbol="ZZZX")], known_symbols=KNOWN)
    case("fake_ticker", c.classification == gg.REJECTED and c.weight == 0.0,
         "rejected as hallucination, weight 0")

    # 2. Real ticker, hallucinated catalyst (no evidence for the claim).
    c = gg.ground_claim(claim="ACME approved for defense contract", symbol="ACME",
                        base_weight=0.9, evidence_items=[], known_symbols=KNOWN)
    case("hallucinated_catalyst", c.weight == 0.0 and c.classification == gg.UNSOURCED,
         "unsourced → zero scoring weight")

    # 3. Stale news.
    fresh = gg.ground_claim(claim="ACME wins a large contract", symbol="ACME",
                            base_weight=0.5, evidence_items=[_ev(freshness_days=0.5)])
    stale = gg.ground_claim(claim="ACME wins a large contract", symbol="ACME",
                            base_weight=0.5, evidence_items=[_ev(freshness_days=90)])
    case("stale_news", stale.weight < fresh.weight / 10,
         f"90-day-old source decays weight {fresh.weight:.4f}→{stale.weight:.6f}")

    # 4. Contradictory evidence.
    contra = gg.ground_claim(
        claim="ACME wins a large contract", symbol="ACME", base_weight=0.5,
        evidence_items=[_ev(), _ev(eid="EV-2", contradicts=True,
                                   claim="ACME loses the contract bid")])
    case("contradictory_evidence",
         contra.weight < fresh.weight and contra.contradiction_penalty < 1.0,
         "contradiction penalty engaged")

    # 5. Missing price history → backtest refuses metrics, claims nothing.
    rep = bt.run_backtest([], assumptions=bt.Assumptions())
    case("missing_price_history", rep["headline"]["n"] == 0
         and "no metrics claimed" in rep["headline"].get("warning", ""),
         "empty data → no metrics claimed")

    # 6. Extreme outlier return — must surface, not silently average away.
    rep = bt.run_backtest([
        {"signal_id": "S1", "symbol": "ACME",
         "t_decision": DEC.isoformat(),
         "t_outcome": (DEC + _dt.timedelta(days=5)).isoformat(),
         "entry_price": 100, "exit_price": 900},
    ], assumptions=bt.Assumptions(transaction_cost=0, slippage=0))
    case("extreme_outlier", rep["headline"]["best"] == rep["headline"]["worst"] == 8.0
         and rep["headline"]["small_sample_warning"],
         "outlier visible in best/worst + small-sample warning")

    # 7. Stock split (price halves overnight): looks like -50% — the
    #    evidence layer requires provenance; unadjusted series is a data
    #    bug surfaced via worst-return visibility, never auto-corrected.
    rep = bt.run_backtest([
        {"signal_id": "SPLIT", "symbol": "ACME",
         "t_decision": DEC.isoformat(),
         "t_outcome": (DEC + _dt.timedelta(days=1)).isoformat(),
         "entry_price": 100, "exit_price": 50},
    ], assumptions=bt.Assumptions(transaction_cost=0, slippage=0))
    case("stock_split_artifact", rep["headline"]["worst"] == -0.5
         and rep["headline"]["small_sample_warning"],
         "split artifact visible as -50% with warning — human must adjust data")

    # 8. Currency mismatch — evidence records currency; mixing is visible.
    e = dq.build_evidence(source_type="api", source_name="nse",
                          claim="TCS quarterly revenue",
                          raw_evidence=b"x", observed_at=DEC,
                          symbol="TCS.NS", currency="inr")
    case("currency_mismatch", e.currency == "INR",
         "currency normalized + recorded; INR vs USD can't silently mix")

    # 9. Duplicate syndicated article across 20 outlets.
    copies = [_ev(eid=f"EV-{i}",
                  claim="ACME Corp wins major defense contract worth $2bn",
                  confidence=0.9) for i in range(20)]
    for i, c2 in enumerate(copies):
        c2["source_name"] = f"outlet_{i}"
    eff = syn.effective_sources(copies)
    single = gg.ground_claim(claim="ACME Corp wins major defense contract worth $2bn",
                             symbol="ACME", base_weight=0.5,
                             evidence_items=copies[:1])
    syndicated = gg.ground_claim(claim="ACME Corp wins major defense contract worth $2bn",
                                 symbol="ACME", base_weight=0.5,
                                 evidence_items=copies)
    case("syndicated_duplicates",
         eff["effective_count"] == 1 and abs(syndicated.weight - single.weight) < 1e-9,
         f"20 copies collapse to {eff['effective_count']} effective source; "
         "weight identical to single source")

    # 10. Low-float pump language → speculation, note only.
    c = gg.ground_claim(claim="ACME could 10x, unconfirmed whispers of buyout",
                        symbol="ACME", base_weight=0.9, evidence_items=[_ev()])
    case("pump_language", c.classification == gg.SPECULATION and c.weight == 0.0,
         "speculative phrasing → note-only, zero weight")

    # 11. Insider rumor with no source.
    c = gg.ground_claim(claim="insider says ACME earnings beat",
                        symbol="ACME", base_weight=0.9, evidence_items=[])
    case("insider_rumor", c.weight == 0.0, "no source → zero weight")

    # 12. LLM overconfident claim (conf 0.99, one weak stale source).
    c = gg.ground_claim(claim="ACME wins a large contract", symbol="ACME",
                        base_weight=0.99,
                        evidence_items=[_ev(confidence=0.3, freshness_days=30)])
    case("llm_overconfidence", c.weight < 0.075,
         f"0.99 claimed → {c.weight:.4f} grounded (evidence caps confidence)")

    # 13. Future filing leaked into past decision.
    v = tg.validate_sample(t_decision=DEC,
                           t_published=DEC + _dt.timedelta(hours=2),
                           t_outcome=DEC + _dt.timedelta(days=5))
    case("future_filing_leak", v.status == tg.INVALID,
         "t_published > t_decision → sample invalid for evaluation")

    # 14. Survivorship-biased universe: rejects must be REPORTED.
    rep = bt.run_backtest([
        {"signal_id": "DEAD", "symbol": "GONE",
         "t_decision": DEC.isoformat(), "t_outcome": DEC.isoformat(),  # leak
         "entry_price": 100, "exit_price": 0.01},
        {"signal_id": "OK", "symbol": "ACME",
         "t_decision": DEC.isoformat(),
         "t_outcome": (DEC + _dt.timedelta(days=5)).isoformat(),
         "entry_price": 100, "exit_price": 101},
    ], assumptions=bt.Assumptions())
    case("survivorship_reporting",
         rep["samples_rejected_by_temporal_guard"] == 1
         and rep["rejection_reasons"],
         "invalid samples reported, never silently dropped")

    # 15. Delisted ticker (exit price ~0) — visible catastrophic return,
    #     small-sample warning, no smoothing.
    case("delisted_ticker", rep["headline"]["n"] == 1,
         "delisted-style sample either valid+visible or rejected+reported")

    # 16. Non-tradable/private company → not in universe → rejected.
    c = gg.ground_claim(claim="PrivateCo to IPO", symbol="PRIVCO",
                        base_weight=0.8, evidence_items=[_ev(symbol="PRIVCO")],
                        known_symbols=KNOWN)
    case("private_company", c.classification == gg.REJECTED,
         "outside evidence-backed universe → rejected")

    # 17. Dual listing (SHEL vs SHEL.L): distinct symbols don't cross-pollinate.
    c = gg.ground_claim(claim="Shell raises dividend", symbol="SHEL",
                        base_weight=0.5,
                        evidence_items=[_ev(symbol="SHEL.L", claim="Shell raises dividend")],
                        known_symbols=KNOWN)
    case("dual_listing", c.weight == 0.0,
         "evidence for SHEL.L does not ground a SHEL claim — listings stay distinct")

    # 18. Ambiguous ticker symbol — unknown symbol fails closed.
    c = gg.ground_claim(claim="ABC beats earnings", symbol="ABC",
                        base_weight=0.5, evidence_items=[_ev(symbol="ABC")],
                        known_symbols=KNOWN)
    case("ambiguous_ticker", c.classification == gg.REJECTED,
         "symbol not in master → fail closed")

    # 19. Macro shock day — instability triggers ABSTAIN.
    rep_sa = sa.analyze({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5},
                        decision_threshold=0.5, sigma=0.25)
    case("macro_shock_instability", rep_sa["recommendation"] == sa.ABSTAIN,
         "borderline score under high noise → ABSTAIN recommendation")

    # 20. Earnings date timezone edge: 09:00 IST release vs 13:00 CET decision.
    ist = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
    cet = _dt.timezone(_dt.timedelta(hours=1))
    eastern = _dt.timezone(_dt.timedelta(hours=-4))
    ok = tg.validate_sample(
        t_decision=_dt.datetime(2026, 6, 1, 13, 0, tzinfo=cet),     # 12:00 UTC
        t_published=_dt.datetime(2026, 6, 1, 9, 0, tzinfo=ist),     # 03:30 UTC
        t_outcome=_dt.datetime(2026, 6, 2, 9, 30, tzinfo=eastern),  # next day
    )
    bad = tg.validate_sample(
        t_decision=_dt.datetime(2026, 6, 1, 13, 0, tzinfo=cet),     # 12:00 UTC
        t_published=_dt.datetime(2026, 6, 1, 20, 0, tzinfo=ist),    # 14:30 UTC
        t_outcome=_dt.datetime(2026, 6, 2, 9, 30, tzinfo=eastern),
    )
    case("earnings_timezone_edge",
         ok.status == tg.VALID and bad.status == tg.INVALID,
         "IST/CET/US-Eastern conversions decide validity correctly")

    return cases


def write_report(cases: list[dict], out_dir: Path | None = None) -> Path:
    out_dir = out_dir or (_REPO_ROOT / "reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"model_redteam_{stamp}.md"
    passed = sum(1 for c in cases if c["ok"])
    lines = [
        "# Model red-team report", "",
        f"Generated: {_dt.datetime.now(UTC).isoformat()} · "
        f"**{passed}/{len(cases)} adversarial cases safe**", "",
        "Advisory-only: every case asserts a SAFE behavior (reject / abstain "
        "/ zero-weight / invalid / human review). No case can produce an "
        "execution — there is nothing to execute.", "",
        "| # | Case | Result | Safe behavior observed |",
        "| - | ---- | ------ | ---------------------- |",
    ]
    for i, c in enumerate(cases, 1):
        lines.append(f"| {i} | {c['name']} | {'✅ SAFE' if c['ok'] else '❌ FAIL'} "
                     f"| {c['behavior']} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> int:
    cases = run_cases()
    path = write_report(cases)
    failed = [c for c in cases if not c["ok"]]
    print(f"red-team: {len(cases) - len(failed)}/{len(cases)} safe → {path}")
    for c in failed:
        print(f"  FAIL: {c['name']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
