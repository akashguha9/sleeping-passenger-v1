# Manual Decision Board Doctrine (ADVISORY-ONLY)

The Manual Decision Board (`scripts/manual_decision_board.py`) is an
**advisory-only human-review classifier**. It exists to help one human decide
*what to look at*. **It cannot authorize action and contains no execution
path.**

## What it emits (human-review classifications ONLY)

`MANUAL_REVIEW_CANDIDATE`, `WATCH`, `WAIT`, `AVOID`, `RISK_BLOCK`,
`EXISTING_HOLDING_REVIEW`, `REDUCE_REVIEW`, `OUTCOME_REVIEW_NEEDED`.

## What it will NEVER emit

`BUY`, `SELL`, `ENTER`, `EXECUTE`, `ORDER`, `BROKER_ROUTE` — and it imports no
broker/order/execution module (ast-test enforced). Every output row carries
`human_review_required = true` and `authorizes_action = false`.

## Evidence consumed

`evidence_strength`, `contradiction_score`, `chronology_support`,
`data_freshness`, `governance_state`, `operator_contract_state`,
`invalidation_required`, `moltbook_feedback_value`, `survival_risk`.

## Fail-closed behaviour

- Weak/insufficient evidence while doctrine is **UNRATIFIED** → `RISK_BLOCK`.
- Thin evidence or stale data → `WAIT`.
- Strong evidence still only reaches `MANUAL_REVIEW_CANDIDATE` — a *review*
  flag, never an instruction — and requires a defined invalidation.

## Advisory doctrine states (NOT execution states)

The board reports three states, all of which can coexist with revoked authority:

- `ADVISORY_DECISION_BOARD_AVAILABLE` — the board can run.
- `OPERATOR_CONTRACT_UNRATIFIED` — the human has not ratified the operator
  contract (see `docs/ACTION_AUTHORITY_DOCTRINE.md`).
- `EXECUTION_AUTHORITY_REVOKED` — `action_authority` is REVOKED; unchanged.

## Relationship to execution authority

The board existing does **not** raise execution readiness. `action_authority`
stays REVOKED, `execution_integrity_state` stays LOCKED_EXECUTION,
`busquets_audit_state` stays HARD_VETO, and `can_deploy_capital` stays false.
This is **manual advisory decision maturity**, explicitly **not** execution
maturity. Lifting any lock remains a human act performed outside code, gated by
the five ratification gates in the action-authority doctrine.
