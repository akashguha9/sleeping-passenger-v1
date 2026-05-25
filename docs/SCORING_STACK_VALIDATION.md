# Scoring Stack Validation — EMS / EQS / DS / LS / EFS / APS

> The advisory scoring stack is currently **uncalibrated**.  This document
> explains what each axis claims to measure, the explicit refusal of
> predictive validity until a labelled outcome corpus exists, and the
> conservative gate that prevents the codebase from silently growing a
> predictive claim it cannot defend.

## TL;DR

* The MVP emits six scores: **EMS, EQS, DS, LS, EFS, APS**.  Their
  formulas are public (see `README.md` and `src/`).
* No predictive claim is currently allowed.  The calibration gate
  (`scripts/calibration_report.py`) returns `INSUFFICIENT_EVIDENCE` until
  a labelled outcome corpus of ≥ 200 closed observations is supplied.
* The conservative thresholds are **Brier ≤ 0.25** and **ECE ≤ 0.10**.
* The gate stamps `advisory_status="ADVISORY_ONLY"` and
  `predictive_claim_allowed=false` on every output until those gates pass.

## What each axis is

| Axis | Name | What it claims to measure |
|---|---|---|
| EMS | Engineered-Manipulation Score | The fraction of a signal's energy that is engineered attention (virality, recycled narrative, curiosity gap) versus durable evidence. |
| EQS | Evidence Quality Score | Primary-source weight + source credibility + confirmation count + recency + cross-source diversity minus contradiction penalty. |
| DS | Durability Score | Time stability + persistence + stress survival + cross-source confirmation + contradiction resistance. |
| LS | Liquidity / Live-source Score | Liquidity proxy + volume + book-depth proxy minus spread penalty. |
| EFS | Execution-Friction Score | Spread + low-liquidity + volatility + timing risk + API-uncertainty penalties. |
| APS | Advisory / Asymmetry / Probability Score | Weighted composite of EQS / DS / LS / market-mispricing minus EMS / EFS. |

The exact linear weights are in `README.md` (search for `EMS = 0.20*…`).

## Why the gate is `INSUFFICIENT_EVIDENCE` today

* No labelled outcome corpus is checked in.
* Closed paper trades exist but the provenance-gated set is below the
  minimum sample size required to defend a calibration claim.
* Without held-out outcomes, **Brier score and ECE are uncomputable**
  for the model itself — only synthetic / hypothetical numbers can be
  produced, which the gate refuses to report as predictive.

## How to compute calibration (when a labelled corpus exists)

For each observation *i*:

```
p_i  ∈ [0, 1]     — the model's advisory probability (APS-normalised or per-axis)
y_i  ∈ {0, 1}     — the realised outcome label
```

### Brier score

```
BS = (1 / N) · Σ_i (p_i − y_i)²
```

* 0.00 = perfect.  0.25 = always predict 0.5.  1.00 = inverted.
* Gate threshold: **BS ≤ 0.25**.

### Expected Calibration Error (ECE)

Partition observations into *B* buckets by predicted probability.  For
each bucket *b*:

```
predicted_b = (1 / |B_b|) · Σ_{i ∈ B_b} p_i
observed_b  = (1 / |B_b|) · Σ_{i ∈ B_b} y_i
ce_b        = | predicted_b − observed_b |
ECE         = Σ_b (|B_b| / N) · ce_b
```

* Gate threshold: **ECE ≤ 0.10**.
* The default bucket count is 10.

### Minimum sample size

```
N_min = 200
```

If `N < N_min`, the gate returns:

```
calibration_status        = "INSUFFICIENT_EVIDENCE"
predictive_claim_allowed  = false
brier_score               = null
ece                       = null
```

## How to run the gate

```powershell
# In dry-run / current state — produces INSUFFICIENT_EVIDENCE:
python scripts/calibration_report.py

# With a JSON list of observations:
python scripts/calibration_report.py --input my_observations.json --output runtime/release/calibration_report.json --json
```

## What the gate does NOT do

* It does **not** fabricate outcome labels.
* It does **not** read live broker fills.
* It does **not** attempt to estimate outcomes from a partial sample.
* It does **not** claim predictive validity below the sample-size or
  threshold gates.

## Promotion path

A future sprint will:

1. Curate a labelled outcome corpus from closed Polymarket markets and
   closed manual trades.
2. Backfill APS, EMS, EQS, DS, LS, EFS at the *moment of signal* (not
   post-hoc).
3. Run the calibration gate against the corpus.
4. Publish the resulting Brier / ECE / reliability diagram alongside
   each model release.

Until step 4 is done, every advisory output continues to carry the
truthful disclaimer that scores are uncalibrated.

## Advisory-only safety note

This document and the supporting code are **advisory-only**.  They do
not authorise execution, do not call brokers, and do not lift the
`execution_gate=LOCKED` invariant.  Every calibration report stamp set:

```
advisory_status      = "ADVISORY_ONLY"
execution_gate       = "LOCKED"
broker_api_called    = false
ai_execution_count   = 0
canonical_store      = "sqlite"
jsonl_is_canonical   = false
```
