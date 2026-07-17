# Simulation Intelligence Layer — Limitations & Empirical Honesty

This document exists because the repository has historically had **limited or zero
real-outcome evidence** in some operational audits. The SIL is sophisticated
*engineering*; that sophistication must **never** be converted into a claim of
predictive accuracy or profit.

---

## 1. The one rule

> A beautiful simulated distribution with no real outcomes behind it is
> `SIMULATED_ONLY` and can never masquerade as `MEASURED`.

The evidence label is *what kind of thing the output is*, never *how big the number
is*. It is never collapsed into a bare confidence.

## 2. Hard honesty caps (enforced / declared)

- **Empirical validation is `0.0 / 10`.** There are no leakage-safe real outcomes
  wired into the SIL. The machine-readable report hard-sets
  `empirical_validation_score = 0.0` and documents why.
- **No profitability claim.** The council never outputs expected return, P&L, or
  "alpha". `usefulness_score` measures *engineering + decision usefulness*, capped
  at 10, and is explicitly *not* predictive accuracy.
- **No validated alpha.** Not claimed anywhere; would require leakage-safe forward
  outcomes that do not yet exist.
- **Overall production-intelligence is capped below 9/10** while empirical
  calibration is materially incomplete (see the scoring section of the sprint
  report).

## 3. What is measured vs simulated vs proxied

| Category | In the SIL today |
|---|---|
| `MEASURED` | **None.** No lens returns `MEASURED` — there are no real outcomes behind it. |
| `EMPIRICALLY_CALIBRATED` | None yet — requires reconciled outcomes feeding the lens. |
| `BACKTEST_DERIVED` | None yet. |
| `MODEL_INFERRED` | Lens conclusions derived from the observation's real-ish inputs (returns, vol, liquidity). |
| `PROXY_DERIVED` | Narrative/source and catalyst proxies. |
| `SIMULATED_ONLY` | Monte-Carlo stress outcomes and pure what-if branches. |
| `INSUFFICIENT_DATA` | Any lens whose required inputs are missing. |
| `ENGINE_UNAVAILABLE` | Optional engine (Stockfish/COPASI) absent. |

Proxy metrics are kept **separate** from measured metrics; backtest outcomes would be
kept separate from live/forward outcomes.

## 4. Leakage & bias posture

The SIL is a forward what-if tool over a **caller-supplied observation with an
explicit `data_cutoff`**; it does not itself read historical price panels, so it
introduces no new look-ahead surface. The honesty obligations it inherits from the
product:

- **Look-ahead / timestamp leakage** — every run records `as_of` and `data_cutoff`;
  replay is keyed on them. The SIL never reaches past the cutoff because it only sees
  what the caller passes.
- **Revised-data leakage** — the SIL stores the exact input snapshot
  (`request_json`) so a replay uses the *same* inputs, not later-revised ones.
- **Survivorship / benchmark-selection bias** — the SIL makes no cross-sectional
  ranking and picks no benchmark, so it adds none. (The existing
  `survivorship_bias_corrector` remains the owner of that concern for discovery.)
- **Duplicated outcomes** — the council's `provenance.deduplicate` prevents the same
  evidence fingerprint from being counted twice within a run.

**Not yet done:** because no real outcomes feed the SIL, there is no SIL-specific
leakage-safe backtest to audit. When outcomes are wired in, they must go through the
existing `outcome_evidence_extractor` / `calibration_map` leakage guards *before*
any lens is allowed to emit a label stronger than `MODEL_INFERRED`.

## 5. Modelling limitations (be skeptical)

- **The domain mappings are analogies, not physical facts.** "Price as position,
  liquidity as friction, catalyst as force" is a *useful modelling stance*, presented
  as such — never as a law of nature. The lenses label their outputs accordingly.
- **The six lenses are not fully independent.** They share the same observation, so
  agreement can be an artefact of shared inputs. The aggregator penalises this
  (`SHARED_EVIDENCE_ILLUSION`, `INSUFFICIENT_INDEPENDENCE`, correlation penalty), but
  independence is bounded by construction.
- **Monte-Carlo bounds are deliberately small** (default 512 runs) for CPU-safety;
  tail estimates are coarse. Convergence is reported, not assumed.
- **No neural policy/value model is trained** (Leela/Maia) — insufficient data. The
  policy-value and human-error layers are original heuristics, labelled as such.
- **Optional engines are curiosities, not authorities.** Stockfish/COPASI, when
  enabled, widen search/solver breadth; they never change the advisory contract and
  are never required.

## 6. What would raise the empirical score

1. Wire reconciled outcomes (`reconciliation_results` / `imported_outcomes`) to the
   lenses through the existing leakage-safe calibration path.
2. Record forward (post-cutoff) outcomes for stored runs and compute calibration
   (Brier/ECE) *out of sample*.
3. Only then may a lens emit `EMPIRICALLY_CALIBRATED` / `BACKTEST_DERIVED`, and only
   then may the empirical-validation score rise above 0 — and never above 5/10
   without adequate real outcomes.

Until then: **the SIL is a rehearsal and stress-thinking instrument. It is not
evidence that any trade will make money.**
