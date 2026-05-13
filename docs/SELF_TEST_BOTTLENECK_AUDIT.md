# Self-Test Bottleneck Audit

> Companion to [DIAGNOSTIC_FRAMEWORK_ROADMAP.md](DIAGNOSTIC_FRAMEWORK_ROADMAP.md),
> [AI_OUTPUT_VALIDATION.md](AI_OUTPUT_VALIDATION.md), and
> [E2E_TEST_PLAN.md](E2E_TEST_PLAN.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

## 0. Verdict

This MVP is **not blocked by missing live trading**. It is blocked by
**proof, discipline, diagnostics, and a closed learning loop**. The
operator's stated plan is to self-test manually for 1–2 years, then
decide whether to showcase. For that plan, what matters is:

1. Can the system *prove* it observed a signal, validated it, and asked
   for a manual decision — without ever pretending to be able to act on
   that decision?
2. Can the system *prove* that a signal was fragile, contaminated, or
   degraded *before* the operator looks at it?
3. Can the system *record* the operator's manual decision in enough
   structural detail to learn from it months later?
4. Can the system *reconcile* the outcome and *attribute* the result to
   skill vs. luck vs. process error?
5. Can the system *survive* a laptop reboot, a power loss, or a corrupt
   DB and still report what it knew when?

Nothing on that list requires hosting, multi-user auth, Postgres, a
broker integration, or paid live APIs. All of it requires diagnostics,
discipline, and evidence collection that the current MVP only *sketches*.

## 1. Solo Self-Test Bottlenecks

Ordered by impact on a 1–2 year manual self-test, not on private-beta
readiness.

| Bottleneck | Current issue | Why it hurts self-testing | Fix in this sprint |
|---|---|---|---|
| Frontend / E2E proof | `frontend/package.json` ships no Vitest, RTL, or Playwright. The `nextBestAction.spec.ts` file is committed but cannot run. Manual smoke walk in DEMO.md is the only frontend safety net. | A green pytest run does not prove the workflow that the operator will actually use every day. | Cannot install tooling without operator approval. Update E2E plan; add pure helper tests that don't need npm. Ask explicitly for approval to install. |
| AI schema not wired everywhere | `scripts/ai_output_schema.py` exists with 28 tests, but `signal_inbox_api.add_ai_discussion_summary` ignores it — raw `summary_text` is persisted, with no validation_status, no secret redaction at the boundary. | Schema that exists but isn't used is documentation, not enforcement. A real AI integration would smuggle credentials into the JSONL log on the first run. | Wrap `add_ai_discussion_summary` and any peer paths through `validate_ai_interpretation_payload`. Add integration tests. |
| No signal sensitivity diagnostic | Roadmap lists chaos-sensitivity as the first P1 diagnostic, but nothing implements it. | The operator has no way to tell whether a signal flipped from REVIEW to BLOCKED on a 1% input perturbation — i.e. whether it is fragile. | Implement `scripts/signal_sensitivity_diagnostics.py` as a pure deterministic helper. |
| No toxic-signal quarantine state | Roadmap names quarantine; no module exists. Signals with high contradiction, low reliability, recycled narrative, or invalid AI output have no distinct state. | The operator will eventually trade off a contaminated signal because nothing labeled it loudly enough. | Implement `scripts/toxic_signal_quarantine.py`. Pure helper first, optional UI tag later. |
| No continuity / degraded mode | Mock / fallback / DB-down states are detectable but not summarised into one continuity signal. Frontend shows individual banners; the operator has no single "system integrity score". | Operator may interpret partial data as canonical and trade off it during a degraded window. | Implement `scripts/continuity_mode.py`. Surface in smoke check and (optionally) /health. |
| Manual decision rationale weakness | `manual_trades` schema captures `thesis` and `notes`. There is no scoring of journal completeness — did the operator record invalidation, horizon, risk reason, exit plan? | After 6 months the operator cannot tell whether a profitable trade was a good decision or a lucky one. | Implement `scripts/self_test_journal_quality.py`. Score dicts. Do not migrate schema. |
| Reconciliation does not classify outcome quality | `reconciliation_results.outcome_status` is one of `WIN/LOSS/BREAKEVEN/UNKNOWN`. There is no separate signal for "process error vs. market noise vs. valid bet that lost". | Operator confuses noise losses with skill failures and over-corrects. | Document the gap; surface in self-test report. Schema migration is out of scope. |
| Moltbook mistake taxonomy thin | `moltbook_entries.mistake_type` exists but is free-text. Repeated mistakes are not aggregated. | Operator cannot see "I made the same mistake 5 times this quarter". | Document in audit; add aggregation to self-test report. |
| Source health truth | `source_run_log` + `source_health` exist; the registry distinguishes implemented/placeholder/planned. Frontend has a SourceHealthPanel. There is no end-to-end "freshness state" surfacing in the report. | Operator may treat a 48-hour-old fallback row as live. | Audit; add to self-test report. Tests already cover most of it. |
| No self-test evidence export | The MVP has CSV exports per surface (manual_trades, reflections, reconciliations). It has no single rollup report. | Operator cannot answer "what does my self-test look like over 30 days" in one command. | Implement `scripts/self_test_report.py`. Read-only against SQLite. |
| No multi-day operational proof | Smoke check is a pre-demo snapshot. Nothing exercises the system across a *week* and proves continuity. | Operator cannot prove the system survives a real test cycle. | Out of scope; add runbook. |
| No Docker build/up proof | `docker compose config` may parse fine but `build && up` is not exercised. | Operator may have a `docker-compose.yml` that is broken without knowing. | Out of scope unless smoke test catches it. |

## 2. Non-Priorities For This Sprint

Explicitly **not** addressed here:

- **Hosting / deployment.** Operator does not want to host.
- **User acquisition.** Operator does not want public users.
- **Private beta auth design.** Operator may build it post-self-test.
- **Postgres migration.** SQLite is fine for solo self-test.
- **Broker execution.** Forbidden. The MVP is advisory-only.
- **Real-money automation.** Forbidden.
- **Public launch / marketing.** Premature.
- **Paid live API expansion.** Not necessary to prove self-test discipline.
- **AI auto-trading.** Forbidden.
- **Frontend e2e auto-install.** Requires explicit operator approval to
  add Vitest / Playwright dependencies.

If any of these are addressed in this sprint, it is *only* because they
fell out of a higher-priority change for free.

## 3. Target Outcome

By the end of this sprint, the MVP should be able to answer with
verifiable evidence:

> "Did my process work, or did I get lucky?"

The bar for "verifiable evidence" is:

1. Every promoted signal has a sensitivity diagnostic recording its
   chaos sensitivity and classification stability.
2. Every promoted signal has a toxic-quarantine state, even if that
   state is `clean`.
3. Every degraded-system event is labelled with a continuity mode and a
   reason — not just an individual banner.
4. Every AI summary persisted carries a `validation_status` and goes
   through the secret-redaction boundary.
5. Every manual trade can be scored for journal completeness against a
   `Learning_Readiness` formula.
6. The operator can run one command and get a rolling self-test report
   with counts, distributions, and limitations — no PnL claims unless
   they are operator-entered and explicitly marked manual.

The bar is **not**:

- A profitable equity curve.
- A live trading system.
- A SaaS.
- A finished product.

It is a disciplined local advisory machine that *teaches the operator
whether their process is real* over months and years.

## 4. Out-of-Scope, Documented for Later

These are listed here only so the next operator does not re-derive
them:

- Distribution shift diagnostic (P1, after sensitivity).
- Amplification pathway scoring (P1).
- Signal rhythm / arrhythmia (P2; needs months of data).
- Frontend e2e auto-install (requires approval).
- AI eval harness with calibration dataset (post-private-beta).
- Multi-user isolation (post-self-test-profitability).

## 5. Glossary

- **Local self-test**: operator-only manual operation of the MVP, with
  no public users, no broker execution, and no real-money automation.
- **Continuity mode**: a single label for the operator that summarises
  whether the system is in NORMAL, DEGRADED_ADVISORY, or
  CONTINUITY_SAFE_ADVISORY state.
- **Toxic quarantine state**: a state for a signal that is too
  contaminated to promote to the human-review queue without explicit
  override.
- **Learning_Readiness**: a multiplicative scoring of whether a manual
  trade record carries enough structural detail (thesis × invalidation
  × horizon × risk_rationale × outcome_log × reflection) for the
  operator to learn from it later.
