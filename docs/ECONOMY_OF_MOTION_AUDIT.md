# Economy of Motion Audit

## Purpose

"It is not daily increase but daily decrease — hack away the unessential."
MVP quality is *useful signal minus ornamentation*, not feature count. This
audit (`scripts/economy_of_motion_audit.py`) measures system sharpness and
names removal candidates, reusing the existing release-gate audits so the
numbers cannot drift.

## Inputs

Read-only from:
* `runtime_truth_purity_audit` → mock pollution (un-quarantined fake rows) and
  quarantined-rows-excluded.
* `broken_windows_report` → stale sources.
* `closed_loop_learning_audit` → unreconciled trades (redundant motion).

Useful-signal proxy = clean canonical rows = `total_rows_scanned - fake -
quarantined` (the operator-truth surface, not the raw multi-thousand signal
ledger).

## Formula

```
EconomyScore = 10 * UsefulSignals /
    max(UsefulSignals + Redundant + Decorative + Stale + MockPollution
        + DuplicateDiagnostics, 1)

SystemSharpness = UsefulDiagnostics - DecorativeComplexity - StaleDataDebt
                  - DuplicateSignalDebt - MockPollutionPenalty
```

## Outputs

`economy_score`, `system_sharpness`, `useful_signal_count`,
`redundant_signal_count`, `decorative_signal_count`, `stale_signal_count`,
`mock_pollution_count`, `duplicate_diagnostic_count`,
`recommended_removal_candidates`, `release_gate_impact`,
`quarantined_rows_excluded`.

## State consequence

`release_gate_impact`: **BLOCK** when mock pollution (un-quarantined fake rows)
> 0 — poison in canonical truth. **WARN** for hygiene debt (stale, redundant,
duplicate, decorative). **CLEAR** when only useful signal remains. Quarantined
rows are *not* debt — they have already been hacked away from active truth.

## Tests

`tests/test_economy_of_motion_audit.py` — formula, mock pollution BLOCKs while
quarantine does not, all-useful is perfect, build_audit on clean vs polluted
DBs, advisory stamps.

## Failure modes

* Missing DB → counts default to 0; gate state derives from the upstream
  audits' fail-closed behaviour.
* A newly leaked (un-quarantined) fake row immediately flips the gate to BLOCK.

## Advisory-only safety note

Read-only; deletes nothing; no broker calls. `release_gate_impact` is human
guidance, not an execution control.

## How to verify locally

```powershell
python scripts\economy_of_motion_audit.py
python scripts\economy_of_motion_audit.py --json
python -m pytest tests\test_economy_of_motion_audit.py -q
```
