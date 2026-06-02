# Trade-Log & Discovery Metrics

Advisory-only analytics over the operator's Google-Sheet trade log plus the
daily 5-model discovery board. Every module here is a pure function with no DB,
network, broker, or AI-execution surface. Nothing in this layer ever places an
order or tells the operator what to buy/sell — human execution stays mandatory.

Modules:

| Module | Role |
|---|---|
| `scripts/google_sheet_schema.py` | Normalize messy CSV export -> typed `TradeLogRow` + validation issues |
| `scripts/trade_log_metrics.py` | Capital, win-rate triad, expectancy, profit factor, diversity, cohorts |
| `scripts/outcome_maturity.py` | Trading-day maturity (don't judge young trades) |
| `scripts/model_version_performance.py` | Per-model-version cohorts (no overclaiming) |
| `scripts/mfe_mae.py` | Entry-quality diagnosis (MFE/MAE) |
| `scripts/country_diversity_gate.py` | Quotas, concentration warnings, trade-candidate caps |
| `scripts/discovery_board.py` | Daily discovery board (discovery before trade candidates) |
| `scripts/rejected_candidate_tracker.py` | Learn from false negatives / correct rejections |
| `scripts/dashboard_contract.py` | Stable unified JSON contract |

## 1. Capital — free cash is NOT total equity

`CAPITAL AFTER ROW` in the sheet is **free / unallocated cash**. It excludes
capital tied up in open positions, so it is *not* total equity. The schema
emits an `INFO CAPITAL_AFTER_ROW_NOT_EQUITY` issue and the metrics report sets
`capital_after_row_is_total_equity: false`.

```
Equity_marked = C_0 + CumPL_N
ReturnPct     = TotalPL / C_0
FreeCash      = final CAPITAL AFTER ROW
Allocated_open = Σ_i A_i · Remaining_i   for open/partial rows i
```

When a row's remaining fraction is missing it is inferred: CLOSED → 0.0,
PARTIAL_TP (booked ≥ 0.8) → 0.2, (≥ 0.5) → 0.5, OPEN → 1.0. Reconstruction
(`free_cash + allocated_open` vs `marked_equity`) rarely closes exactly because
of FX/leverage simplifications; the gap is **reported** (`reconstruction_discrepancy`),
never hidden.

## 2. Win rate — three honest definitions

```
Wins = #{P_i > 0}   Losses = #{P_i < 0}   Flats = #{P_i = 0}
WinRate_marked_ex_flat = Wins / (Wins + Losses)
WinRate_all_rows       = Wins / N
WinRate_closed         = ClosedWins / (ClosedWins + ClosedLosses)   (closed rows only)
```

Flat rows are excluded from the marked win rate. Closed-only is reported
separately; when the closed sample is small the report adds
`CLOSED_ONLY_EVIDENCE_IMMATURE` — low-sample closed results are never treated as
conclusive.

## 3. Expectancy & profit factor

```
AvgWin       = mean(P_i | P_i > 0)
AvgLossAbs   = |mean(P_i | P_i < 0)|
ProfitFactor = GrossProfit / |GrossLoss|
Expectancy   = p_win·AvgWin − (1 − p_win)·AvgLossAbs        (p_win = marked ex-flat)
R_expectancy = mean(R_i)        R_WinRate = R_wins / (R_wins + R_losses)
```

## 4. Country diversity & concentration

Two separate surfaces:

* **Realized trade log** (`trade_log_metrics`): `US_HEAVY` if US share > 0.50,
  `US_OVERCONCENTRATED` if > 0.65.
* **Daily discovery board** (`country_diversity_gate`): over the discovery
  output `p_c = n_c / N`,

```
HHI            = Σ_c p_c²
H              = −Σ_c p_c·ln(p_c)        H_norm = H / ln(K)   (K>1 else 0)
DiversityScore = 100 · H_norm · (1 − HHI)        clamped to [0, 100]
```

Discovery concentration warnings: `COUNTRY_CONCENTRATION_WARNING` (any
p_c > 0.40), `COUNTRY_OVERCONCENTRATION_BLOCK` (> 0.60),
`DISCOVERY_TOO_CONCENTRATED` (HHI > 0.35). Quotas (`config/discovery_quotas.yaml`)
govern discovery *visibility* and a per-country trade-candidate cap — they never
force a trade and the gate never fabricates a missing country (shortfalls are
reported, not invented).

## 5. Outcome maturity — don't judge young trades

Trading-day age uses a weekday-only approximation (no exchange-holiday
calendar yet — see TODO in `outcome_maturity.py`).

```
ScoreEligible_i = closed_i OR tp_hit_i OR stop_hit_i OR age_i ≥ 5 trading days
```

States: `CLOSED_SCORE_ELIGIBLE`, `EVENT_SCORE_ELIGIBLE`,
`MATURE_OPEN_SCORE_ELIGIBLE`, `PENDING_HORIZON`, `UNKNOWN`. Horizon buckets:
`TOO_EARLY` (<2), `FORMING` (2–4), `FIRST_HORIZON` (5–9), `EXTENDED_HORIZON` (≥10).

## 6. MFE / MAE entry quality

```
CurrentReturn = (Live − Entry) / Entry          (long-only)
MFE = (HighSinceEntry − Entry)/Entry   (provisional: max(0, CurrentReturn))
MAE = (LowSinceEntry  − Entry)/Entry   (provisional: min(0, CurrentReturn))
```

Diagnoses: `GOOD_DISCOVERY_BAD_EXIT`, `GOOD_THESIS_POOR_ENTRY_TIMING`,
`BAD_DISCOVERY_OR_BAD_ENTRY`, `GOOD_DISCOVERY_GOOD_ENTRY`, `PENDING_HORIZON`,
`INCONCLUSIVE`.

## 7. Rejected-candidate learning

Once a 5-day horizon is known: `FALSE_NEGATIVE_REVIEW` (r5 ≥ 0.05 or MFE ≥ 0.08),
`CORRECT_REJECTION` (r5 ≤ −0.03 and MAE ≤ −0.05), `NEUTRAL_REJECTION`
(|r5| < 0.02), else `INCONCLUSIVE_REVIEW`; missing horizon → `PENDING_HORIZON`.
Each emits an advisory `rejected_candidate_review` Moltbook entry.

## 8. Model-version cohorts

Derived from an explicit `model_version` column or inferred from the entry date
(`v2026_05_early` 05-14..05-20, `v2026_05_override` 05-21..05-24,
`v2026_05_recalibration` 05-25..05-31, `v2026_06_global_watchlist` ≥ 06-01).
Confidence: LOW (N<10), MEDIUM (10–29), HIGH (≥30). Cohorts with N<30 are
labelled "promising but immature" — improvement is never overclaimed on a small
sample.

## Advisory-only limitation

This is decision *support*, not decision *making*. All outputs carry
`execution_gate=LOCKED`, `broker_api_called=False`, `ai_execution_count=0`,
`real_money_sizing_impact=PROHIBITED`. The only candidate labels are advisory:
`WATCH`, `WAIT`, `AVOID`, `RISK_BLOCK`, `TRADE_CANDIDATE_FOR_MANUAL_REVIEW`,
`WATCH_CAP_LIMITED`, `OUTCOME_REVIEW_NEEDED`. No BUY/SELL/EXECUTE.

## CLI

```
python scripts/trade_log_metrics.py --input exports/trade_log.csv --starting-capital 4000
python scripts/trade_log_metrics.py --input exports/trade_log.csv --starting-capital 4000 --format json --report-date 2026-06-02
python scripts/model_version_performance.py --input exports/trade_log.csv
python scripts/dashboard_contract.py --input exports/trade_log.csv --starting-capital 4000
```
