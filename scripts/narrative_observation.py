"""Normalized information observations — typed, deduplicated, independence-weighted.

Converts raw ``signal_events`` rows (news, filings, prediction markets,
disclosures) into the Narrative Cascade layer's typed
InformationObservation dicts, then clusters duplicates and assigns
independence weights.

Pipeline stage covered here:

    INGESTED signal_events row
      -> normalize (deterministic ID, UTC timestamps, source family,
         language guess, explicit missingness)
      -> deduplicate (exact fingerprint -> URL -> near-title Jaccard)
      -> independence weight I_c = 1 / (1 + ln(1 + n_c))

Honesty contract
----------------
* The raw event row is never mutated; observations are derived objects
  with their own ``extraction_version``.
* ``published_at_utc`` is the source's own publication timestamp when the
  payload carries one; ``retrieved_at_utc`` is always the fetch time.
  Missing publication time stays None (retrieval time is never silently
  substituted — the field says which one you have).
* Cluster size is preserved as an ATTENTION measure alongside the
  independence weight (100 syndicated copies are one fact but real
  attention).
* Non-English / empty text is flagged, not scored.

Pure module; stdlib only; advisory-only.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

try:
    from scripts.linguistic_state_engine import extract_linguistic_features
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    from linguistic_state_engine import extract_linguistic_features  # type: ignore[no-redef]

OBSERVATION_SCHEMA_VERSION = "information_observation_v1"
EXTRACTION_METHOD = "deterministic_lexical_v1"

# Source families + configured reliability priors (operator priors, not
# learned).  Reliability is about FACT weight; every source still counts
# fully toward ATTENTION.
SOURCE_FAMILY: dict[str, str] = {
    "polymarket": "prediction_market",
    "kalshi": "prediction_market",
    "prediction_market_disagreement": "prediction_market",
    "gdelt": "news",
    "newsapi": "news",
    "event_registry": "news",
    "sec_edgar": "regulatory_filing",
    "global_filings": "regulatory_filing",
    "asia_disclosure": "regulatory_filing",
    "india": "regulatory_filing",
    "grok_xai": "ai_interpretation",
}

RELIABILITY_PRIOR: dict[str, float] = {
    "regulatory_filing": 0.9,
    "prediction_market": 0.7,
    "news": 0.55,
    "ai_interpretation": 0.45,
    "unknown": 0.4,
}

_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_STOP = frozenset(
    "the a an of to in on for and or as at by with from is are was were be "
    "has have had will would could may might this that these those it its "
    "into over after before amid says said say new".split()
)


def _norm_title(title: str) -> str:
    return _WS_RE.sub(" ", (title or "").strip().lower())


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _parse_ts(ts: Any) -> str | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # GDELT-style compact timestamps: 20260214T101500Z
        try:
            dt = datetime.strptime(ts.strip(), "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def normalize_observation(event_row: dict[str, Any]) -> dict[str, Any] | None:
    """One signal_events row -> one InformationObservation dict (or None).

    Returns None for rows that are not information observations
    (market_data candles, empty payloads).
    """
    if not isinstance(event_row, dict):
        return None
    source_name = str(event_row.get("source_name", "") or "")
    if source_name == "market_data":
        return None  # prices are outcomes, not information observations
    payload = event_row.get("raw_payload")
    if not isinstance(payload, dict):
        return None

    title = str(payload.get("title", "") or payload.get("question", "") or "")
    text_parts = [title]
    for field in ("description", "summary"):
        val = payload.get(field)
        if isinstance(val, str) and val.strip():
            text_parts.append(val.strip())
    raw_text = ". ".join(p for p in text_parts if p) or None
    if not raw_text:
        return None

    retrieved = _parse_ts(event_row.get("fetched_at"))
    if retrieved is None:
        return None
    published = (
        _parse_ts(payload.get("published_at"))
        or _parse_ts(payload.get("seendate"))
        or _parse_ts(payload.get("filed_at"))
    )
    family = SOURCE_FAMILY.get(source_name, "unknown")
    language = str(payload.get("language", "") or "") or None

    linguistic = extract_linguistic_features(raw_text)

    prob = payload.get("implied_probability")
    if isinstance(prob, bool) or not isinstance(prob, (int, float)):
        prob = None

    return {
        "observation_id": f"OBS_{_sha(str(event_row.get('event_id', '')) + retrieved)}",
        "event_id": str(event_row.get("event_id", "") or ""),
        "source_type": family,
        "source_name": source_name,
        "source_url": str(payload.get("url", "") or "") or None,
        "source_item_id": str(payload.get("market_id", "") or "") or None,
        "author_id": None,  # never available on current feeds — honest None
        "published_at_utc": published,
        "retrieved_at_utc": retrieved,
        "raw_title": title or None,
        "raw_text": raw_text,
        "language": language,
        "prediction_market_id": str(payload.get("market_id", "") or "") or None,
        "probability": float(prob) if prob is not None else None,
        "market_volume": payload.get("volume") if isinstance(payload.get("volume"), (int, float)) else None,
        "market_liquidity": payload.get("liquidity") if isinstance(payload.get("liquidity"), (int, float)) else None,
        "linguistic_features": linguistic,
        "source_reliability_prior": RELIABILITY_PRIOR.get(family, RELIABILITY_PRIOR["unknown"]),
        "dedup_fingerprint": _sha(_norm_title(title)),
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "extraction_method": EXTRACTION_METHOD,
        "feature_availability": {
            "published_at": published is not None,
            "url": bool(payload.get("url")),
            "probability": prob is not None,
            "linguistic": bool(linguistic.get("available")),
            "author": False,
        },
    }


def deduplicate_observations(
    observations: list[dict[str, Any]],
    *,
    near_duplicate_jaccard: float = 0.75,
) -> list[dict[str, Any]]:
    """Assign deduplication clusters + independence weights in place-safe copies.

    Cluster rules, in order: exact normalized-title fingerprint; exact URL;
    near-duplicate title (token Jaccard >= threshold vs a cluster's first
    representative).  Adds per-observation:

        deduplication_cluster_id, duplicate_cluster_size,
        independence_weight = 1/(1+ln(1+n_c)), is_cluster_representative
    """
    out = [dict(o) for o in observations if isinstance(o, dict)]
    clusters: list[dict[str, Any]] = []  # {id, fingerprints, urls, tokens, members}

    for idx, obs in enumerate(out):
        fp = obs.get("dedup_fingerprint")
        url = obs.get("source_url")
        toks = _tokens(obs.get("raw_title") or "")
        target = None
        for cluster in clusters:
            if fp and fp in cluster["fingerprints"]:
                target = cluster
                break
            if url and url in cluster["urls"]:
                target = cluster
                break
            if toks and _jaccard(toks, cluster["tokens"]) >= near_duplicate_jaccard:
                target = cluster
                break
        if target is None:
            target = {
                "id": f"DUP_{_sha((obs.get('raw_title') or '') + str(len(clusters)))}",
                "fingerprints": set(),
                "urls": set(),
                "tokens": toks,
                "members": [],
            }
            clusters.append(target)
        if fp:
            target["fingerprints"].add(fp)
        if url:
            target["urls"].add(url)
        target["members"].append(idx)

    import math as _math
    for cluster in clusters:
        n = len(cluster["members"])
        weight = 1.0 / (1.0 + _math.log(1.0 + (n - 1))) if n > 1 else 1.0
        for rank, idx in enumerate(cluster["members"]):
            out[idx]["deduplication_cluster_id"] = cluster["id"]
            out[idx]["duplicate_cluster_size"] = n
            out[idx]["independence_weight"] = round(weight, 6)
            out[idx]["is_cluster_representative"] = rank == 0
    return out


def build_observations_from_events(
    event_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Full normalize + dedup pass. Returns observations and counts."""
    normalized = []
    skipped = 0
    for row in event_rows if isinstance(event_rows, list) else []:
        obs = normalize_observation(row)
        if obs is None:
            skipped += 1
        else:
            normalized.append(obs)
    deduped = deduplicate_observations(normalized)
    cluster_ids = {o["deduplication_cluster_id"] for o in deduped} if deduped else set()
    return {
        "observations": deduped,
        "raw_event_count": len(event_rows or []),
        "observation_count": len(deduped),
        "skipped_non_information": skipped,
        "duplicate_cluster_count": len(cluster_ids),
        "duplicates_collapsed": len(deduped) - len(cluster_ids),
        "schema_version": OBSERVATION_SCHEMA_VERSION,
    }


__all__ = [
    "OBSERVATION_SCHEMA_VERSION",
    "EXTRACTION_METHOD",
    "SOURCE_FAMILY",
    "RELIABILITY_PRIOR",
    "normalize_observation",
    "deduplicate_observations",
    "build_observations_from_events",
]
