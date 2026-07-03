"""NBI claim ingestion — raw news/provider rows -> narrative_branch_engine claims.

Closes the "claims are hand-supplied" gap from nbi-v1.0.  Converts rows from
the existing news surfaces (GDELT-like, NewsAPI-like, EventRegistry-like,
the daily ``today_news_events.json`` rows, and social/official captures)
into canonical NBI claim records, with three automated stages:

1. **Source-cluster derivation** (independence discipline):
       cluster_id = "story:" + sha1(normalized_title)[:10]   (>=4 title tokens)
                  | "domain:" + root_domain                  (fallback)
   Same story syndicated across domains collapses to ONE cluster —
   conservative by construction: syndication can never manufacture
   independent confirmation.  No URL and no title -> the shared
   "UNATTRIBUTED" bucket (the engine's least-independence bucket).

2. **Source-class derivation** from domain/provider: official gov > exchange
   filing > prediction market > credible media > local media (unknown web
   default) > social.  Unknown-with-no-URL degrades to SOCIAL_MEDIA, the
   least-trust class — never upward.

3. **Rule-based narrative-layer classification** (deterministic, ordered;
   no LLM in the loop).  Uncertainty fails closed: an unclassifiable text
   gets UNKNOWN_LAYER, which the engine treats as UNVERIFIED (excluded from
   every truth path).  Social sources can NEVER be classified as
   OFFICIAL_RESOLUTION or NARRATIVE_DEATH — cancellation language from a
   social cluster is a RUMOR with a causal-leap payload, by rule.

Fail-closed guarantees (tested):
* row without a URL -> claim has no evidence_refs -> UNVERIFIED downstream;
* the same article repeated N times -> one cluster;
* independent domains with distinct stories -> distinct clusters;
* classifier never upgrades trust, only assigns less-trusted fallbacks.

Advisory-only.  Pure functions; no network, no DB writes, no execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from scripts.narrative_branch_engine import normalize_claims

INGESTION_PROFILE_VERSION = "nbi-ingest-v1.0"

UNKNOWN_LAYER = "UNKNOWN_LAYER"

# ---------------------------------------------------------------------------
# Domain -> source class
# ---------------------------------------------------------------------------

OFFICIAL_DOMAIN_MARKERS: tuple[str, ...] = (
    ".gov", ".go.jp", ".gov.in", ".gov.uk", ".europa.eu", "mea.gov",
    "mofa.go", "pmo.", "whitehouse.", "bundesregierung.",
)
EXCHANGE_FILING_MARKERS: tuple[str, ...] = (
    "sec.gov", "edgar.", "jpx.co.jp", "bseindia.", "nseindia.",
    "mca.gov.in", "tse.or.jp",
)
PREDICTION_MARKET_MARKERS: tuple[str, ...] = ("kalshi.", "polymarket.")
SOCIAL_DOMAIN_MARKERS: tuple[str, ...] = (
    "twitter.", "x.com", "instagram.", "facebook.", "reddit.", "t.me",
    "telegram.", "tiktok.", "youtube.", "threads.",
)
CREDIBLE_MEDIA_DOMAINS: frozenset[str] = frozenset({
    "reuters.com", "apnews.com", "bloomberg.com", "ft.com", "wsj.com",
    "nikkei.com", "asia.nikkei.com", "nhk.or.jp", "bbc.com", "bbc.co.uk",
    "economist.com", "ptinews.com", "thehindu.com", "livemint.com",
    "economictimes.com", "cnbc.com", "theguardian.com", "nytimes.com",
})
LLM_PROVIDER_MARKERS: tuple[str, ...] = ("grok", "xai", "llm", "gpt", "claude")


def root_domain(url_or_domain: str) -> str:
    """Normalized registrable-ish domain: strips scheme, www/amp/m prefixes."""
    text = (url_or_domain or "").strip().lower()
    if not text:
        return ""
    host = urlparse(text if "://" in text else f"http://{text}").netloc or text
    host = host.split("@")[-1].split(":")[0]
    for prefix in ("www.", "amp.", "m.", "mobile."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def classify_source_class(
    url: str = "", provider: str = "", source_type_hint: str = "",
) -> str:
    """Map domain/provider to an engine source class.  Never upgrades:
    unknown web media -> LOCAL_MEDIA; nothing identifiable -> SOCIAL_MEDIA."""
    hint = (source_type_hint or "").strip().upper()
    if hint in (
        "OFFICIAL_GOVERNMENT", "EXCHANGE_FILING", "COMPANY_FILING",
        "PREDICTION_MARKET", "CREDIBLE_MEDIA", "LOCAL_MEDIA",
        "SOCIAL_MEDIA", "LLM_SUMMARY",
    ):
        return hint
    domain = root_domain(url)
    prov = (provider or "").strip().lower()
    if any(m in prov for m in LLM_PROVIDER_MARKERS):
        return "LLM_SUMMARY"
    if not domain:
        return "SOCIAL_MEDIA"  # unattributable -> least trust
    if any(m in domain for m in SOCIAL_DOMAIN_MARKERS):
        return "SOCIAL_MEDIA"
    if any(m in domain for m in EXCHANGE_FILING_MARKERS):
        return "EXCHANGE_FILING"
    if any(m in domain for m in OFFICIAL_DOMAIN_MARKERS):
        return "OFFICIAL_GOVERNMENT"
    if any(m in domain for m in PREDICTION_MARKET_MARKERS):
        return "PREDICTION_MARKET"
    if domain in CREDIBLE_MEDIA_DOMAINS:
        return "CREDIBLE_MEDIA"
    return "LOCAL_MEDIA"


# ---------------------------------------------------------------------------
# Source-cluster derivation
# ---------------------------------------------------------------------------

_TITLE_STRIP = re.compile(r"[^a-z0-9 ]+")


def _normalized_title_key(title: str) -> str:
    tokens = _TITLE_STRIP.sub(" ", (title or "").lower()).split()
    return " ".join(tokens)


def derive_source_cluster(
    url: str = "", title: str = "", provider: str = "",
) -> dict[str, str]:
    """cluster_id derivation (independence-conservative).

    * >=4 normalized title tokens -> ``story:<sha1[:10]>`` — syndicated
      copies across domains collapse to one cluster;
    * else URL present -> ``domain:<root_domain>``;
    * else provider present -> ``provider:<provider>``;
    * else the shared ``UNATTRIBUTED`` bucket (never a fresh cluster).
    """
    key = _normalized_title_key(title)
    domain = root_domain(url)
    if len(key.split()) >= 4:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        return {"cluster_id": f"story:{digest}", "root_domain": domain}
    if domain:
        return {"cluster_id": f"domain:{domain}", "root_domain": domain}
    prov = (provider or "").strip().lower()
    if prov:
        return {"cluster_id": f"provider:{prov}", "root_domain": ""}
    return {"cluster_id": "UNATTRIBUTED", "root_domain": ""}


# ---------------------------------------------------------------------------
# Rule-based narrative-layer classifier (deterministic, ordered)
# ---------------------------------------------------------------------------

_TRUTH_BEARING = frozenset({
    "OFFICIAL_GOVERNMENT", "EXCHANGE_FILING", "COMPANY_FILING",
    "PREDICTION_MARKET", "CREDIBLE_MEDIA", "LOCAL_MEDIA",
})

# (regex, layer, branch, direction, magnitude) — first match wins.  Rumor
# rows carry claim_magnitude for the causal-leap math; evidence_strength is
# assigned from source class afterwards.
_LAYER_RULES: tuple[tuple[re.Pattern[str], str, str, str, float], ...] = (
    (re.compile(r"\b(officially (cancelled|called off)|cancellation confirmed"
                r"|has been cancelled|is cancelled|called off)\b"),
     "NARRATIVE_DEATH", "core_event", "REFUTES", 9.0),
    # Completion language = the event question is actually resolved.
    (re.compile(r"\b(was held|took place|has concluded|concluded successfully"
                r"|successfully held|wrapped up)\b"),
     "OFFICIAL_RESOLUTION", "core_event", "SUPPORTS", 0.0),
    # Official *confirmation* that an event WILL happen is strong CORE_FACT,
    # not a resolution — the event is still live and closeable.
    (re.compile(r"\b(officially|ministry|government|confirmed by"
                r"|official statement|press release)\b.*\b(confirm|announce)"
                r"|\b(confirm|announce)\w*\b.*\b(officially|ministry"
                r"|government|official statement)\b"),
     "CORE_FACT", "core_event", "SUPPORTS", 0.0),
    (re.compile(r"\b(venue (shifted|changed|moved)|moved to|relocated to"
                r"|itinerary (changed|revised)|scaled down|shortened"
                r"|leg (dropped|cancelled))\b"),
     "PARTIAL_RESOLUTION", "venue_specific", "REFUTES", 0.0),
    (re.compile(r"\b(no official confirmation|denied|denies|clarified"
                r"|debunked|fact[- ]check|refuted)\b"),
     "CORRECTION", "core_event", "SUPPORTS", 0.0),
    (re.compile(r"\b(contradict|conflicting reports|disputes?)\b"),
     "CONTRADICTION", "core_event", "NEUTRAL", 0.0),
    (re.compile(r"\b(may be cancelled|might be cancelled|facing uncertainty"
                r"|sources? (claim|say)|reportedly (off|cancelled)|rumou?r"
                r"|unconfirmed reports?|could be (called off|cancelled)"
                r"|speculat)\b"),
     "RUMOR", "core_event", "REFUTES", 8.0),
    (re.compile(r"\b(viral|reposted|retweet|shared \d+|amplif|trending"
                r"|circulating on)\b"),
     "AMPLIFICATION", "", "NEUTRAL", 0.0),
    (re.compile(r"\b(traffic (jam|snarl|chaos|disruption)|crowd(ing)?"
                r"|protest|road (blocked|closure)|accident|stampede"
                r"|incident near)\b"),
     "TRIGGER", "", "NEUTRAL", 0.0),
    (re.compile(r"\b(mou|memorandum|deal signed|agreement signed"
                r"|investment announced|contract awarded)\b"),
     "CORE_FACT", "deals_or_mous", "SUPPORTS", 0.0),
    (re.compile(r"\b(delegation|business leaders|company executives"
                r"|\d+\s+(japanese|indian)?\s*(companies|firms))\b"),
     "CORE_FACT", "delegation_intact", "SUPPORTS", 0.0),
    (re.compile(r"\b(summit|visit|talks|meeting)\b.*\b(planned|expected"
                r"|scheduled|to be held|underway|preparations?)\b"
                r"|\b(planned|expected|scheduled)\b.*\b(summit|visit"
                r"|talks|meeting)\b"),
     "CORE_FACT", "core_event", "SUPPORTS", 0.0),
)

# Evidence strength assigned by class (0-10) for causal-leap math: what a
# claim of this provenance can structurally prove on its own.
_CLASS_EVIDENCE_STRENGTH: dict[str, float] = {
    "OFFICIAL_GOVERNMENT": 9.0,
    "EXCHANGE_FILING": 8.0,
    "COMPANY_FILING": 7.0,
    "PREDICTION_MARKET": 5.0,
    "CREDIBLE_MEDIA": 5.0,
    "LOCAL_MEDIA": 3.0,
    "SOCIAL_MEDIA": 1.0,
    "LLM_SUMMARY": 1.0,
}
_CLASS_BASE_STRENGTH: dict[str, float] = {
    "OFFICIAL_GOVERNMENT": 0.9,
    "EXCHANGE_FILING": 0.85,
    "COMPANY_FILING": 0.8,
    "PREDICTION_MARKET": 0.7,
    "CREDIBLE_MEDIA": 0.7,
    "LOCAL_MEDIA": 0.6,
    "SOCIAL_MEDIA": 0.5,
    "LLM_SUMMARY": 0.4,
}


def classify_layer(text: str, source_class: str) -> dict[str, Any]:
    """Ordered rule classification.  Fails closed on uncertainty.

    Guardrails:
    * social/LLM sources can never yield NARRATIVE_DEATH or
      OFFICIAL_RESOLUTION — cancellation language downgrades to RUMOR;
    * OFFICIAL_RESOLUTION requires an OFFICIAL_GOVERNMENT source — from
      anyone else it downgrades to CORE_FACT (a report about officials);
    * no rule match -> UNKNOWN_LAYER (excluded from truth by the engine).
    """
    lowered = (text or "").lower()
    notes: list[str] = []
    if not lowered.strip():
        return {
            "layer": UNKNOWN_LAYER, "branch": "", "direction": "NEUTRAL",
            "claim_magnitude": 0.0, "confidence": 0.0,
            "notes": ["empty text -> UNKNOWN_LAYER"],
        }
    truth_bearing = source_class in _TRUTH_BEARING
    for pattern, layer, branch, direction, magnitude in _LAYER_RULES:
        if not pattern.search(lowered):
            continue
        if layer in ("NARRATIVE_DEATH", "OFFICIAL_RESOLUTION") and not truth_bearing:
            notes.append(
                f"{layer} language from {source_class} downgraded to RUMOR"
            )
            return {
                "layer": "RUMOR", "branch": "core_event",
                "direction": "REFUTES", "claim_magnitude": 9.0,
                "confidence": 0.5, "notes": notes,
            }
        if layer == "NARRATIVE_DEATH" and source_class != "OFFICIAL_GOVERNMENT":
            notes.append(
                "cancellation language without official source -> RUMOR "
                "(NARRATIVE_DEATH needs official confirmation)"
            )
            return {
                "layer": "RUMOR", "branch": "core_event",
                "direction": "REFUTES", "claim_magnitude": 9.0,
                "confidence": 0.5, "notes": notes,
            }
        if layer == "OFFICIAL_RESOLUTION" and source_class != "OFFICIAL_GOVERNMENT":
            notes.append(
                "official-resolution language from non-official source -> CORE_FACT"
            )
            layer = "CORE_FACT"
        if layer == "RUMOR" and not truth_bearing:
            pass  # rumor from social stays rumor (velocity input)
        if layer == "PARTIAL_RESOLUTION" and not truth_bearing:
            notes.append("partial-resolution language from social -> RUMOR")
            return {
                "layer": "RUMOR", "branch": "venue_specific",
                "direction": "REFUTES", "claim_magnitude": 6.0,
                "confidence": 0.4, "notes": notes,
            }
        return {
            "layer": layer, "branch": branch, "direction": direction,
            "claim_magnitude": magnitude,
            "confidence": 0.8 if truth_bearing else 0.5,
            "notes": notes,
        }
    return {
        "layer": UNKNOWN_LAYER, "branch": "", "direction": "NEUTRAL",
        "claim_magnitude": 0.0, "confidence": 0.0,
        "notes": ["no classification rule matched -> UNKNOWN_LAYER"],
    }


# ---------------------------------------------------------------------------
# Jurisdiction inference (minimal, honest: unknown stays unknown)
# ---------------------------------------------------------------------------

_TLD_JURISDICTION: dict[str, str] = {
    "jp": "JP", "in": "IN", "uk": "GB", "de": "DE", "fr": "FR", "cn": "CN",
    "kr": "KR", "au": "AU", "sg": "SG",
}


def infer_jurisdiction(url: str = "", explicit: str = "") -> str:
    if (explicit or "").strip():
        return explicit.strip().upper()
    domain = root_domain(url)
    if not domain:
        return ""
    tld = domain.rsplit(".", 1)[-1]
    if tld == "gov" or domain.endswith(".gov"):
        return "US"
    return _TLD_JURISDICTION.get(tld, "")


# ---------------------------------------------------------------------------
# Row extraction — tolerant of GDELT / NewsAPI / EventRegistry / daily rows
# ---------------------------------------------------------------------------

_URL_KEYS = ("url", "source_url", "link", "canonical_url", "article_url")
_TITLE_KEYS = ("headline", "title", "claim_text", "text", "summary")
_PROVIDER_KEYS = ("provider", "source_name", "api", "feed")
_SOURCE_KEYS = ("source", "domain", "sourcecommonname", "outlet")
_TIME_KEYS = (
    "timestamp_utc", "published_at", "publishedAt", "seendate", "date",
    "first_seen", "dateTime",
)


def _first_text(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):  # NewsAPI: {"source": {"name": ...}}
            value = value.get("name")
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_age_hours(row: dict[str, Any], now: datetime | None) -> float | None:
    if now is None:
        return None  # no reference clock supplied -> honest unknown recency
    raw = _first_text(row, _TIME_KEYS)
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T?(\d{2})?(\d{2})?(\d{2})?Z?", raw)
        if m:
            parts = [int(g) for g in m.groups() if g is not None]
            try:
                parsed = datetime(*parts, tzinfo=timezone.utc)  # type: ignore[arg-type]
            except ValueError:
                parsed = None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    reference = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return max((reference - parsed).total_seconds() / 3600.0, 0.0)


def build_nbi_claim_from_news_row(
    row: dict[str, Any],
    event_id: str,
    *,
    index: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One raw provider row -> one engine-ready raw claim dict."""
    data = row if isinstance(row, dict) else {}
    url = _first_text(data, _URL_KEYS)
    title = _first_text(data, _TITLE_KEYS)
    provider = _first_text(data, _PROVIDER_KEYS)
    source = _first_text(data, _SOURCE_KEYS)

    source_class = classify_source_class(
        url=url or source, provider=provider,
        source_type_hint=str(data.get("source_type") or ""),
    )
    cluster = derive_source_cluster(url=url or source, title=title, provider=provider)
    layered = classify_layer(title, source_class)

    mph = data.get("mentions_per_hour")
    if mph is None:
        mph = data.get("narrative_velocity")

    return {
        "claim_id": str(data.get("claim_id") or f"{event_id}:ingest:{index}"),
        "event_id": event_id,
        "claim_text": title,
        "source_cluster": cluster["cluster_id"],
        "source_class": source_class,
        "jurisdiction": infer_jurisdiction(
            url or source, str(data.get("jurisdiction") or "")
        ),
        # UNKNOWN_LAYER is intentionally not in NARRATIVE_LAYERS: the engine
        # marks such claims UNVERIFIED, excluding them from truth paths.
        "layer": layered["layer"],
        "timestamp": _first_text(data, _TIME_KEYS) or None,
        "age_hours": _parse_age_hours(data, now),
        "direction": layered["direction"],
        "branch": layered["branch"],
        "strength": round(
            _CLASS_BASE_STRENGTH.get(source_class, 0.4) * layered["confidence"], 4,
        ),
        "claim_magnitude": layered["claim_magnitude"],
        "evidence_strength": (
            _CLASS_EVIDENCE_STRENGTH.get(source_class, 1.0)
            if layered["layer"] == "RUMOR" else 0.0
        ),
        "mentions_per_hour": mph,
        # Cite-or-drop: only a real URL counts as an evidence ref.
        "evidence_refs": [url] if url else [],
        "provider": provider,
        "root_domain": cluster["root_domain"],
        "ingestion_notes": layered["notes"],
        "raw_row_keys": sorted(data.keys()),
    }


def build_nbi_claims_from_news_rows(
    rows: Any,
    event_id: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Convert provider rows into engine-ready raw claims (list order kept)."""
    items = rows if isinstance(rows, list) else []
    return [
        build_nbi_claim_from_news_row(r, event_id, index=i, now=now)
        for i, r in enumerate(items)
        if isinstance(r, dict)
    ]


def ingest_rows_to_normalized_claims(
    rows: Any, event_id: str, *, now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rows -> raw claims -> the engine's normalized claim records."""
    return normalize_claims(build_nbi_claims_from_news_rows(rows, event_id, now=now))


# ---------------------------------------------------------------------------
# Demo fixture rows (clearly synthetic; provider names say so)
# ---------------------------------------------------------------------------

DEMO_ROWS: list[dict[str, Any]] = [
    {
        "title": "Japan-India summit planned in Guwahati for early July",
        "url": "https://www.reuters.com/world/japan-india-summit-fixture",
        "provider": "FIXTURE_NEWSAPI",
        "publishedAt": "2026-07-01T08:00:00Z",
    },
    {  # syndicated copy — same story key, different domain -> same cluster
        "title": "Japan-India summit planned in Guwahati for early July",
        "url": "https://www.livemint.com/syndicated/japan-india-summit-fixture",
        "provider": "FIXTURE_EVENTREGISTRY",
        "publishedAt": "2026-07-01T09:00:00Z",
    },
    {
        "title": "Traffic chaos and crowding near Ganeshguri flyover",
        "url": "https://www.assamlocalnews.in/ganeshguri-traffic-fixture",
        "provider": "FIXTURE_GDELT",
        "seendate": "20260701T120000Z",
    },
    {
        "title": "Sources claim PM visit may be cancelled after security team stuck",
        "url": "https://www.instagram.com/p/fixture-rumor",
        "provider": "FIXTURE_SOCIAL",
        "narrative_velocity": 42,
    },
    {
        "title": "MOFA press release: summit preparations confirmed by ministry",
        "url": "https://www.mofa.go.jp/press/fixture-confirmation",
        "provider": "FIXTURE_OFFICIAL",
        "published_at": "2026-07-01T15:00:00+00:00",
    },
    {
        "title": None,  # no title, no URL -> UNATTRIBUTED + UNVERIFIED
        "provider": "FIXTURE_BROKEN_ROW",
    },
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "NBI claim ingestion: convert raw news/provider rows into "
            "narrative_branch_engine claims (advisory-only, no network)."
        )
    )
    parser.add_argument("--rows-json", help="Path to a JSON list of raw rows")
    parser.add_argument("--event-id", default="demo-event")
    parser.add_argument(
        "--demo", action="store_true", help="Ingest the built-in fixture rows"
    )
    args = parser.parse_args(argv)

    if args.demo:
        rows: Any = DEMO_ROWS
    elif args.rows_json:
        with open(args.rows_json, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    else:
        parser.print_help()
        return 2

    claims = ingest_rows_to_normalized_claims(rows, args.event_id)
    print(json.dumps(claims, indent=2, default=str))
    verified = sum(1 for c in claims if c["verification"] == "VERIFIED")
    clusters = {c["source_cluster"] for c in claims}
    print(
        f"\n# {len(claims)} claims | {verified} verified | "
        f"{len(clusters)} clusters | ADVISORY_ONLY"
    )
    return 0


__all__ = [
    "INGESTION_PROFILE_VERSION", "UNKNOWN_LAYER",
    "root_domain", "classify_source_class", "derive_source_cluster",
    "classify_layer", "infer_jurisdiction",
    "build_nbi_claim_from_news_row", "build_nbi_claims_from_news_rows",
    "ingest_rows_to_normalized_claims", "DEMO_ROWS", "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
