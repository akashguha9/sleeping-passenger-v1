"""Customer Consent & Regulatory Fragility Engine (advisory-only).

Core investment law:

    Reported revenue is not automatically good revenue. Revenue must be
    stress-tested against customer consent quality, service fulfilment,
    exit fairness, and regulatory fragility.

Doctrine:
    Process without output is bureaucracy.
    Digital payment without digital relief is a dark-pattern signal.
    Delay becomes revenue when billing continues during processing.
    A premium price creates a premium accountability contract.
    Revenue from trapped users is lower quality than revenue from
    satisfied users.
    Fraud risk can hide inside a chain of individually defensible
    frictions.

Every score in this package is an ADVISORY_ONLY research signal about
business-model risk patterns. It detects risk patterns, not legal guilt;
complaint evidence can be biased; anecdotes are not statistical proof;
intent cannot be inferred without evidence.
"""

CONSENT_DOCTRINE: tuple[str, ...] = (
    "Process without output is bureaucracy.",
    "If collection is instant but correction is slow, revenue quality is suspect.",
    "Digital payment without digital relief is a dark-pattern signal.",
    "A premium price creates a premium accountability contract.",
    "Internal fragmentation is not a customer's liability.",
    "Delay becomes revenue when billing continues during processing.",
    "Revenue from trapped users is lower quality than revenue from satisfied users.",
    "A company that makes exit hard is borrowing from future regulatory risk.",
    "Customer consent is a revenue-quality variable.",
    "A system that tracks money better than outcomes is not efficient; it is extractive.",
)

CONSENT_ADVISORY_NOTE = (
    "ADVISORY_ONLY — business-model risk pattern detection for journal "
    "research. Detects risk patterns, not legal guilt. No orders are "
    "placed; human judgement required."
)
