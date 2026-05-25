# Demo Case Studies — Defensive Value (Kanté Edition)

> Advisory-only. None of these case studies claim a profit, return, or P/L
> improvement. They demonstrate *risk prevented* — the interceptions,
> recoveries, and clean-ups that make the MVP a 10/10 defender even with
> "no goals, no assists".

Generate the live numbers behind these studies with:

```bash
python -m scripts.business_value_report --json
```

---

## Case Study 1 — GLD/TSM loss → Moltbook repair (Recovery)

**Situation.** A real, operator-entered manual trade on GLD (and separately
TSM) closed at a loss. Historically the loss could sit unlogged — a "broken
window" that decays operator discipline.

**Defensive action.** `scripts/moltbook_reconciliation_bridge.py` reads the
closed losing reconciliation row and creates **exactly one** advisory-only
Moltbook learning entry per loss — derived entirely from real reconciliation
data, never invented. Re-running is idempotent (dedup by trade → reconciliation
→ ticker+close+pnl). Winning/flat/open trades are never turned into mistake
entries; missing P/L degrades to "insufficient data" rather than fabricating a
number.

**MVP equivalent.** *Recovery / mistake cleanup* — the loss is recovered into
the learning ledger so the next decision is better informed.

**Evidence.** `business_value_report.closed_losses_repaired_into_moltbook`
counts these. `release_gate` `closed_losses_detectable` makes coverage visible.

---

## Case Study 2 — Fake SPY/QQQ pollution → canonical truth repair (Interception)

**Situation.** `runtime/mvp_local.db` was once polluted with thousands of fake
demo Moltbook rows (`FABRIC_SPY` / `FABRIC_QQQ` event ids, the "Persistence
above 0.8" demo thesis, synthetic SPY "Thesis A" seeds). Demo data masquerading
as truth is the worst kind of own-goal.

**Defensive action.** The write path that allowed it is closed (Moltbook
sentinel guard + lazy `DB_PATH` resolution + the conftest runtime-DB isolation
fixture). `scripts/moltbook_cleanup_fake_seed.py` removes any residual fake rows
with a deliberately narrow, never-widening signature that can only match
unlinked demo rows — a real user-linked entry with the same text is preserved.
`release_gate` now **FAILS** if any fake pollution survives, so a polluted DB
can never ship.

**MVP equivalent.** *Interception* — fake data is blocked before it reaches the
operator or a demo audience.

**Evidence.** `business_value_report.fake_demo_pollution_active` (0 when clean)
and `release_gate.failing_checks` containing `moltbook_no_fake_pollution`.

---

## Case Study 3 — AI consensus echo → source-independence downgrade (Press resistance)

**Situation.** Five models (Grok, Claude, Codex, Gemini, Mistral, DeepSeek) all
"agree" — but they are all repeating one public catalyst. Naive consensus would
read this as five independent confirmations and over-promote the thesis.

**Defensive action.** `scripts/model_signal_normalizer.py` normalizes each
model snippet into one advisory schema, then uses the complex-systems
**source-independence** computation: a catalyst repeated across models collapses
to a single unique catalyst, driving `independence_score` down and
`echo_chamber_risk` up. Five genuinely independent catalysts score strictly
higher than one repeated catalyst. A report missing its `invalidation` is
promotion-blocked. No normalized output can become a BUY — `direction_bias` is
only `net_long_bias` / `net_short_bias` / `no_clear_bias`.

**MVP equivalent.** *Press resistance / tactical discipline* — the system does
not panic-promote under a wall of agreeing-but-echoing models.

**Evidence.** `model_signal_normalizer.normalize_model_reports(...).consensus`
exposes `independence_score`, `echo_chamber_risk`, `repeated_catalyst_count`.

---

## Why these matter (the Sofascore read)

| Defensive action | MVP equivalent | Where |
|---|---|---|
| Interception | fake data blocked | Case 2 — pollution gate |
| Recovery | Moltbook loss repair | Case 1 — reconciliation bridge |
| Positioning | release gate | `release_gate.py` |
| Transition control | indexed/paginated reads | `signal_index_query.py` |
| Ball retention | canonical SQLite truth | `advisory_contract.py` |
| Press resistance | echo-aware normalization | Case 3 — normalizer |
| Tactical discipline | advisory-only stamps everywhere | shared contract |

No goals. No assists. No leak.
