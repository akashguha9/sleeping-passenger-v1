# Trade-Log Discovery Dashboard Contract

`scripts/dashboard_contract.py:build_dashboard()` emits one stable, versioned
JSON document (`contract_version: "trade_log_discovery_dashboard/v1"`) that a
frontend / API / Sheet export can consume without re-deriving anything.

## Shape

```json
{
  "contract_version": "trade_log_discovery_dashboard/v1",
  "report_date": "2026-06-02",
  "labels": {
    "marked_equity": "starting_capital + latest cumulative P/L",
    "free_cash": "CAPITAL AFTER ROW — free/unallocated cash, NOT total equity",
    "open_allocated_capital": "capital tied up in open/partial positions",
    "realised_pl": "P/L from closed rows",
    "unrealised_marked_pl": "marked P/L on open/partial rows",
    "closed_only_evidence_immature": "ok | closed-sample too small to be conclusive"
  },
  "capital": {
    "starting_capital": 4000.0,
    "marked_equity": 4029.76,
    "free_cash": 2623.934293,
    "open_allocated_capital": 1480.0,
    "total_pl": 29.76,
    "realised_pl": -5.5,
    "unrealised_marked_pl": 35.26,
    "return_pct": 0.00744,
    "capital_after_row_is_total_equity": false,
    "reconstruction_discrepancy": -74.17
  },
  "win_rate": {
    "wins": 4, "losses": 4, "flats": 3,
    "marked_win_rate_ex_flat": 0.5,
    "all_row_win_rate": 0.3636,
    "closed_win_rate": 0.3333,
    "closed_only_evidence_immature": true
  },
  "expectancy": {
    "average_win": 30.065, "average_loss_abs": 22.625,
    "profit_factor": 1.3288, "expectancy_per_trade": 3.72
  },
  "diversity": {
    "country_hhi": 0.2727, "country_entropy": 0.83,
    "country_diversity_score": 62.52, "us_share": 0.4545, "warnings": []
  },
  "outcome_maturity": { "pending_horizon": 2, "score_eligible": 9, "closed": 3,
                        "horizon_bucket_counts": {} },
  "model_versions": { "v2026_05_early": { "n": 2, "confidence": "LOW", ... } },
  "advisory_safety": {
    "advisory_only": true, "human_execution_required": true,
    "broker_api_called": false, "ai_execution_count": 0,
    "execution_gate": "LOCKED", "real_money_sizing_impact": "PROHIBITED"
  },
  "warnings": ["CLOSED_ONLY_EVIDENCE_IMMATURE", "CAPITAL_RECONSTRUCTION_DISCREPANCY"],
  "discovery_board": { "...optional..." }
}
```

## Explicit labels

The contract labels every capital figure so a consumer can never confuse:

* **Marked equity** = `starting_capital + latest cumulative P/L`.
* **Free cash** = `CAPITAL AFTER ROW` — unallocated, *not* equity.
* **Open allocated capital** = capital in open/partial positions.
* **Realised P/L** vs **unrealised / marked P/L** reported separately.
* **Closed-only evidence immature** flagged when the closed sample is < 10.

## Optional discovery board

Pass `discovery_board=` (the output of
`scripts/discovery_board.py:build_daily_discovery_board`) to attach the daily
board under `"discovery_board"`. The board carries: (A) per-country table,
(B) global top-30 ranked, (C) capped manual-review candidates, (D) concentration
warnings, (E) advisory-only labels — produced *before* trade candidates.

## Safety

The `advisory_safety` block is always `execution_gate=LOCKED`,
`broker_api_called=false`, `ai_execution_count=0`,
`real_money_sizing_impact=PROHIBITED`. The dashboard is decision support only.
