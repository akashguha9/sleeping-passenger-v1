"""Shared evidence extraction and score contract for the consent engine.

Complaint/review texts are scanned against deterministic phrase lexicons
(one lexicon per harm category). Extraction is counting, not inference:
the engine never claims intent, only that evidence phrases occur.

Every module in this package returns a ``LayerScore`` carrying score
(0–10), label, evidence terms, rationale, confidence, and explicit
missing-data warnings — no naked numbers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.utils.math_utils import clamp01, clip

# ---------------------------------------------------------------------------
# Evidence lexicons. Phrases are matched case-insensitively as substrings.
# Categories mirror the structural patterns in the reflection: easy signup /
# hard cancellation, automatic payment / manual refund, bot-only support,
# language burden, monetized delay, claims non-payment, premium failure.
# ---------------------------------------------------------------------------

EVIDENCE_LEXICONS: dict[str, tuple[str, ...]] = {
    "charged_after_cancellation": (
        "charged after cancel", "cancelled but billed", "canceled but billed",
        "billed after cancellation", "app says cancelled",
        "store says not cancelled", "kept charging", "payment after cancellation",
        # German: debits after a (timely) cancellation
        "nach kundigung abgebucht", "trotz kundigung abgebucht",
        "trotz kundigung weiter abgebucht", "nach kundigung weiter",
        "abbuchung nach kundigung",
    ),
    "cannot_cancel": (
        "cannot cancel", "can't cancel", "couldn't cancel", "could not cancel",
        "no cancellation option", "hard to cancel", "written notice required",
        "cancellation deadline", "auto-renew", "auto renewal",
        # German: Kündigung (cancellation) friction — harm-context phrases
        # only; the bare topic word lives in GERMAN_TOPIC_TERMS.
        "kundigung abgelehnt", "kundigung nicht moglich", "nicht kundbar",
        "kundigung nur schriftlich", "kundigungsfrist verpasst",
        "zum nachstmoglichen zeitpunkt", "vertrag verlangert",
        "mitgliedschaft verlangert", "fristgerecht gekundigt, trotzdem",
    ),
    "email_only_relief": (
        "email only", "had to email", "write an email", "only by email",
        "by post", "letter required", "in writing only",
        # German: written-form / email-only requirements
        "nur schriftlich", "nur per e-mail", "nur per email", "nur per brief",
        "schriftform erforderlich",
    ),
    "bot_only_support": (
        "bot only", "automated bot", "no human", "support unreachable",
        "please email", "no response", "never replied", "no escalation",
        "call queue", "hotline loop",
        # German: bot/queue/abandonment support
        "warteschleife", "nur ein automat", "roboter", "nicht zustandig",
        "kundenservice nicht erreichbar", "keine antwort",
    ),
    "language_burden": (
        "german only", "only in german", "had to translate", "no english",
        "foreign language letter", "not in english",
        "nur auf deutsch", "kein englisch",
    ),
    "processing_delay": (
        "took a week", "took weeks", "still charged", "waiting for response",
        "processing delay", "refund pending", "processed once per week",
        "slow reply", "weeks for refund", "still waiting",
        # German: processing-time / pending refunds
        "bearbeitungszeit", "erstattung steht aus", "warte seit wochen",
        "keine ruckmeldung",
    ),
    "hidden_fees": (
        "hidden fee", "unexpected charge", "admin fee", "interest charged",
        "late fee", "mahnung", "collection letter", "sent to collections",
        "debt collection", "default interest", "reminder fee",
        # German: dunning / arrears monetization
        "mahngebuhr", "verzugszinsen", "inkasso", "forderung",
        "versteckte gebuhr", "bearbeitungsgebuhr",
    ),
    "claims_non_payment": (
        "claim denied", "no reimbursement", "never reimbursed",
        "not reimbursed", "claim ignored", "documents missing",
        "no formal rejection", "no payout", "claim rejected without",
        "never paid a claim",
        # German: insurance claim / reimbursement failures
        "erstattungsantrag abgelehnt", "anspruch abgelehnt", "abgelehnt",
        "unterlagen fehlen", "nicht eingegangen", "keine erstattung",
        "keine ruckerstattung", "keine ruckzahlung", "leistungsfall",
        "versicherung zahlt nicht",
    ),
    "premium_failure": (
        "stolen", "theft", "no support", "poor service", "restricted access",
        "not all equipment", "trainer required", "upfront fee", "no refund",
        "front desk did not help", "incident ignored",
        "gestohlen", "diebstahl",
    ),
    "lock_in": (
        "lock-in", "locked in", "minimum term", "trainer contract",
        "cannot pause", "add-on contract", "bundled contract",
        "mindestlaufzeit", "vertragsbindung",
    ),
    "pause_friction": (
        "cannot pause in app", "pause requires", "freeze requires",
        "pause by email", "freeze by email", "still charged while waiting",
        "pause took", "suspend membership",
        # German: pause / dormancy (Stilllegung)
        "stilllegung", "stilllegen", "pausieren", "ruhend stellen",
        "mitgliedschaft pausieren",
    ),
    "enforcement_speed": (
        "debited immediately", "instant debit", "direct debit failed",
        "fine", "penalty letter", "fast to charge", "debt letter",
        "enforcement",
        # German: SEPA / direct-debit enforcement (harm-context phrases;
        # bare "lastschrift"/"sepa"/"abbuchung" are topic words)
        "sofort abgebucht", "beitrag eingezogen", "lastschrift geplatzt",
        "lastschrift fehlgeschlagen", "abbuchung ohne ankundigung",
    ),
    "backend_mismatch": (
        "app says cancelled", "store says not cancelled", "different department",
        "wrong department", "not synchronized", "office did not know",
        "local store was not informed",
        # German: app/portal/store desync (Deutschlandticket case family)
        "deutschlandticket", "aboportal", "db navigator", "handy-ticket",
        "im abo gekundigt aber",
    ),
    "positive_relief": (
        "easy to cancel", "cancelled in app", "refunded quickly",
        "quick refund", "responsive support", "no problem cancelling",
        "claim paid", "reimbursed promptly", "instant refund",
        "human answered",
        "schnell erstattet", "problemlos gekundigt", "sofort erstattet",
    ),
}

# German TOPIC terms: establish that a text discusses cancellation,
# billing, insurance, etc. — WITHOUT counting as harm evidence. Mapping a
# bare "Vertrag" or "SEPA" to a harm category would let any German text
# mentioning a contract masquerade as a complaint (an inverted gaming
# vector). Used for language detection and evidence-term surfacing only.
GERMAN_TOPIC_TERMS: dict[str, str] = {
    "kundigung": "cancellation",
    "kundigen": "cancellation",
    "fristgerecht": "cancellation",
    "kundigungsfrist": "cancellation",
    "mitgliedschaft": "contract",
    "vertrag": "contract",
    "abo": "contract",
    "mindestlaufzeit": "contract",
    "stilllegung": "pause",
    "stilllegen": "pause",
    "pausieren": "pause",
    "ruhend stellen": "pause",
    "beitrag": "billing",
    "abbuchung": "billing",
    "lastschrift": "billing",
    "sepa": "billing",
    "iban": "billing",
    "rechnung": "billing",
    "gebuhr": "billing",
    "mahnung": "arrears",
    "mahngebuhr": "arrears",
    "verzugszinsen": "arrears",
    "forderung": "arrears",
    "inkasso": "arrears",
    "ruckerstattung": "refund",
    "erstattung": "refund",
    "ruckzahlung": "refund",
    "bearbeitungszeit": "processing",
    "schriftlich": "channel",
    "per e-mail": "channel",
    "kundenservice": "support",
    "warteschleife": "support",
    "automat": "support",
    "roboter": "support",
    "nicht zustandig": "support",
    "versicherung": "insurance",
    "erstattungsantrag": "insurance",
    "leistungsfall": "insurance",
    "anspruch": "insurance",
    "abgelehnt": "insurance",
    "unterlagen fehlen": "insurance",
    "nicht eingegangen": "insurance",
    "deutschlandticket": "mobility",
    "aboportal": "mobility",
    "db navigator": "mobility",
    "handy-ticket": "mobility",
}

import re as _re

_UMLAUT_FOLD = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})
_PUNCTUATION_PATTERN = _re.compile(r"[,!?;:()\"']")
_SENTENCE_PERIOD_PATTERN = _re.compile(r"\.(?!\d)")


def normalize_text(text: str) -> str:
    """Umlaut-safe, hyphen-tolerant lowercase normalization.

    Both evidence texts and lexicon phrases pass through this, so
    "Kündigung", "Kuendigung", and "kundigung" all meet at the same form,
    and "Handy-Ticket" matches "handy ticket".
    """
    lowered = str(text).lower().translate(_UMLAUT_FOLD)
    # Digraph transliterations Germans type without umlaut keys.
    for digraph, folded in (("ae", "a"), ("oe", "o"), ("ue", "u"), ("ss", "s")):
        lowered = lowered.replace(digraph, folded)
    lowered = lowered.replace("-", " ")
    # Strip punctuation so "confirmed," tokenizes as "confirmed"; periods
    # survive only inside numbers ("9.90").
    lowered = _PUNCTUATION_PATTERN.sub(" ", lowered)
    lowered = _SENTENCE_PERIOD_PATTERN.sub(" ", lowered)
    return " ".join(lowered.split())


# Precompute normalized lexicons once; extraction matches in folded space
# but reports the original phrase so German terms stay readable.
_NORMALIZED_LEXICONS: dict[str, tuple[tuple[str, str], ...]] = {
    category: tuple((normalize_text(phrase), phrase) for phrase in phrases)
    for category, phrases in EVIDENCE_LEXICONS.items()
}
_NORMALIZED_TOPICS: tuple[tuple[str, str], ...] = tuple(
    (normalize_text(term), term) for term in GERMAN_TOPIC_TERMS
)

# Confidence: how many independent evidence texts are enough to trust the
# qualitative extraction. Below the floor, scores carry explicit warnings.
EVIDENCE_FULL_CONFIDENCE_TEXTS = 8
EVIDENCE_MIN_TEXTS = 3


@dataclass(slots=True)
class EvidenceHit:
    """All matches for one harm category across the supplied texts."""

    category: str
    count: int
    matched_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class LayerScore:
    """Mandatory score contract for every consent-engine module.

    ``score`` is 0–10. For risk modules 10 = worst risk; for quality
    modules 10 = best quality — ``higher_is_worse`` says which.
    """

    name: str
    score: float
    label: str
    higher_is_worse: bool
    confidence: float
    evidence_terms: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)
    missing_data_warnings: list[str] = field(default_factory=list)
    raw_components: dict[str, float] = field(default_factory=dict)
    advisory_status: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_evidence(texts: list[str]) -> dict[str, EvidenceHit]:
    """Deterministic phrase extraction over complaint/review texts.

    Matching happens in normalized (umlaut-folded, hyphen-tolerant)
    space; reported terms are the original lexicon phrases so German
    evidence stays readable in ``evidence_terms``.
    """
    hits: dict[str, EvidenceHit] = {}
    normalized = [normalize_text(t) for t in texts or []]
    for category, phrases in _NORMALIZED_LEXICONS.items():
        matched: list[str] = []
        count = 0
        for text in normalized:
            for folded, original in phrases:
                if folded in text:
                    count += 1
                    if original not in matched:
                        matched.append(original)
        hits[category] = EvidenceHit(
            category=category, count=count, matched_terms=matched
        )
    return hits


def detect_topics(texts: list[str]) -> dict[str, list[str]]:
    """German topic-term detection: {topic: [matched terms]}.

    Establishes WHAT a text is about (cancellation, billing, insurance)
    without counting as harm evidence. Also the basis for crude language
    detection in the ingestion adapter.
    """
    normalized = [normalize_text(t) for t in texts or []]
    topics: dict[str, list[str]] = {}
    for folded, original in _NORMALIZED_TOPICS:
        topic = GERMAN_TOPIC_TERMS[original]
        for text in normalized:
            if folded in text:
                topics.setdefault(topic, [])
                if original not in topics[topic]:
                    topics[topic].append(original)
                break
    return topics


def evidence_intensity(hit: EvidenceHit, text_count: int) -> float:
    """Category intensity in [0, 1] with a saturating denominator.

    A pattern present in ~40% of the texts (denominator capped at 8) is
    treated as fully established — large complaint sets don't need dozens
    of repeats, and small sets aren't diluted into invisibility. The
    confidence channel (``evidence_confidence``) separately reports how
    much the sample size is worth.
    """
    if text_count <= 0:
        return 0.0
    denominator = clip(text_count * 0.4, 1.0, 8.0)
    return clamp01(hit.count / denominator)


def evidence_confidence(text_count: int) -> float:
    """Extraction confidence in [0, 1] from evidence volume alone."""
    return clamp01(text_count / EVIDENCE_FULL_CONFIDENCE_TEXTS)


def confidence_warnings(text_count: int) -> list[str]:
    """Standard missing-data warnings for thin evidence bases."""
    warnings: list[str] = []
    if text_count == 0:
        warnings.append(
            "no complaint/review texts supplied — evidence-based components "
            "are inactive and structured inputs dominate"
        )
    elif text_count < EVIDENCE_MIN_TEXTS:
        warnings.append(
            f"only {text_count} evidence text(s) — anecdotes are not "
            "statistical proof; treat evidence components as provisional"
        )
    return warnings


def matched_terms(hits: dict[str, EvidenceHit], categories: list[str]) -> list[str]:
    """Flatten matched terms across the given categories (deduplicated)."""
    terms: list[str] = []
    for category in categories:
        hit = hits.get(category)
        if hit:
            for term in hit.matched_terms:
                if term not in terms:
                    terms.append(term)
    return terms


def scale_to_ten(value01: float) -> float:
    """Map a [0, 1] internal value onto the 0–10 reporting scale."""
    return clip(value01 * 10.0, 0.0, 10.0)


def quality_label(score: float) -> str:
    """Label bands for quality scores (10 = best)."""
    if score >= 8.0:
        return "strong"
    if score >= 6.0:
        return "adequate"
    if score >= 4.0:
        return "weak"
    if score >= 2.0:
        return "poor"
    return "critical"


def risk_label(score: float) -> str:
    """Label bands for risk scores (10 = worst)."""
    if score >= 8.0:
        return "severe"
    if score >= 6.0:
        return "high"
    if score >= 4.0:
        return "elevated"
    if score >= 2.0:
        return "moderate"
    return "low"
