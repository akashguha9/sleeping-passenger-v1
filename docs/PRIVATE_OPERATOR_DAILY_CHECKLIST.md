# Private Operator Daily Checklist (Sprint 10D)

This is the operator's private checklist. It is not a public guide and
not a sales deck. The intent is to make the daily ritual repeatable
enough that data, paper trades, and reflections accumulate honestly.

> Paired tools:
> - `scripts/local_mvp_audit.py` and `scripts/windows/run_local_mvp_audit.ps1`
> - `scripts/backup_local_state.py` + `scripts/verify_backup.py`
> - `scripts/refresh_live_signals.py` + the 6-hour scheduled task
> - `docs/PRIVATE_RECOVERY_RUNBOOK.md`
> - `docs/PAPER_LEDGER_OPERATING_ROUTINE.md`
> - `docs/OUTCOME_CALIBRATION_GATE.md`

The MVP is **advisory-only**. Nothing in this checklist authorizes a
trade. The execution gate stays LOCKED.

---

## 1. Daily readiness formula

```
Daily_Readiness =
  Fresh_Data
× Source_Health
× Token_Mode_If_Needed
× Learning_Backlog_Awareness
× Safety_Invariants
× Backup_Recent
```

If any critical factor fails, **operate in review-only mode** — do not
record new paper trades, do not attempt outcome reconciliation, just
read what the system says and write a note about what was wrong.

A failed critical factor is any of:
- last refresh > 6 hours ago AND no manual refresh ran since
- core source health label = `unhealthy`
- safety invariants drift (any of the locked stamps not present)
- no successful backup in the last 24 hours
- token mode required but `MVP_API_TOKEN` not set

---

## 2. Morning / pre-session (≈3 minutes)

1. Repo state is clean or you know exactly what is uncommitted.
   ```powershell
   git status --short
   git log --oneline -5
   ```
2. Scheduler last ran within the cadence window.
   ```powershell
   Get-ScheduledTaskInfo -TaskName SleepingPassengerLiveSignalRefresh |
       Select-Object LastRunTime, NextRunTime, LastTaskResult
   ```
   If `LastRunTime` is older than 6 hours, run a manual refresh:
   ```powershell
   .\scripts\windows\run_live_signal_refresh_once.ps1 -WriteMode
   ```
3. Source health is acceptable.
   ```powershell
   python scripts/local_mvp_audit.py --section source_health
   ```
   Treat any `core_health_label` in `{degraded, watch, unhealthy}` as a
   readiness blocker. Do not blame paper outcomes on stale signals.
4. Token mode is set when writes are needed.
   ```powershell
   python scripts/local_mvp_audit.py --section token
   ```
   If the audit reports `mvp_api_token_set: false` and you plan to use
   the manual trade form or reconciliation actions, set it for the
   current PowerShell session:
   ```powershell
   $env:MVP_API_TOKEN = "<paste-from-vault>"
   ```
5. Quick read-only audit pass.
   ```powershell
   python scripts/local_mvp_audit.py
   ```
   Confirm: `safety_invariants=PASS`, `paper_ledger=PASS/WARN`,
   `learning_completeness` block is visible, no `FAIL`.
6. Calibration confidence is honest.
   ```powershell
   python scripts/local_mvp_audit.py --section calibration
   ```
   If `manual_trade_count` < 5, treat all calibration as advisory only.
   See `docs/OUTCOME_CALIBRATION_GATE.md` for the gate rules.
7. Learning completeness backlog is acknowledged.
   ```powershell
   python scripts/local_mvp_audit.py --section learning
   ```
   `learning_incomplete_count` > 0 means there are reconciled rows
   missing thesis / invalidation / lesson — fix those before recording
   new outcomes, otherwise the next reconciliation pass is biased.
8. Safety invariants present.
   - `ADVISORY_ONLY = true`
   - `HUMAN_EXECUTION_REQUIRED = true`
   - `execution_gate = LOCKED`
   - `BROKER_ORDER_PERMISSION = false`
   - `AI_EXECUTION = 0`
   - `broker_api_called = false`
   - `execution_permission = false`
   - `can_execute = false`
   Any drift → stop. Do not record paper trades. Investigate first.
9. Paper ledger file is present and a recent backup exists.
   ```powershell
   Get-ChildItem exports\paper_trade_*.csv
   Get-ChildItem backup_local_state |
       Sort-Object LastWriteTime -Descending |
       Select-Object -First 3
   ```

If steps 1–9 all pass, proceed. Otherwise drop to **review-only mode**.

---

## 3. During signal review (per signal)

1. Refresh live sources if any are stale.
   ```powershell
   .\scripts\windows\run_live_signal_refresh_once.ps1 -WriteMode -Sources "polymarket,newsapi"
   ```
2. Check the source-health badge for each contributing source before
   trusting any signal.
3. Capture the reactor snapshot at decision time, not after.
   - thesis (1–3 lines)
   - invalidation condition
   - horizon
   - entry plan, exit plan, risk note
   - source freshness state at decision time
   - preflight state
4. Do not edit a snapshot after the outcome is known. That is
   lookahead bias and breaks calibration.
5. If you are recording a paper trade row, set:
   - `trade_mode = PAPER`
   - `PAPER_TRADE_ONLY = true`
   - `REAL_CAPITAL_AT_RISK = false`
   - `BROKER_ORDER_ID = "NONE"`
   - `BROKER_API_CALLED = false`
   - `EXECUTION_REAL = false`
6. **Paper outcomes are not alpha proof.** They test workflow
   discipline, classification quality, reactor coverage, and
   lookahead resistance — not edge.

---

## 4. Evening / post-session (≈5 minutes)

1. Backup DB and paper ledger.
   ```powershell
   python scripts/backup_local_state.py
   python scripts/verify_backup.py (Get-ChildItem backup_local_state |
       Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
   ```
2. Reconcile any matured paper outcomes.
   - Mark `outcome_status`, `outcome_quality`, `process_quality`
   - Record `mistake_tags` and `lesson`
   - Set `reconciled_at`
3. Capture lessons even on neutral outcomes.
4. Run the learning-completeness pass.
   ```powershell
   python scripts/local_mvp_audit.py --section learning
   ```
   Aim for `learning_incomplete_count = 0` before bed.
5. Run the calibration gate (Sprint 10F).
   ```powershell
   python scripts/calibration_gate.py
   ```
   Read the status verbatim. Do not extrapolate beyond what the gate
   allows for current sample size.
6. Note operator mistakes in the moltbook / reflection desk. This is
   the only honest output of a single-trader MVP: process feedback.

---

## 5. Weekly (Sundays, ≈15 minutes)

1. Restore drill — pick the latest backup and verify it works:
   ```powershell
   python scripts/verify_backup.py <latest_backup_dir>
   ```
   If FAIL, fix the backup pipeline before anything else.
2. Review which sources failed most often this week. Decide whether to
   raise credentials, lower expectations, or drop the source.
3. Review paper outcomes **only** if `paper_calibration_ready != NOT_READY`.
4. Do not overfit `n < 50` paper outcomes. Repeated process mistakes
   are still valid signal even when edge isn't.
5. Push any code or doc changes.
   ```powershell
   git status --short
   git push origin main
   ```

---

## 6. Review-only mode

Triggered automatically by any failed critical readiness factor in
section 1.

While in review-only mode you may:
- read the UI
- inspect logs and the local audit
- update reflections and the moltbook
- back up data

You may **not**:
- record new paper trades
- run outcome reconciliation
- mark new lessons
- adjust calibration thresholds based on the broken state

Document the readiness blocker. Fix the blocker (typically: refresh
the data, repair a credential, recover a stale source). Re-run section
1. Only then leave review-only mode.

---

## 7. Hard non-negotiables

- The execution gate is LOCKED. Nothing on this checklist unlocks it.
- No broker is contacted by any step.
- No order is placed by any step.
- `.env` is never copied by the backup script and never committed.
- Paper outcomes are operator process data, not real-money proof.
- If a calibration claim ever sounds like "we proved edge",
  that is the bias — reset to the calibration gate's actual state.
