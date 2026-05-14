# Forensic Gap Analysis — Pre-Wiring Snapshot

> Read-only assessment produced before any code edit in this sprint.
> Comparing local repo, Claude export evidence (sanitized in
> [ZERO_BACKEND_CLAUDE_PROJECT_RECOVERY_SUMMARY.md](./ZERO_BACKEND_CLAUDE_PROJECT_RECOVERY_SUMMARY.md)),
> existing tests, existing docs, and the operational gaps described in
> the user's task brief.

## A. Current repo capabilities already present

### Signal reactor
- `scripts/signal_reactor.py` — full orchestrator with 8 reactor states,
  9 allowed-action labels, deterministic precedence rules, safety stamps,
  CLI. Tests: `tests/test_signal_reactor.py`,
  `tests/test_signal_reactor_safety_invariants.py`.
- Supporting modules (all pure, all advisory-only): `signal_field_geometry`,
  `echo_risk_engine`, `signal_decay_waste`, `fission_branch_mapper`,
  `fusion_thesis_engine`, `operator_control_rods`, `adaptive_signal_router`.
- Doctrine: `docs/SIGNAL_REACTOR_MODEL.md`, `docs/SIGNAL_REACTOR_USAGE.md`.

### Signal inbox / reflection desk
- `scripts/signal_inbox_api.py` — 8 public operations:
  list_inbox_items, get_inbox_diagnostics, get_signal_detail,
  run_validation, add_user_reflection, add_ai_discussion_summary,
  mark_signal, log_manual_trade, reconcile_trade, list_manual_trades.
- Per-item enrichment: sensitivity, toxic quarantine, journal quality.
- Backed by SQLite (canonical) with JSONL fallback.
- Frontend page: `frontend/src/app/signal-inbox/page.tsx` plus detail route.

### Self-test report
- `scripts/self_test_report.py` — read-only DB rollup, journal quality,
  reconciliation summary, process quality, AI validation distribution,
  Moltbook, source health. CLI flags for period, JSON, Markdown.
- Compact summary via `build_self_test_summary()` used by the API and
  the preflight bundler.

### Pre-real-money preflight
- `scripts/pre_real_money_preflight.py` — bundles five subchecks:
  `db_integrity`, `local_security`, `source_refresh`,
  `self_test_summary`, `reconciliation_queue`.
- Hard-block thresholds for unreconciled backlog
  (WARN=10, BLOCK=25, FULL_REVIEW=50).

### Reconciliation queue
- `scripts/reconciliation_queue.py` — read-only listing, per-trade
  journal-quality scoring, summary by ticker / emotional_state /
  expected_horizon, oldest age.
- Wired through `/self-test/reconciliation-queue` API endpoint and
  consumed by `frontend/src/app/reconciliation/page.tsx`.

### Frontend
- Next.js 14 + React 18 + TypeScript + Tailwind.
- Pages: signal-inbox, signal-inbox/[id], manual-trade-log,
  reconciliation, reflection-desk, live-signals, securities,
  chart-structure, moltbook, exports, settings, help, root.
- Components: SignalCard, ReconciliationCard, ManualTradeLogForm,
  HumanOnlyBadge, AdvisoryOnlyBadge, NoExecutionBanner, BullStateBadge,
  EvidenceTimeline, MoltbookEntryCard, NextHumanActionBadge,
  GateDetailsPanel, SignalScorePanel, SourceHealthPanel, etc.

## B. Missing capabilities clearly supported by repo + Claude source

1. **Signal-reactor enrichment of inbox responses.** The reactor exists and
   is tested; the inbox API does not currently call it. Grep across
   `scripts/` shows only `signal_reactor.py` references itself. The
   memories digest emphasises veto, control rods, gallardo block —
   matching reactor outputs.
2. **Signal-reactor self-check in pre-real-money preflight.** Preflight
   already bundles five subchecks; reactor is a natural sixth as a
   diagnostic confirming the safety/criticality layer is healthy.
3. **Signal-reactor visibility in self-test report.** Report already
   surfaces ai_validation, source_health, journal_quality. A
   `reactor_self_check` block fits the same pattern.

## C. Partially implemented capabilities

- **Frontend reactor surface.** No badge or panel currently exists for
  `reactor_state`, `decision_grade_energy`, `echo_risk_score`,
  `meltdown_risk_score`, `operator_heat_score`, or `gallardo_block`.
  The signal-inbox page renders `BullStateBadge`, `NextHumanActionBadge`
  etc., but the reactor fields are not yet on the wire.
  `docs/SIGNAL_REACTOR_MODEL.md §10` explicitly defers UI badges to
  future work — this sprint will land them in the backend payload so
  the frontend can pick them up next sprint.
- **Frontend testing.** `frontend/package.json` declares no test
  framework; the only `*.test.*` files in `frontend/` are inside
  `node_modules`. Frontend coverage is essentially zero.

## D. Contradictions between Claude export and local code

- Export memory cites Softr/Streamlit Cloud as the frontend; the live
  repo uses Next.js. The Next.js direction is correct and active —
  the memory is stale.
- Export memory cites Make.com / GitHub Actions for live phase
  automation; the repo has no such pipeline. Not a contradiction so
  much as an unstarted phase.
- ATOM "retire to 35 fields" was an action item in the memory; the
  repo already operates with a compact-safety-stamps / verbose-
  diagnostics split. The intent is satisfied; the literal field-count
  exercise is not done and is out of scope here.

## E. Files likely involved in this sprint

Read-and-modify candidates (additive only):

- `scripts/signal_inbox_api.py` — add reactor enrichment helper +
  wire into `_decorate_inbox_diagnostics`; add aggregate counts to
  `list_inbox_items`; thread through `get_signal_detail`.
- `scripts/self_test_report.py` — add `_reactor_self_check` + include
  in `build_report` and `build_self_test_summary`.
- `scripts/pre_real_money_preflight.py` — add `signal_reactor`
  subcheck; reactor warns but does not block on its own. Existing
  unreconciled-backlog block remains primary.

Read-only files this sprint:

- `scripts/signal_reactor.py` — already implemented; no change.
- All `frontend/` files — no edits this sprint; frontend test plan
  is a doc-only deliverable.

## F. Tests currently covering each area

- `tests/test_signal_reactor.py` — reactor states, precedence, allowed
  actions.
- `tests/test_signal_reactor_safety_invariants.py` — safety stamps
  locked.
- `tests/test_signal_inbox_api.py` — 8 public ops, plus journal-quality
  paths.
- `tests/test_signal_inbox_bridge.py` — bridge promotions.
- `tests/test_signal_inbox_diagnostics.py` — diagnostics endpoint.
- `tests/test_pre_real_money_preflight.py` — happy path, DB failure,
  security failure, unreconciled thresholds, secret hygiene, safety
  stamps locked, no DB writes, CLI.
- `tests/test_self_test_report.py` + `tests/test_self_test_report_monthly.py`.
- `tests/test_reconciliation_queue.py`.

## G. Tests missing (added by this sprint)

- Reactor enrichment fields appear on inbox items after wiring.
- Reactor enrichment never grants execution permission (re-stamp
  invariant after enrichment).
- Reactor self-check appears in self-test report and in preflight.
- Reactor subcheck in preflight degrades safely when reactor is
  unimportable (no crash; warning).
- Reactor subcheck in preflight cannot unlock execution by itself.

## H. Safe implementation sequence

1. Inbox enrichment helper (`_decorate_with_reactor_diagnostics`) —
   pure, defensive, re-stamps safety on return.
2. Wire helper into `_decorate_inbox_diagnostics` so all inbox flows
   pick it up.
3. Add aggregate `reactor_state_counts` to `list_inbox_items`.
4. Add `_reactor_self_check` to `self_test_report.py` + include in
   `build_report`.
5. Add `signal_reactor` subcheck to `pre_real_money_preflight.py`
   (warning-tier only).
6. Tests for each of the above.
7. Documented frontend test plan + new badges spec for the next
   sprint.

## I. High-risk hallucination zones

- **Fabricating reactor inputs from incomplete inbox-item fields.**
  Inbox items have `priority_score`, `kill_rate_score`,
  `blocker_pressure_score` — not `intensity`, `reliability`,
  `freshness_score`. The enrichment helper must adapt or pass empty,
  not invent missing fields. Reactor degrades to `insufficient_data`
  rather than crashing — preserve this.
- **Preflight inferring blocking from synthetic reactor runs.** If
  the reactor is fed an empty cluster, it returns `COLD_OBSERVE` — a
  perfectly benign state that should *not* light up a blocking issue.
  The subcheck must distinguish "reactor healthy and quiet" from
  "reactor reports real heat on real signals".
- **Conflating thesis vocabulary with trading vocabulary.** The PO /
  COS / WTP material is academic. It must not leak into module names,
  field names, or comments. Continue to use existing engineering
  vocabulary (decision_grade_energy, operator_heat_score, etc.).

## J. Exact Phase 1 implementation plan

### J.1 `signal_inbox_api.py`

Add module-private helper:

```python
def _decorate_with_reactor_diagnostics(item: dict) -> dict:
    """Attach reactor advisory fields to an inbox item. Defensive.

    Adapts an InboxItem-shaped dict to a single-element cluster
    accepted by evaluate_signal_reactor() by mapping fields the inbox
    actually has into reactor-expected names. Missing inputs degrade
    to `insufficient_data` rather than crashing. Re-stamps safety
    invariants on the way out.
    """
```

The helper computes and attaches **only** these new top-level keys
to each inbox-item dict:

- `reactor_state`
- `decision_grade_energy`
- `echo_risk_score`
- `meltdown_risk_score`
- `fusion_validity`
- `fission_branch_clarity`
- `operator_heat_score`
- `gallardo_block`
- `reactor_recommendation`
- `reactor_available`

Wire into `_decorate_inbox_diagnostics` so all flows pick it up.

`list_inbox_items` additionally emits `reactor_state_counts`,
`reactor_gallardo_block_count`, and `reactor_unavailable_count` at
the response level.

`get_signal_detail` benefits transparently via the shared decorator.

No existing field is removed. All advisory stamps are re-applied
after enrichment.

### J.2 `self_test_report.py`

Add `_reactor_self_check()`. It tries to import
`evaluate_signal_reactor`, runs it on a *deterministic synthetic*
cluster and returns:

```python
{
  "available": bool,
  "reactor_state": str,
  "recommendation": str,
  "safety_invariants_ok": bool,
  "import_error": str | None,
}
```

Hooked into `build_report` under key `reactor_self_check`. Also
threaded into `build_self_test_summary` as
`reactor_available` + `reactor_state` (compact).

If the reactor is unimportable, the report still builds; a
limitation tag `reactor_unavailable` is added.

### J.3 `pre_real_money_preflight.py`

Add subcheck #6 `signal_reactor`. The subcheck:

- imports reactor; on failure warns `signal_reactor_unavailable`
  (does NOT block);
- runs reactor on a deterministic synthetic example;
- verifies safety invariants on the returned payload (must remain
  locked); if any invariant is wrong, **this is a blocking issue**
  `reactor_safety_invariant_failed` — that block is correct because
  it means the advisory layer is broken;
- a healthy reactor returning `COLD_OBSERVE` on a synthetic empty
  cluster is normal and NOT a block.

Existing unreconciled-backlog blocking remains untouched and primary.

### J.4 Tests

Additive tests in:
- `tests/test_signal_inbox_api.py` — reactor enrichment present;
  safety invariants survive enrichment; absence of reactor degrades
  safely; aggregate counts shape.
- `tests/test_self_test_report.py` — reactor_self_check key present;
  reports availability; safety invariants OK; limitation tag added
  on absence.
- `tests/test_pre_real_money_preflight.py` — `signal_reactor`
  subcheck present; healthy state does not unlock execution; broken
  invariant adds blocking issue; reactor failure does not crash
  preflight.

### J.5 Frontend

No code changes. Two doc deliverables:

- `docs/recovery/FRONTEND_TEST_PLAN.md` — concrete plan for the
  smallest first Vitest + React Testing Library setup, listing the
  exact components to cover first.
- A list of badges to wire next sprint (see
  `docs/SIGNAL_REACTOR_MODEL.md §10`).
