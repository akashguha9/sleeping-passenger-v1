# Action Authority Doctrine

**Status: the action-engine score (≈2/10) is DOCTRINE-GATED, not code-gated.**
It will not — and should not — rise by adding code. It rises only when the
three doctrine questions below are answered and ratified by a human owner. This
document frames them; it does not pretend to resolve them unilaterally.

This system is **advisory-only**. See `docs/ADVISORY_ONLY_SAFETY_MODEL.md` and
`docs/ADVISORY_DISCLOSURE.md`. Nothing here weakens that. There is no BUY/ENTER
action, no broker integration, and no order path — by design.

Current live posture (verified by tests and the diagnostics summary):
`action_authority=REVOKED`, `busquets_audit_state=HARD_VETO`,
`execution_integrity_state=LOCKED_EXECUTION`, `can_deploy_capital=false`.

`action_authority` is REVOKED whenever the operator state is altered
(`STRESSED`/`EUPHORIC`/`FATIGUED`/`INTOXICATED`) **or** operator stability is
below threshold. The seeded default (`UNKNOWN` operator, stability 0.40) is
therefore REVOKED — the system fails closed.

---

## Gate 1 — Authority: who can lift `action_authority=REVOKED`?

Open questions to ratify (no code may answer these):

- **Operator-only.** Lifting the lock must be a human act by the single named
  operator. No automated condition, score, or model output may flip it.
- **Written pre-commitment.** Should require a written, timestamped
  pre-commitment (thesis, invalidation, size cap) logged *before* the lock is
  lifted — so the decision is auditable and not retrofitted.
- **Test-suite + observation preconditions.** At minimum: green suite, and a
  documented forward-observation period (see chronology readiness) — the lock
  should not be liftable while readiness is observation-gated.
- **Scope + expiry.** Any lift must be narrow (one named candidate) and
  time-boxed; it must not become a standing "execution mode."

**Until ratified, the lock stays REVOKED.** This doc does not grant authority.

## Gate 2 — Unit of learning: what conditions a BUY/entry *candidate*?

The system must define exactly one unit before any review path is meaningful:

- Is the unit a **single ticker**, a **single thesis**, a **signal cluster**, a
  **Moltbook hypothesis**, or a **regime**? (Recommended: one *thesis* bound to
  one *ticker*, with the Moltbook hypothesis as its falsifiable parent.)
- **Evidence required before human review:** falsifiable thesis,
  cross-state-validated signal, decision-grade (`SIGNAL`, not
  `NARRATIVE_CONSTRUCTED_SIGNAL`/`NOISE`), and `pre_entry_state` =
  `CLEAN_ENTRY_ELIGIBLE` (advisory eligibility only).
- **What invalidates it:** any active blocker (GSCE_PHASE_LOCK, REALM_BIS,
  chaos contamination), operator instability, hallucination risk ≥ threshold,
  or the written invalidation condition triggering.

Note: `CLEAN_ENTRY_ELIGIBLE` is an **advisory** tag (see `scripts/tag_engine.py`).
It is explicitly NOT an execution authorization.

## Gate 3 — Operator contract: what does the system promise?

- **It promises:** to surface advisory classifications and next-action *hints*,
  to log provenance, to fail closed under uncertainty, and to never hide a lock
  or a veto.
- **It does NOT promise:** profit, a live quote guarantee (single-source, no
  redundancy — see `market_data_source_chain()`), or any execution.
- **Human-only, never automated:** the decision to act, the act itself
  (order placement happens outside this system), lifting `action_authority`,
  and accepting capital risk.
- **Logged before a manual action:** the written pre-commitment (thesis, size
  cap, invalidation), the active blocker/veto state, and the advisory tag set.
- **Logged after:** the manual trade (via the existing manual-trade log) and
  later reconciliation of the outcome into the Moltbook.

---

## Why this stays at ~2/10 (the right reason)

The capability gap is not missing code — it is missing **ratified doctrine**.
Adding a BUY path now would invert the safety posture (HARD_VETO,
LOCKED_EXECUTION) and manufacture authority the project has not earned. The
honest score reflects that the decision capability is intentionally absent
until a human answers Gates 1–3 in writing.
