"""On-chain wallet labelling placeholder."""
from __future__ import annotations

KNOWN_LABELS: dict[str, str] = {
    # Lower-cased addresses → human-readable labels.
    # Seed only; expand from a real label set later.
}


def label_for(address: str) -> str:
    if not address:
        return "unknown"
    return KNOWN_LABELS.get(address.lower(), "unlabelled")
