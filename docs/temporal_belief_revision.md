# Temporal Belief Revision

`belief_revision.py` maintains an **append-only** belief timeline per twin. The
original prediction stays immutable; new evidence produces a new `BeliefRevision`,
never an overwrite.

## Record
`revision_id, twin_id, seq (monotonic), prior/revised state, prior/revised
confidence, evidence_arrival, information_gain, days_since_signal, expected,
contradicts_thesis, revision_class, content_hash`.

## Dynamics classification
`CORRECT_UPDATE / OVERREACTION / UNDERREACTION / CHURN / NO_UPDATE`. `analyse_timeline`
summarises churn, total information gain, and counts of each class — so the system
learns about its own belief dynamics (over/under-reaction, failure-to-update),
not just prices.

## Append-only guarantee
`persistence.append_belief_revision` is idempotent on `revision_id`; re-appending is
a no-op and prior revisions are never overwritten (tested:
`test_belief_revision_persistence_append_only`). Read at
`GET /api/intelligence/twins/{id}/timeline`.
