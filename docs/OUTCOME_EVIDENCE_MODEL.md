# Outcome Evidence Model

`scripts/outcome_evidence.py` — one canonical record per resolved outcome, with
explicit provenance so REAL / PAPER / SYNTHETIC / BACKTEST evidence never mixes.

## source_type (provenance)
`REAL_MANUAL_TRADE` · `PAPER_TRADE` · `IMPORTED_BACKTEST` · `SYNTHETIC_FIXTURE`.
**Synthetic fixtures are NEVER calibration-eligible** and can never raise the
runtime status to CALIBRATED.

## Return math
- LONG: `r = (P_exit − P_entry) / P_entry`
- SHORT: `r = (P_entry − P_exit) / P_entry`
- PnL fallback (no prices): `r = PnL / capital_at_risk`
- Levered: `r_L = L · r`
Returns are **never fabricated** — undeterminable → OPEN/ineligible.

## Labelling (ε = 0.001)
WIN if `r > ε`, LOSS if `r < −ε`, BREAKEVEN if `|r| ≤ ε`, else OPEN. An
authoritative classifier (reconciliation/Moltbook) may override the label
without inventing a return.

## Quality q_i ∈ [0,1]
`q = 0.15·a + 0.20·b + 0.10·c + 0.10·d + 0.15·e + 0.10·f + 0.15·g + 0.05·h`
(a=entry, b=exit/pnl, c=opened_at, d=closed_at, e=score_at_entry, f=ticker,
g=resolved-label, h=source reliability). A complete real manual trade → q≈1.0.

## Eligibility (q_min = 0.70)
Eligible iff source ∈ {REAL, PAPER, BACKTEST} ∧ label ∈ {WIN,LOSS,BREAKEVEN}
∧ score_at_entry present ∧ q ≥ q_min.

## Extraction
`scripts/outcome_evidence_extractor.py` builds these from manual trades +
reconciliation (+ Moltbook), precedence: reconciliation > trade exit > Moltbook
label > open/record-only (ineligible). Deterministic; no invented prices.
