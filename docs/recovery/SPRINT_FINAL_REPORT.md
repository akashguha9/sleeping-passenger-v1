# Recovery Sprint Final Report — Claude Data MVP Gap Wiring

Branch: `recovery/claude-data-mvp-gap-wiring`
Date: 2026-05-14

## 1. Executive verdict

Signal Reactor is now operationally wired into the daily operator
surfaces — Signal Inbox API, Self-Test Report, and Pre-Real-Money
Preflight — while preserving every advisory-only safety invariant. The
existing 3451-test suite grew to **3464 tests, all passing** (+13 new,
zero regressions). No broker call was introduced. No auto-execution.
No frontend stack destabilisation. Thesis material from the Claude
export was identified and quarantined — none of it leaked into
trading code.

The visible operator gain: every inbox item now carries reactor state,
decision-grade energy, echo / meltdown / heat scores, fusion validity,
fission clarity, gallardo block, and a reactor recommendation — and
list responses carry aggregate counts per reactor state. The preflight
gains a sixth diagnostic subcheck that catches reactor-layer safety
regressions. Self-test gains a reactor self-check section.

## 2. Claude export / project ingestion findings

- Export root: `C:\Users\akash\Downloads\Claude Data\`.
- `conversations.json` is one 71 MB JSON line (single conversation
  stream). Contains the phrase "Zero-backend system architecture
  blueprint" exactly once. Not imported into the repo.
- `projects/01962ad6-…json` — the user's "//Sleeping Passenger" project.
  `docs: []` — no project-knowledge documents attached at export time.
- `projects/01962ad3-…json` — "How to use Claude" starter, irrelevant.
- `memories.json` — the **primary blueprint distillation**: 13 doctrine
  principles, LEAVE default, ATOM 35-core / 95-full dual-layer, spot
  longs only, 10% stop, paper-trading phase, CHAOS_ENTRY tracking.
- Sanitized summary: `docs/recovery/ZERO_BACKEND_CLAUDE_PROJECT_RECOVERY_SUMMARY.md`.

## 3. What was found in "Zero-backend system architecture blueprint"

The literal Claude *Project* with that name does not exist as a
discrete entity in the export — the user's MVP project has no docs
attached, and the phrase appears only inside the 71 MB conversation
stream as a chat reference.

The closest authoritative blueprint that DOES exist is twofold:

1. `memories.json` → project_memories → `01962ad6-…`. Contains the
   distilled doctrine, ATOM architecture, sourcing stack, and current
   paper-portfolio status.
2. `docs/SIGNAL_REACTOR_MODEL.md` in this repo — the doctrine, formulae,
   architecture diagram, translation table from reflection vocabulary
   to engineering vocabulary, and safety invariants.

Together these are the load-bearing specifications. The repo's source
code already implements ~all of the blueprint's load-bearing pieces;
the gap was operational *wiring*, which this sprint closes.

## 4. What was ignored from thesis / co-creation data and why

Quarantined material (NOT touched in code this sprint):

- The user's master's thesis at EBS on **psychological ownership (PO)
  as mediator between consumer outcome-shaping (COS) and willingness
  to pay (WTP)** — academic research, not a trading-system spec.
- Thesis quality scores, methodology debates, randomisation arguments,
  manipulation checks, PROCESS Model 4 bootstrapping, Jamovi/Excel
  workflow notes, 26-paper literature-mapping spreadsheet, gap
  analysis document.

Reason: thesis material is conceptual / academic. Injecting it into
trading code would conflate two unrelated systems. It is permissible
later only as documentation language or product-positioning notes,
never as backend logic, data schema, or frontend behaviour. Section D
of the recovery summary captures the exclusion explicitly.

## 5. Files changed

Code:

- `scripts/signal_inbox_api.py` — added `_inbox_item_to_reactor_signal`,
  `_decorate_with_reactor_diagnostics`, hooked reactor enrichment into
  `_decorate_inbox_diagnostics`, added `reactor_state_counts`,
  `reactor_gallardo_block_count`, `reactor_unavailable_count` to the
  `list_inbox_items` response envelope. Backward-compatible: no field
  removed; safety invariants re-stamped after enrichment.
- `scripts/self_test_report.py` — added `_reactor_self_check()`,
  threaded the result into `build_report` (key `reactor_self_check`)
  and `build_self_test_summary` (compact `reactor_available`,
  `reactor_state`, `reactor_safety_invariants_ok`), Markdown rendering
  now includes a "Signal Reactor Self-Check" section, new limitation
  tags `signal_reactor_unavailable` and
  `signal_reactor_safety_invariant_failed`.
- `scripts/pre_real_money_preflight.py` — added a sixth subcheck
  `signal_reactor`. Warning-tier if reactor is unimportable.
  *Blocking-tier* (`signal_reactor_safety_invariant_failed`) only if
  the reactor returns a broken safety contract — that block is correct
  because the advisory layer is then broken. Unreconciled-backlog
  block remains primary.

Docs:

- `docs/recovery/ZERO_BACKEND_CLAUDE_PROJECT_RECOVERY_SUMMARY.md` (new)
- `docs/recovery/FORENSIC_GAP_ANALYSIS.md` (new)
- `docs/recovery/FRONTEND_TEST_PLAN.md` (new)
- `docs/recovery/SPRINT_FINAL_REPORT.md` (this file, new)

Tests:

- `tests/test_signal_reactor_wiring.py` (new, 13 tests)

No frontend code was modified. No new package was installed.

## 6. Signal Reactor wiring completed

- **Inbox**: every inbox item is now enriched with `reactor_state`,
  `decision_grade_energy`, `echo_risk_score`, `meltdown_risk_score`,
  `fusion_validity`, `fission_branch_clarity`, `operator_heat_score`,
  `gallardo_block`, `reactor_recommendation`, `reactor_available`.
  `list_inbox_items` exposes per-state aggregate counts.
  `get_signal_detail` benefits transparently via the shared decorator.
- **Self-test**: report carries `reactor_self_check` block; summary
  carries `reactor_available` + `reactor_state` +
  `reactor_safety_invariants_ok`.
- **Preflight**: new `signal_reactor` subcheck. Healthy reactor on a
  synthetic empty cluster → ok=True with reactor_state=COLD_OBSERVE.
  Broken invariants → adds blocking issue
  `signal_reactor_safety_invariant_failed`. Unimportable reactor →
  warning only.
- **Safety**: every wiring point re-stamps `advisory_status=ADVISORY_ONLY`,
  `execution_gate=LOCKED`, `broker_api_called=False`,
  `ai_execution_count=0`, `execution_permission=False`,
  `can_execute=False`. Verified by new tests.

## 7. Reconciliation backlog improvements completed

Inspection-only. The reconciliation queue stack is already mature:

- `scripts/reconciliation_queue.py` lists unreconciled trades with
  per-trade journal completeness, learning_readiness, missing fields,
  age in days, and aggregate breakdowns by ticker / emotional_state /
  expected_horizon.
- `scripts/pre_real_money_preflight.py` already blocks at
  `UNRECONCILED_BLOCK_THRESHOLD=25` and adds full-review block at
  `UNRECONCILED_FULL_REVIEW_THRESHOLD=50`, with warning tier at 10.
- `frontend/src/app/reconciliation/page.tsx` already shows the live
  backend queue (unreconciled count, oldest age, avg journal
  completeness, learning-ready count, most-missing fields).
- `scripts/signal_inbox_api.py` already records the operator-discipline
  fields (`outcome_quality`, `process_error`, `process_error_notes`,
  `mistake_tags`, `lesson`) on reconciliation.

No additive backend changes were needed. The remaining gap is purely
UI:

- `frontend/src/app/reconciliation/page.tsx` still uses
  `MOCK_RECONCILIATIONS` for the "Reconciled" list panel — a real
  backend wire would replace that mock with `list_manual_trades` +
  `reconciliation_results`. Deferred; not in scope here.

## 8. Frontend proof improvements completed

Inspection-only and a documented plan. `frontend/package.json`
declares no test runner; only Next.js internal `*.test.*` files exist
inside `node_modules`. Installing a runner is a *new dependency* with
TypeScript + path-alias + JSDOM config implications. The safer path
for this recovery sprint was:

- `docs/recovery/FRONTEND_TEST_PLAN.md` — concrete next-sprint plan
  with the exact `npm install -D` command, the minimal
  `vitest.config.ts`, the priority-ordered list of components to
  cover first, and the safety-assertion pattern that mirrors the
  backend's AST checks.
- Reactor-badge spec (already in the same doc) for the next sprint to
  wire the new payload fields to UI badges.

## 9. Tests added / updated

`tests/test_signal_reactor_wiring.py` — 13 new tests, all passing:

| # | Test | Concern |
|---|---|---|
| 1 | `test_decorate_with_reactor_diagnostics_attaches_required_fields` | 10 reactor keys appear on enriched item |
| 2 | `test_decorate_with_reactor_diagnostics_reports_valid_state` | reactor_state ∈ canonical set; reactor_available True |
| 3 | `test_decorate_with_reactor_diagnostics_preserves_safety_invariants` | invariants locked even on aggressive inputs |
| 4 | `test_decorate_with_reactor_diagnostics_handles_empty_input` | empty dict → valid state, no execution permission |
| 5 | `test_decorate_with_reactor_diagnostics_degrades_when_reactor_missing` | reactor failure does not crash and does not unlock execution |
| 6 | `test_list_inbox_items_exposes_reactor_counts` | new aggregate counts present and total to item count |
| 7 | `test_list_inbox_items_every_item_carries_reactor_fields` | per-item reactor fields + invariants |
| 8 | `test_self_test_report_contains_reactor_self_check` | report has `reactor_self_check` block |
| 9 | `test_self_test_summary_bubbles_reactor_fields` | summary has reactor_available + reactor_state + invariants |
| 10 | `test_self_test_report_markdown_renders_reactor_section` | Markdown rendering includes the new section |
| 11 | `test_preflight_includes_signal_reactor_subcheck` | subcheck present, safety_invariants_ok True |
| 12 | `test_preflight_signal_reactor_does_not_unlock_execution` | reactor pass keeps advisory stamps locked |
| 13 | `test_preflight_reactor_does_not_override_backlog_block` | backlog block remains primary |

No existing test was modified.

## 10. Commands run and exact results

```
> python -m py_compile scripts/signal_inbox_api.py scripts/self_test_report.py scripts/pre_real_money_preflight.py
(no output → success)

> python -m compileall scripts tests
(no errors → all .py files compile)

> python -m pytest tests/test_signal_inbox_api.py tests/test_self_test_report.py tests/test_pre_real_money_preflight.py tests/test_signal_reactor.py tests/test_signal_reactor_safety_invariants.py -q
82 passed in 7.39s
(target-module tests pass after wiring)

> python -m pytest tests/test_signal_reactor_wiring.py -q
13 passed in 4.45s
(all new tests pass)

> python -m pytest tests -q
3464 passed in 201.46s
(full suite green; previous baseline 3451; net +13)
```

Frontend commands skipped per the test plan above. `next build` and
`next lint` were not invoked because no frontend source was modified.

## 11. Updated segmented scorecard with deltas

Evidence-type legend:
- `code` — implementation change
- `test` — test added or already covering
- `UI` — user-visible frontend change
- `doc` — documentation only
- `0` — no change

| # | Segment | Previous After /10 | New After /10 | Delta | Evidence Type | Meaning |
| -: | --- | ---: | ---: | ---: | --- | --- |
| 1 | Product clarity | 9.1 | 9.2 | +0.1 | doc | Recovery summary + forensic gap analysis make the spec→code mapping explicit. |
| 2 | Architecture | 8.3 | 8.4 | +0.1 | code | Reactor is now an integration boundary, not a standalone island. |
| 3 | Frontend quality | 7.9 | 7.9 | 0.0 | 0 | No frontend code change. Plan exists for next sprint. |
| 4 | Backend/API quality | 8.6 | 8.9 | +0.3 | code+test | Reactor wired into inbox API + self-test + preflight; backward-compatible. |
| 5 | Data model & persistence | 8.5 | 8.5 | 0.0 | 0 | No schema or persistence changes. |
| 6 | Auth/authorization | 4.5 | 4.5 | 0.0 | 0 | Untouched by design. |
| 7 | Security floor | 8.4 | 8.5 | +0.1 | test | New invariant tests prove enrichment cannot unlock execution; preflight gains a reactor safety-contract block. |
| 8 | Configuration/environment | 8.3 | 8.3 | 0.0 | 0 | No config/env work. |
| 9 | Testing | 9.2 | 9.3 | +0.1 | test | +13 tests; total now 3464 passing (was 3451). |
| 10 | Error handling/resilience | 8.1 | 8.3 | +0.2 | code+test | Reactor enrichment degrades safely on import / eval failure; preflight reactor subcheck distinguishes "unavailable" from "broken invariant". |
| 11 | Observability/debugging | 8.6 | 8.8 | +0.2 | code | Inbox responses now expose reactor_state_counts and per-item reactor fields; self-test report shows reactor self-check; preflight shows reactor state. |
| 12 | Deployment readiness | 6.0 | 6.0 | 0.0 | 0 | Not touched. |
| 13 | Performance/scalability | 4.0 | 4.0 | 0.0 | 0 | Not touched. |
| 14 | UX/workflow | 8.5 | 8.5 | 0.0 | 0 | No UI integration yet. Payload is now ready for the UI to pick up. |
| 15 | Code quality/maintainability | 7.8 | 7.9 | +0.1 | code | New helpers are small, pure, single-purpose; existing AST checks remain valid. |
| 16 | Documentation/onboarding | 9.8 | 9.9 | +0.1 | doc | Four new docs under docs/recovery/. |
| 17 | AI/API integration readiness | 7.6 | 7.6 | 0.0 | 0 | No AI integration changes. |
| 18 | Live source refresh discipline | 8.1 | 8.1 | 0.0 | 0 | Not touched. |
| 19 | Business/MVP viability | 6.5 | 6.5 | 0.0 | 0 | No external/customer-facing movement. |
| 20 | Legal/privacy/compliance | 6.7 | 6.7 | 0.0 | 0 | No legal/privacy change. |
| 21 | Overall local showcase MVP | 8.7 | 8.8 | +0.1 | code+test | Reactor visibility on the wire, but not yet on screen. |
| 22 | Local self-test readiness | 8.6 | 8.8 | +0.2 | code+test | Self-test report now surfaces reactor health; new limitation tags. |
| 23 | Pre-real-money local operating readiness | 7.8 | 8.1 | +0.3 | code+test | Preflight gains reactor safety-contract guard; unreconciled-backlog block remains primary. |
| 24 | Signal reactor / adaptive routing discipline | 8.0 | 8.5 | +0.5 | code+test | Reactor moved from "callable manually" to "wired into 3 operator surfaces" with safety invariants verified. Calibration on real data still pending; that's why it's not 9.0+. |

Scores only moved where code + tests + (optional) UI evidence support
the move. Scores were *not* inflated for "we added a module" — only
for "we added a module, tests cover it, and the operator can see the
output". UX/workflow (3) and Frontend quality (3) stayed flat because
no UI change actually shipped.

## 12. Remaining blockers

To go from "local showcase" to "ready for real money", in priority
order:

1. **Frontend reactor badges.** Backend payload is ready; UI needs
   `ReactorStateBadge`, decision-grade-energy meter, gallardo-block
   callout, reactor-unavailable cue. Spec is in
   `docs/recovery/FRONTEND_TEST_PLAN.md`.
2. **Frontend test framework.** None installed; plan + minimal config
   ready to land next sprint.
3. **Reconciliation page real-data wire.** Frontend page still uses
   MOCK_RECONCILIATIONS for the "Reconciled" panel — replace with
   `list_manual_trades` joined with `reconciliation_results`.
4. **Reactor calibration on real outcomes.** Thresholds in
   `signal_reactor.py` are doctrine-derived, not empirically tuned.
   Cannot calibrate until enough real-money or paper-trade outcomes
   have been logged and reconciled.
5. **Real-source data flowing through inbox.** When inbox carries a
   sparse priority/persistence/contamination profile, the reactor
   degrades to COLD_OBSERVE on most items. This is honest output but
   becomes more useful when richer field mappings (direction,
   reliability, freshness, narrative_intensity) are populated by the
   sourcing layer.
6. **Long-tail thesis decisions** (separating thesis vocabulary from
   trading vocabulary on positioning docs). Out of scope here.

## 13. Next safest implementation phase

Pick exactly one of the following for the next sprint. They are
roughly equal in size, all surgical, none destabilising:

- **Phase 2A — Frontend reactor badges + the smallest first
  Vitest/RTL test.** Highest "operator visibility per line of code".
  Spec already written. Risk: low.
- **Phase 2B — Reconciliation page real-data wire.** Replaces the
  remaining mock with the existing backend list endpoints. Risk: low.
- **Phase 2C — Richer reactor input mapping in the inbox bridge.**
  Have the sourcing layer populate `direction`, `freshness_score`,
  `narrative_intensity`, `market_confirmation` on inbox items so the
  reactor produces more discriminating states. Risk: medium (changes
  the bridge's contract slightly).

Recommended: **Phase 2A** — it converts the work already on the wire
into operator-visible signal, and a small frontend test framework
unlocks the rest of the frontend proof gap.

---

## Cross-cutting safety statement (re-asserted)

All wiring in this sprint:

- preserves `advisory_status == "ADVISORY_ONLY"`
- preserves `execution_gate == "LOCKED"`
- preserves `broker_api_called == False`
- preserves `ai_execution_count == 0`
- preserves `execution_permission == False`
- preserves `can_execute == False`

The Signal Reactor remains a *diagnostic* layer that produces labels,
not orders. Human execution is the only execution path.
