# External Evidence — Paper-Only Calibrated Weight Readback

`EXTERNAL_EVIDENCE_WEIGHT_READBACK`

This document describes how the Moltbook-learned per-bucket advisory weight
`w_b` is read back into the external-evidence score-delta as a **paper-only**
prior — and why this can never affect real-money sizing.

It is the read-side companion to
[`EXTERNAL_EVIDENCE_MOLTBOOK_CALIBRATION.md`](EXTERNAL_EVIDENCE_MOLTBOOK_CALIBRATION.md)
(the write-side: learning `w_b` after a close) and
[`EXTERNAL_ADVISORY_EVIDENCE_PIPELINE.md`](EXTERNAL_ADVISORY_EVIDENCE_PIPELINE.md)
(the signal-time enrichment stage).

Implementation: `scripts/external_evidence_weight_readback.py`, integrated by
`scripts/external_advisory_evidence.py`, persisted by
`scripts/external_evidence_persistence.py`, surfaced by
`frontend/src/components/ExternalEvidenceReliabilityCard.tsx`.

---

## 1. What `w_b` is

`w_b` is a conservative, per-bucket **advisory reliability weight** in
`[0.10, 1.25]`, learned only from *closed* outcomes by the Moltbook calibration
loop. A bucket is keyed by `source_name | evidence_type | route_decision |
confidence_band`. It answers: "historically, when this source produced this
kind of evidence at this confidence band and the trade later closed, did the
evidence help, harm, or create false confidence?"

```
H_b = help_rate   X_b = harm_rate   F_b = false_confidence_rate
Rel_b = clip(0.50 + 0.75*(H_b - 0.50) - 1.00*X_b - 0.75*F_b, 0.10, 1.25)
sample_multiplier_b = 0.50 (n<30) | 0.75 (30<=n<50) | 1.00 (n>=50)
w_b = clip(Rel_b * sample_multiplier_b, 0.10, 1.25)
```

## 2. Why `w_b` is paper-only

Calibration is learned from **paper / manual** outcomes and from a small sample.
A reliability weight that is honest enough to nudge *analysis* is nowhere near
strong enough to *size real money*. So `w_b` is used strictly as a paper-only
prior: every bucket, every readback, and every persisted row carries
`real_money_weight_allowed = false` and `real_money_sizing_impact = "PROHIBITED"`.
Even a mature (`n_b >= 50`) bucket stays paper-only until an explicit, audited
operator-approval flow exists (a future sprint).

## 3. How `bucket_id` is built

```
bucket_id = source_name + "|" + evidence_type + "|" + route_decision + "|" + confidence_band
```

Built identically at write-time (calibration) and read-time (readback), so a
bucket learned after a close is the one looked up at the next signal.

## 4. Confidence band definitions

```
COLD if confidence_calibrated is None
LOW  if confidence_calibrated < 0.35
MID  if 0.35 <= confidence_calibrated < 0.65
HIGH if confidence_calibrated >= 0.65
```

## 5. Sample-size gates

Tiny samples must not manufacture confidence. The effective weight is capped by
sample size:

| Sample count `n_b` | Cap on `c_i` | Reliability label | Operator message |
|---|---|---|---|
| `n_b < 5` | `0.25` | `COLD_START` | Too few outcomes. Reliability heavily discounted. |
| `5 <= n_b < 30` | `0.50` | `EARLY_SAMPLE` | Early evidence only. Paper-only. |
| `30 <= n_b < 50` | `0.75` | `PROVISIONAL` | Provisional reliability. Paper-only. |
| `n_b >= 50` | `1.25` (no extra cap) | `MATURE_PAPER_ONLY` | Mature sample, still paper-only. Real-money sizing prohibited. |

Even at `n_b >= 50`: `real_money_weight_allowed = false`,
`real_money_sizing_impact = "PROHIBITED"`, no automatic sizing, no real-money
authority.

## 6. Harm-sensitive damping

Bad evidence should lose influence faster than good evidence gains it:

```
harm_damping = clip(1 - 0.75*X_b - 0.50*F_b, 0.25, 1.00)
```

Null harm / false-confidence rates (cold start) → `harm_damping = 1.00`, but the
cold-start cap still applies.

## 7. Mathematical formula

For each accepted evidence item `i`:

```
a_i           in [-1, +1]               alignment score
r_i           in {0, 0.25, 0.50, 1.00}  router safety multiplier
q_i           in [0, 1]                 evidence quality multiplier
c_i = w_b     in [0.10, 1.25]           calibrated advisory weight (bucket)
p_i           in {0, 1}                 paper-only eligibility multiplier

c_i_effective = min(c_i, sample_cap)
c_i_final     = clip(c_i_effective * harm_damping, 0.10, 1.25)

delta_i_raw        = a_i * r_i * q_i          (generic confidence proxy w_i is dropped)
delta_i_calibrated = delta_i_raw * c_i_final * p_i

Delta_ext_paper      = clip(sum_i delta_i_calibrated, -1.00, +0.50)
S_paper_candidate    = clip(S_base + Delta_ext_paper, 0, 10)
```

`p_i = 1.0` for paper / `ADVISORY_CONTEXT_ONLY` evidence; `p_i = 0.0` for
real-money mode or any `ERROR_SAFE / DISABLED / CONFIG_MISSING / ROUTER_REJECTED`
status. The cap stays **asymmetric**: maximum positive boost `+0.50`, maximum
negative penalty `-1.00` (a stronger risk reducer than hype booster).

Hard safety overrides (unchanged by calibration):

- If `safety_veto`: `S_final = min(S_paper_candidate, S_base)`, class stays the
  original veto class (DIABLO / CHAOS_VETO / NO_NEW_RISK).
- If external evidence is the only positive evidence: `final_class <= WATCHLIST`.
- If evidence status is error/disabled/rejected: `Delta_ext_paper = 0`,
  `S_final = S_base`.

## 8. Why real-money sizing remains prohibited

Calibration is a *learning* signal, not a *sizing* signal. Sample sizes are
small, outcomes are paper/manual, and the whole framework is advisory-only by
product contract. There is no broker call, no order placement, no autonomous
execution, and no path from `w_b` to a position size anywhere in the code.
`real_money_weight_allowed` is hard-coded `False` on every surface.

## 9. Frontend / operator interpretation

`ExternalEvidenceReliabilityCard.tsx` (implemented + unit-tested, **not mounted
yet**) shows the operator, per source: sample count, help / harm /
false-confidence rates, advisory weight, effective paper weight, the reliability
label, and the operator message. The bundle-level header shows raw vs
paper-calibrated score delta, the asymmetric caps, and a banner: *"Paper-only
reliability. Human review required. Real-money sizing prohibited. No broker
action."* The compact operator block also appears in the daily synthesis context
under `EXTERNAL EVIDENCE RELIABILITY`.

## 10. Failure-safe defaults

- **No bucket** (cold start): `advisory_weight = 0.25`,
  `weight_source = COLD_START_DEFAULT`,
  `proof_status = COLD_START_NO_BUCKET_PAPER_ONLY`.
- **DB read failure**: `advisory_weight = 0.25`,
  `weight_source = ERROR_SAFE_DEFAULT`,
  `proof_status = CALIBRATION_READBACK_FAILED_SAFE_DEFAULT`. Never raises; the
  daily run is never blocked.
- All defaults preserve `real_money_weight_allowed = false` and
  `real_money_sizing_impact = "PROHIBITED"`.

## 11. Current limitations

- External adapters (incl. Kronos) are disabled by default, so a default daily
  run applies calibration to zero items.
- Sample sizes are small; most live buckets sit at the cold-start / early-sample
  caps, so calibrated deltas are heavily discounted in practice.
- The frontend card is implemented and tested but **not mounted** — the daily
  payload is not yet surfaced through a frontend API for external evidence.
- Per-source thresholds are global constants, not yet tuned.

## 12. Next sprint

1. **Mount** the reliability card into the advisory/signal page once the daily
   payload exposes `external_evidence` + `external_evidence_calibration`.
2. **Per-source threshold tuning** once enough closed outcomes exist.
3. **Operator approval flow** for any real-money use of a mature bucket — gated
   behind explicit, audited consent; still never automatic sizing.

---

## Kanté score-ceiling sprint update

The weight-readback `effective_weight` (`c_i_final`) is now cross-checked by the
**fake-confidence audit** (`scripts/fake_confidence_audit.py`). For each bucket
it computes an `overconfidence_score` (OCR):

```
OCR = clip(0.50*false_confidence_rate + 0.30*harm_rate + 0.20*max(advisory_weight - help_rate, 0), 0, 1)
```

**What improved:** a bucket that learned a high weight but keeps being
wrong-while-sure is now labelled `HIGH_FAKE_CONFIDENCE_RISK` and can **never add
positive score delta** (`apply_fake_confidence_block` forces a positive delta to
0). Bad evidence loses influence faster than good evidence gains it.

**What remains future-only:** the OCR needs real closed paper outcomes to become
meaningful — until then every bucket is `COLD_START_UNKNOWN` (not "low risk").

**Why real-money readiness stays low:** `real_money_weight_allowed=false` is
unchanged; a mature, low-OCR bucket is still paper-only. A 10/10 on safety
segments does not imply trading readiness — only 50–100 closed paper outcomes
can move real-money readiness, and no score is a "proven edge" without them.
