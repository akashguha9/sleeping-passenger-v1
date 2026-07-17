# Intelligence Budget Methodology

`intelligence_budget.py` prevents compute theatre: not every candidate deserves the
full council + ablation + optional engines.

## Allocation
From a cheap prescreen (liquidity + actual field presence + return history) plus
tail risk, value-of-information and uncertainty, it emits one of:
- `REJECT_CHEAP` — weak, no tail, no research value → no council run at all.
- `SHALLOW` — insufficient price history → fail-closed shallow analysis.
- `STANDARD` — adequate quality, moderate uncertainty; `stop_researching` when
  strong + low-uncertainty + well-evidenced (don't over-analyse).
- `DEEP` — high tail risk / high VoI / high uncertainty on a plausible candidate →
  12 scenarios + pairwise ablation, optional engines justified only at high tail.

Cheap rejection is proven runtime-reached in the daily run (`JUNK → REJECT_CHEAP`,
no council). A `priority_score` ranks candidates for the operator's attention queue.
