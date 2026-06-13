# Advisory runner — operator quickstart (PowerShell)

The Mythos→Fable advisory loop. **Advisory-only. No real-money execution path.
No writes by default.** Every output is stamped `advisory_status=ADVISORY_ONLY`
and `real_money_execution=PROHIBITED`.

All commands below are Windows PowerShell. The runner reads observations from a
JSON file and never touches the network.

## 1. Run the built-in demo (synthetic, never calibration-eligible)

```powershell
python -m scripts.signal_arbitrage.advisory_runner --demo
```

`--demo` forces `source_type=SYNTHETIC_FIXTURE`, so a demo capture can never
become a calibration record.

## 2. Run a real advisory from a sample observation file (read-only)

```powershell
python -m scripts.signal_arbitrage.advisory_runner --observations examples/mythos_observations/reality_up_narrative_down.json
```

This is the canonical `REALITY_UP_NARRATIVE_DOWN` cluster: one thesis
corroborated across three distinct ecologies, so it clears corroboration and
routes to Fable 5 (`pre_scoring_decision=ROUTE_TO_FABLE5`). Nothing is written.

## 3. Check calibration-corpus readiness (read-only)

```powershell
python -m scripts.signal_arbitrage.advisory_runner --check-corpus --capture-path data/calibration_corpus/decisions.jsonl
```

If the file does not exist (the default state — it is gitignored runtime data),
you get `status=NO_CORPUS_FOUND`. Once captures accumulate, the status follows
the eligibility ladder: `CAPTURE_STARTED_NO_LABELS` → `PROVISIONAL_DIAGNOSTIC_READY`
(≥10) → `FIRST_PASS_CALIBRATION_READY` (≥30) → `STRONGER_CALIBRATION_READY` (≥100),
counting only resolved, feature-bearing, non-synthetic records.

## 4. Capture a real decision into the local corpus (opt-in, explicit write)

Capture is **off** unless you explicitly enable it. To turn it on for a session:

```powershell
$env:SIGNAL_CAPTURE_DECISIONS = "1"
$env:SIGNAL_CAPTURE_MODE      = "write"
$env:SIGNAL_CAPTURE_PATH      = "data/calibration_corpus/decisions.jsonl"

python -m scripts.signal_arbitrage.advisory_runner --observations examples/mythos_observations/reality_up_narrative_down.json
```

Reruns of the same decision are deduped by `decision_id`, so the corpus is not
polluted. The capture file is **gitignored** — it is local runtime data, never
committed (committing it would inject non-canonical rows into the corpus).

Equivalent flags-only form (no env):

```powershell
python -m scripts.signal_arbitrage.advisory_runner `
  --observations examples/mythos_observations/reality_up_narrative_down.json `
  --capture-decisions --capture-mode write `
  --capture-path data/calibration_corpus/decisions.jsonl
```

To compute the snapshot without writing anything, use `--capture-mode dry_run`
(the CLI default even when `--capture-decisions` is set).

### Reset the capture environment

```powershell
Remove-Item Env:SIGNAL_CAPTURE_DECISIONS
Remove-Item Env:SIGNAL_CAPTURE_MODE
Remove-Item Env:SIGNAL_CAPTURE_PATH
```

## 5. Weekly outcome-resolution loop (how calibration becomes possible)

1. Run advisories with capture enabled (step 4) over the week.
2. As real outcomes land, attach a label to each captured decision:

   ```powershell
   python -m scripts.signal_arbitrage.advisory_runner `
     --resolve-outcome --decision-id <id> --realized-return <r> `
     --outcome-label WIN --capture-mode write `
     --capture-path data/calibration_corpus/decisions.jsonl
   ```

   Valid labels: `WIN, LOSS, AVOIDED_TRAP, FALSE_POSITIVE, FALSE_NEGATIVE, MISSED_WINNER`.
3. Re-check readiness (step 3). Only once ≥30 resolved, feature-bearing,
   non-synthetic records exist does first-pass calibration unlock:

   ```powershell
   python -m scripts.signal_arbitrage.advisory_runner --run-calibration `
     --capture-path data/calibration_corpus/decisions.jsonl
   ```

   Below 10 eligible records it honestly reports `INSUFFICIENT_EVIDENCE` rather
   than fitting weights to noise.

## Safety contract

- Default = capture disabled → **no file is ever written**.
- Demo captures are always `SYNTHETIC_FIXTURE` → never calibration-eligible.
- `data/calibration_corpus/decisions.jsonl` is gitignored runtime data.
- No broker API, no order placement, no execution surface exists in this loop.
