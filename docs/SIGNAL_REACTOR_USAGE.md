# Signal Reactor Usage

> Advisory-only diagnostic. The signal reactor reads signals, labels
> their geometry, scores echo risk, decays waste, maps fission
> branches, fuses only independent evidence, and inserts operator
> control rods. It never executes trades and it never calls a broker.

## What it does

`scripts/signal_reactor.py` composes the following pure-function helpers
into one advisory payload:

- `signal_field_geometry` — direction, phase alignment, resonance, damping
- `echo_risk_engine` — independence vs. repetition, AI-echo guard
- `signal_decay_waste` — half-life decay, stale/duplicate/contradicted classes, waste load
- `fission_branch_mapper` — branch energies and clarity for explosive events
- `fusion_thesis_engine` — evidence density, signal temperature, fusion validity
- `operator_control_rods` — operator heat, containment, meltdown risk, gallardo block
- `adaptive_signal_router` — route weight, nutrient value, terrain penalty

It returns a single dict with:

- `signal_reactor_state` (one of the reactor states below)
- `decision_grade_energy` (advisory score in `0..1`)
- per-component scores (`echo_risk_score`, `fusion_thesis_strength`,
  `meltdown_risk_score`, `waste_load_score`, …)
- `recommendation` (`observe`, `watch`, `review_candidate`,
  `map_branches`, `decay_archive`, `cool_down`, `human_review_only`)
- `allowed_actions` with `broker_execute` **always false**
- `safety` block with `advisory_status="ADVISORY_ONLY"`,
  `execution_gate="LOCKED"`, `broker_order_id="NONE"`.

## What it does not do

- It does **not** place orders.
- It does **not** call a broker API.
- It does **not** authorize AI execution.
- It does **not** invite external users.
- It does **not** require hosting.
- It does **not** require Postgres.
- It does **not** guarantee profitability.
- It does **not** replace human judgement.

## How to run the example

```bash
python scripts/signal_reactor.py --example --json
```

This prints a worked example payload for an aligned independent
two-source news cluster. The example reaches
`FUSION_REVIEW_CANDIDATE`. Even at that state the
`allowed_actions.broker_execute` field stays `false`. Review candidate
is not a trade.

## Reactor states

| State                       | Meaning                                                                                                                         |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `COLD_OBSERVE`              | Not enough evidence to act on; just observe and journal.                                                                        |
| `WARM_WATCH`                | Some clean evidence is accumulating; keep watching, do not promote.                                                             |
| `FUSION_REVIEW_CANDIDATE`   | Multiple *independent* signals align with decent containment — eligible for **human review**, not a trade.                      |
| `FISSION_MAP_ONLY`          | Explosive event but branch clarity is low — map the consequences, do not act on the shock.                                      |
| `HOT_CONTAINMENT_REQUIRED`  | Reaction heat exceeds containment capacity — cool down before any review.                                                       |
| `WASTE_DECAY`               | Stale, duplicated, contradicted, or unreconciled debt is high — archive/decay before considering new positions.                 |
| `ECHO_SUPPRESSED`           | Repetition is being mistaken for confirmation — suppress until independent sources appear.                                      |
| `OPERATOR_CONTROL_RODS`     | Operator heat, altered perception, sleep deficit, or process non-compliance triggered the gallardo block — no trading activity. |

States are ordered by precedence: an operator block always wins, then
echo suppression, then waste decay, then fission map-only, then valid
fusion review, then containment heat, then warm watch, then cold observe.

## Interpretation rules

- **Review candidate is not execution.** It means *a human should look
  closer*. The reactor never authorizes a trade.
- **Echo is not confirmation.** Ten copies of one rumor stay echo
  even if `decision_grade_energy` is technically positive.
- **Heat is not evidence.** A `0.9` operator_heat_score blocks
  promotion regardless of how strong the signal looks.
- **Pattern is not truth.** When `pattern_overfit_risk` is high, the
  reactor marks the trace as `hypothesis_only` even if the geometry is
  beautiful.

## Mathematical model

```
Decision_Grade_Energy =
    Signal_Energy
  * Evidence_Density
  * Criticality_Control
  * Fusion_Validity
  * Fission_Branch_Clarity
  * Containment_Strength
  * Operator_Clearance
  - Waste_Load
  - Meltdown_Risk
  - Echo_Risk
```

Supporting equations live in `docs/SIGNAL_REACTOR_MODEL.md`.

## Future work (out of this sprint)

- UI badges for `signal_reactor_state`, `echo_risk_score`,
  `decision_grade_energy`, `gallardo_block`.
- Threshold calibration once real self-test outcomes are labeled. The
  current thresholds are first-pass and intentionally conservative.
- A persistent waste/quarantine table so cleanup work has memory across
  sessions.
- A source-independence graph so canonical-URL lineage is tracked
  across feeds rather than guessed per-batch.

Nothing here implies broker execution, AI execution, hosting, Postgres,
auth, private beta, or public launch.
