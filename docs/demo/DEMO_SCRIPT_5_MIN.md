# 5-Minute Operator Demo Script

> Advisory-only walkthrough.  No broker execution, no order placement.
> The demo proves the *truth surface* honestly reports state — it does
> **not** execute trades and never claims predictive validity until
> calibration unlocks.

## Pre-flight (≈ 0:00)

```
python scripts/bootstrap_local_operator.py --dry-run
```

Verify the JSON report shows:

- `advisory_status = "ADVISORY_ONLY"`
- `execution_gate = "LOCKED"`
- `broker_api_called = false`
- `ai_execution_count = 0`
- `bootstrap_score ≥ 7.0`

## Step 1 — Start the backend (≈ 0:30)

```
python scripts/api_server.py
```

Expected: `Uvicorn running on http://127.0.0.1:8000`.

## Step 2 — Start the frontend (≈ 1:00)

```
cd frontend && npm run dev
```

Navigate to `http://127.0.0.1:3000/live-signals`.

## Step 3 — Show the advisory-only banner (≈ 1:30)

Visible at the top of every page.  Read aloud:

> "ADVISORY ONLY.  Execution is LOCKED.  Broker API is never called.
> AI executes zero trades."

## Step 4 — Show the MOCK/LIVE truth bar (≈ 2:00)

`TopTruthBar` component:

- Live providers → green chips.
- Mock or fallback → amber chips.
- Backend offline → red banner ("backend unreachable — MOCK MODE").

## Step 5 — Show the Source Configuration Snapshot (≈ 2:30)

`SourceConfigurationSnapshot` panel must satisfy `C + N = T`:

- `C` configured sources.
- `N` not-yet-configured.
- `T` total source registry length.

## Step 6 — Run advisory-only refresh (≈ 3:00)

Click `RunRefreshButton`.  The button label reads
"Refresh live signals (advisory-only)" and the resulting toast confirms
`execution_gate=LOCKED`.

## Step 7 — Show the calibration report (≈ 3:30)

```
python scripts/calibration_report.py
```

Confirm:

- `predictive_claim_allowed = false` (because N_real < 200).
- `n_real`, `n_min`, `evidence_status` printed honestly.

## Step 8 — Show the manual trade log (≈ 4:00)

The `ManualTradeLogForm` is the *only* mutation path in the system.

## Step 9 — Show the Moltbook feedback loop (≈ 4:30)

`MoltbookEntryCard` records outcomes for later calibration.

## Step 10 — Show the role-fit scorecard (≈ 5:00)

```
python scripts/segment_role_scorecard.py --markdown docs/scorecards/SEGMENT_ROLE_SCORECARD.md
```

Read the composite role-fit score and explain that Public SaaS is
NOT_TARGETED_THIS_YEAR — that is correct, not a defect.
