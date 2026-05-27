# Test Inventory

**Sprint:** proof_loop_hardening_sprint, Phase 11.

The repo collects thousands of tests.  Quantity is not value.  This
doc and the inventory script define which tests are *load-bearing* for
the proof loop and which are cosmetic.

> **6,267 tests collected** is a number, not an argument.  Without
> marker tagging, you can't tell which tests are protecting an
> invariant and which are snapshot tests that will pass even when the
> system regresses.

## Marker taxonomy (pytest.ini)

| Marker | Protects |
|---|---|
| `safety_floor` | advisory-only / no-execution / no-secrets / no-broker invariants |
| `reliability` | freshness, persistence, scheduler, watchdog, provider failures, retry, backup/restore |
| `calibration` | calibration corpus, Brier/ECE/MCE/log loss, N_real, fixture exclusion |
| `moltbook` | reconciliation learning, contamination rejection, idempotency, open-trade blocking |
| `frontend_truth` | UI truthfulness (advisory-only, mock/live/stale/degraded, no execution language) |
| `cosmetic` | snapshot / shape tests that do not protect a major invariant |

New tests landing in this sprint use explicit markers.  Legacy tests
are classified by filename heuristic in
`scripts/test_inventory_report.py` until they are migrated.

## Honest limitations

- The heuristic is filename-based.  A test named `test_misc.py` would
  land in `cosmetic_or_unknown` even if it actually pins a safety
  invariant.  This is intentional: the unknown bucket is loud so it
  can't hide.
- The script does NOT execute tests.  It classifies files.
- `pytest -m "safety_floor"` is the *authoritative* selector once
  markers are in place; the inventory is for triage, not for
  execution gating.

## Running

```powershell
python scripts/test_inventory_report.py --json
```

Example shape:

```
test inventory: total=420 safety=80 reliability=120 calibration=20 ...
```

## Where this fits in the evidence bundle

`docs/EVIDENCE_BUNDLE.md` references the marker counts when computing
testing-segment scores.  A high `unknown_pct` decays the
`Testing/CI` segment toward its evidence ceiling.
