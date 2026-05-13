# Local Self-Test Runbook

> Companion to [SELF_TEST_BOTTLENECK_AUDIT.md](SELF_TEST_BOTTLENECK_AUDIT.md),
> [AI_OUTPUT_VALIDATION.md](AI_OUTPUT_VALIDATION.md), and
> [DIAGNOSTIC_FRAMEWORK_ROADMAP.md](DIAGNOSTIC_FRAMEWORK_ROADMAP.md).
>
> `advisory_status = ADVISORY_ONLY` · `execution_gate = LOCKED` ·
> `broker_api_called = false` · `ai_execution_count = 0` ·
> `execution_permission = false` · `can_execute = false`

This runbook is for the **solo operator** who plans to self-test the
MVP for 1–2 years before deciding whether to showcase, host, or open
to private beta. It is not for public users. It is not for traders
looking for automated execution. It is not a product manual.

The MVP is an advisory signal review, reflection, manual decision,
manual trade logging, reconciliation, and learning journal. It does
not place trades. It does not call brokers. It never will, under any
sequence of clicks.

---

## 0. The single rule

> **Perception is not permission.**
>
> The MVP can show you many things. None of them grant you authority
> to act. Every trade is a manual decision made by you, logged by you,
> reconciled by you, and learned from by you.

---

## 1. Daily routine (≈ 10 minutes)

Run these commands from the repo root.

```powershell
# 1. Preflight: backend reachable, advisory safety stamps intact, DB available
python scripts/smoke_check.py

# 2. Refresh plan dry-run — does NOT call any live API
python scripts/run_live_refresh.py --source all --plan-only --json
```

Then open the dashboard:

```powershell
cd frontend
npm run dev
```

Walk this loop in the UI:

1. **Signal Inbox** — review the new signals. Mark each as `watchlist`,
   `human_review`, or `rejected`. **Do not skip this step.** A signal
   that never gets a decision is a hole in your self-test record.
2. **Reflection desk** — for any signal that survived to
   `human_review`, write a short reflection (why does this matter?
   what would falsify it?). Save it.
3. **AI summary** (optional) — if you generated one through the API,
   the schema validator (`validate_ai_interpretation_payload`) ensures
   the payload is structured and stamped. Read the
   `validation_status` field on the response; a status of `partial` or
   `invalid` is a smell.
4. **Manual trade log** — if you place a trade *outside* the system
   (because you must — the MVP does not trade for you), come back and
   log it here. Fill in:
   - thesis
   - invalidation level (a price or a condition)
   - expected horizon
   - position size
   - risk reason
   - exit plan
   - confidence before
   - emotional state
   - source references
   
   Sparse logs destroy learnability later. See §6.
5. **Reconciliation** — when the trade closes (broker-side, by your
   hand), come back and reconcile. Record actual fill, quantity,
   outcome status (`WIN` / `LOSS` / `BREAKEVEN` / `UNKNOWN`), and a
   short outcome note.
6. **Moltbook** — within 24 hours of closing the trade, write the
   mistake-type tag and the lesson learned. Even on wins. Especially
   on wins that felt lucky.

End the day with:

```powershell
python scripts/self_test_report.py
```

Read the report. Notice what is missing — unreconciled trades,
missing reflections, source health degraded. Fix it tomorrow.

---

## 2. Weekly routine (≈ 30 minutes)

Once a week, run a full evidence sweep:

```powershell
# Pytest — all backend invariants
python -m pytest tests -q

# Self-test rollup
python scripts/self_test_report.py --json > runtime/self_test_report_week.json
python scripts/self_test_report.py --markdown docs/SELF_TEST_REPORT.md
```

Back up the DB (the daily backup script if you wired one up, or
manually):

```powershell
python scripts/backup_db.py
```

Inspect:

- `journal_quality.average_learning_readiness` — is it trending up?
- `journal_quality.factor_pass_rates` — which factor are you
  consistently missing? (Almost always: `invalidation` or
  `reflection`.)
- `reconciliation.outcome_distribution` — is `UNKNOWN` going down?
- `moltbook.mistake_type_distribution` — are you logging the same
  mistake twice?
- `source_health.per_source` — any source stuck on `FAIL` or with
  `OK` older than 12 hours? Restart that adapter manually.

---

## 3. Monthly routine (≈ 60 minutes)

Once a month, do an honest review:

1. Read your last 30 days of Moltbook entries. Group by `mistake_type`.
   Pick the top three.
2. For each top-three mistake, write a one-line "rule" you will follow
   for the next 30 days. Add it to your personal trading rules
   document — **not** to the code. The code does not enforce rules;
   you do.
3. Check `journal_quality.factor_pass_rates`:
   - If `reflection` < 0.6 → you are not closing the loop. Force
     yourself to write a Moltbook entry within 24 hours of every trade
     close for the next month.
   - If `invalidation` < 0.6 → you are entering trades without exit
     plans. Refuse to log a trade without an `exit_plan` field.
4. Run the sensitivity diagnostic on a *sample* of last month's
   signals:

   ```powershell
   python scripts/signal_sensitivity_diagnostics.py --json path/to/sample.json
   ```

   Count fragile signals. If > 30% of promoted signals were fragile,
   you are over-promoting noisy data. Tighten your inbox triage.

---

## 4. Quarterly routine (≈ 2 hours)

Once a quarter, ask the hard question:

> **Did my process work, or did I get lucky?**

To answer it honestly, look at:

- `reconciliation.outcome_distribution`: WIN/LOSS ratio over the
  quarter. Compare against a random-walk null model. If you cannot
  beat random, your process is not yet validated.
- `journal_quality.average_learning_readiness`: was it ≥ 0.70 across
  most trades? If not, your evidence base is too thin to draw any
  conclusion about skill vs. luck.
- `moltbook.mistake_type_distribution`: are repeated mistakes
  decreasing in count quarter-over-quarter? If not, you are not
  actually learning — you are journaling.
- Trade outcomes vs. signal sensitivity at decision time. If your
  losses cluster on `fragile_watchlist` signals you promoted anyway,
  that is a process error.

If after four quarters the answer is still ambiguous, **do not
showcase**. Self-test for another year. The MVP can wait.

---

## 5. What to do when the system degrades

Symptoms:

- `scripts/smoke_check.py` returns FAIL.
- `/health` shows `db_available=false`.
- Inbox shows `MOCK_FALLBACK` or `legacy_fabric` instead of `sqlite`.
- Multiple sources stuck on `FAIL` for > 6 hours.
- AI summaries returning `validation_status="invalid"` for the third
  time in a row.

Steps:

1. Run `python scripts/smoke_check.py` and read the failing check.
2. If `db_available=false` → check `runtime/mvp_local.db` exists and
   is not zero bytes. If lost, restore from your most recent
   `python scripts/backup_db.py` snapshot.
3. If source health is degraded → check `runtime` logs and the
   source's last `error_message` via the freshness endpoint.
4. If AI validation is consistently invalid → the upstream model or
   adapter is misbehaving. Stop relying on AI summaries until fixed;
   the rest of the workflow does not require them.

**While degraded, do not log new manual trades.** A trade record that
cannot be persisted is a process violation.

Continuity-mode diagnostic (`scripts/continuity_mode.py`) summarises
all of this into one of three states:

- `NORMAL` — proceed.
- `DEGRADED_ADVISORY` — proceed with caution; double-check sources.
- `CONTINUITY_SAFE_ADVISORY` — review-only; stop logging manual
  trades.

`allowed_actions["execute_broker_order"]` is **always** `False`,
regardless of mode. The MVP cannot trade; degradation only changes
what you should *trust*.

---

## 6. The discipline that makes this useful

Self-testing only works if you respect the journal. The MVP cannot
force you. The runbook can only remind you.

Three commitments:

1. **No trade without a logged thesis and invalidation.** If you cannot
   write down what would prove you wrong, you are gambling, not
   testing.
2. **No reconciliation without an outcome status.** `UNKNOWN` is a
   real outcome status — use it deliberately, not lazily.
3. **No skipped Moltbook entry on a closed trade.** The closure of a
   trade is the start of learning, not the end of work.

If you cannot maintain those three for a month, the MVP is not the
problem. Stop self-testing until you can.

---

## 7. What this runbook does **not** cover

- **Hosting / deployment.** Out of scope. The MVP is local-first.
- **User onboarding.** There are no users besides you.
- **Broker execution.** The MVP does not place trades. There is no
  configuration that turns this on. There is no module to import that
  enables it.
- **Real-money automation.** Same.
- **AI auto-trading.** Same. AI outputs are advisory and validated
  against `scripts/ai_output_schema.py`; they cannot escalate into
  authority.

If you ever find yourself adding any of the above, you have left the
self-test phase. Re-read [SELF_TEST_BOTTLENECK_AUDIT.md](SELF_TEST_BOTTLENECK_AUDIT.md)
and decide whether you have earned that transition with evidence.

---

## 8. Quick-reference command list

```powershell
# Preflight
python scripts/smoke_check.py
python scripts/run_live_refresh.py --source all --plan-only --json

# Run dashboard
cd frontend
npm run dev

# Self-test report
python scripts/self_test_report.py
python scripts/self_test_report.py --json
python scripts/self_test_report.py --markdown docs/SELF_TEST_REPORT.md

# Backup
python scripts/backup_db.py

# Test suite
python -m pytest tests -q

# Diagnostic dry-runs (no DB writes)
python scripts/signal_sensitivity_diagnostics.py --example
python scripts/signal_sensitivity_diagnostics.py --json path/to/signal.json
```

Nothing in this list calls a broker. Nothing in this list executes a
trade. Nothing in this list grants execution permission anywhere in
the system. That is the point.
