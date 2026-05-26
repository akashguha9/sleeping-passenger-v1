# Local-First Walkthrough

> Companion to the 5-minute demo: long-form explanation of the local
> truth surface for an operator who wants to understand *why* each
> control exists.

## What "local-first" means here

- The canonical store is local SQLite (`runtime/mvp_local.db`).
- JSONL is an audit-only mirror.  It is never canonical.
- The advisory contract is enforced by the
  `scripts/advisory_contract.py` module — every other surface borrows
  the stamp from it rather than hand-rolling its own.
- All persistence happens on the operator's machine.  No multi-tenant
  hosted services are required to use the MVP.

## The four truth surfaces

### 1. `TopTruthBar`

Renders a global mock/live/fallback chip.  When the backend is down it
flips to a red "backend offline" banner, never blanks out silently.

### 2. `SourceConfigurationSnapshot`

Counts configured (C), not-yet-configured (N), and total (T) sources
and asserts `C + N = T` in-band — drifts are visible on the same page.

### 3. `SourceHealthPanel`

Per-source freshness and degraded-state labels.  Fed by the watchdog
that writes `runtime/release/kalshi_source_health.json` (and analogues
for other providers).

### 4. `RunRefreshButton` + `RunRefreshPanel`

Single explicit action to refresh live providers.  The button text
contains the literal token "advisory-only" so a screen-reader operator
hears the safety posture too.

## The honest-by-construction calibration gate

The gate **refuses** to claim predictive validity until:

1. `N_real ≥ 200` calibration pairs with both `p_i` and `y_i` exist.
2. Brier score `BS ≤ 0.25`.
3. ECE `≤ 0.10`.
4. MCE `≤ 0.25`.

Until then, `predictive_claim_allowed = false` is emitted everywhere
the calibration state is referenced (scorecard, frontend gate panel,
report JSON).

## The seven-step honesty contract

A demo passes the contract when:

1. Advisory banner visible.
2. Mock/live truth bar visible.
3. Source configuration snapshot accurate.
4. Refresh button labelled advisory-only.
5. Refresh result includes `execution_gate=LOCKED`.
6. Calibration report shows `predictive_claim_allowed=false` until
   evidence unlocks it.
7. No forbidden trading vocabulary appears anywhere — "place trade",
   "execute trade", "broker order", "buy now", "sell now", "send
   order".

If any one of these fails, the demo is considered a *truth incident*
and must be fixed before recording.
