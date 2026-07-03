"""NBI prediction-market bridge — per-event contract matching + branch blend.

Maps Kalshi/Polymarket-style contract rows onto an NBI event's BRANCHES
(never blindly onto the whole event) and blends probabilities:

    alpha      = min(1, VolumeScore x LiquidityScore x PhrasingMatchScore)
    P_blend_b  = alpha x P_market_b + (1 - alpha) x P_model_b

Rules (all tested):
* no matching contract          -> alpha = 0, model-only (never blocks);
* weak phrasing / illiquid      -> low alpha, flagged WEAK_MARKET_MATCH;
* an uncited contract (no URL)  -> alpha = 0 (cite-or-drop applies to
  markets exactly as it applies to claims);
* branch mapping is keyword-driven: a "held in Guwahati" contract maps to
  venue_specific, not core_event;
* official-fact guard: a branch whose engine evidence includes an
  OFFICIAL_GOVERNMENT cluster caps alpha at 0.25 — markets may inform,
  never override, officially confirmed facts;
* the structural invariant survives blending:
  P_blend(venue) <= P_blend(core).

Contract rows are injectable (the normalized shapes the existing Kalshi /
Polymarket adapters emit); this module does no network I/O itself.
The blend annotates the report (``market`` section + ``p_blend`` per
branch) — the engine's evidence-derived ``p`` is never silently rewritten.

Advisory-only.  No trading endpoints, no order placement.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from scripts.narrative_branch_engine import BRANCHES
from scripts.runtime_common import REPO_ROOT

MARKET_BRIDGE_VERSION = "nbi-pm-bridge-v1.0"

MATCH_NONE = "NO_MARKET_MATCH"
MATCH_WEAK = "WEAK_MARKET_MATCH"
MATCH_OK = "MARKET_MATCH"

WEAK_ALPHA_THRESHOLD = 0.20
VOLUME_SATURATION_USD = 25_000.0
OFFICIAL_OVERRIDE_ALPHA_CAP = 0.25
# v1.3 alpha caps (spec: illiquid alpha <= 0.2, weak phrasing alpha <= 0.3;
# both applied stricter-or-equal so they can only demote).
ILLIQUID_VOLUME_FLOOR_USD = 5_000.0
ILLIQUID_ALPHA_CAP = 0.15
WEAK_PHRASING_FLOOR = 0.40
WEAK_PHRASING_ALPHA_CAP = 0.30

# Branch routing keywords — most specific first; a contract must hit one
# branch's vocabulary to be mapped at all.
_BRANCH_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("venue_specific", ("venue", "guwahati", "location", "held in", "hosted in",
                        "city", "moved to", "relocat")),
    ("delegation_intact", ("delegation", "companies attend", "business leaders",
                           "executives attend")),
    ("deals_or_mous", ("mou", "deal", "agreement signed", "investment",
                       "contract signed")),
    ("sector_impact", ("sector", "semiconductor", "tariff", "supply chain")),
    ("already_priced_in", ("priced in", "market reaction", "stock move")),
    ("core_event", ("summit", "visit", "meeting", "talks", "happen",
                    "take place", "cancel")),
)

_TOKEN = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def phrasing_match_score(contract_title: str, event_name: str) -> float:
    """Token overlap (Jaccard on the smaller set) between contract phrasing
    and the event name — deterministic, no embedding dependency."""
    a, b = _tokens(contract_title), _tokens(event_name)
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return round(overlap / min(len(a), len(b)), 4)


def map_contract_to_branch(contract_title: str) -> str | None:
    lowered = (contract_title or "").lower()
    for branch, keywords in _BRANCH_KEYWORDS:
        if any(k in lowered for k in keywords):
            return branch
    return None


def _volume_score(volume_usd: float | None) -> float:
    """VolumeScore = min(1, log(1+V) / log(1+VolumeCap)) — log-scaled so a
    single whale print cannot buy market credibility linearly."""
    if volume_usd is None or volume_usd <= 0:
        return 0.0
    return min(
        1.0, math.log1p(volume_usd) / math.log1p(VOLUME_SATURATION_USD)
    )


def _branch_has_official_evidence(branch_info: dict[str, Any]) -> bool:
    return any(
        ev.get("source_class") == "OFFICIAL_GOVERNMENT"
        for ev in branch_info.get("evidence", [])
    )


RECENCY_LAMBDA_PER_HOUR = 0.01  # half-life ~ 69h of contract-quote age


def _recency_score(fetched_at: Any, now_iso: str | None) -> tuple[float, bool]:
    """exp(-lambda * age_hours); unknown timestamps score 1.0 but are
    flagged RECENCY_UNKNOWN (disclosed, not silently penalized or credited)."""
    if not fetched_at or not now_iso:
        return 1.0, False
    try:
        fetched = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
        now = datetime.fromisoformat(str(now_iso).replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    except ValueError:
        return 1.0, False
    age_hours = max((now - fetched).total_seconds() / 3600.0, 0.0)
    return math.exp(-RECENCY_LAMBDA_PER_HOUR * age_hours), True


def match_prediction_markets_to_nbi_event(
    event_report: dict[str, Any],
    contracts: list[dict[str, Any]] | None,
    *,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Match contract rows to event branches and compute per-branch blends."""
    branches = event_report.get("branches", {})
    event_name = str(event_report.get("event_name") or "")
    matches: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []

    for row in contracts or []:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("contract_title") or "")
        url = str(row.get("url") or row.get("source_url") or "").strip()
        yes_p = row.get("yes_probability")
        try:
            yes_p = float(yes_p)
        except (TypeError, ValueError):
            yes_p = None
        branch = map_contract_to_branch(title)
        if branch is None or yes_p is None:
            unmatched.append({
                "title": title, "reason": "no branch mapping or no probability",
            })
            continue
        volume = row.get("volume_usd")
        try:
            volume = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            volume = None
        liquidity = row.get("liquidity_score")
        try:
            liquidity = float(liquidity) if liquidity is not None else None
        except (TypeError, ValueError):
            liquidity = None
        if liquidity is None:
            liquidity = _volume_score(volume)

        phrasing = phrasing_match_score(title, event_name)
        recency, recency_known = _recency_score(row.get("fetched_at"), now_iso)
        alpha = min(1.0, _volume_score(volume) * max(0.0, min(1.0, liquidity))
                    * phrasing * recency)
        notes: list[str] = []
        if not recency_known and now_iso:
            notes.append("RECENCY_UNKNOWN: contract has no fetched_at stamp")
        if str(row.get("adapter_status") or "LIVE") != "LIVE":
            alpha = 0.0
            notes.append(
                f"ADAPTER_NOT_LIVE: status "
                f"{row.get('adapter_status')!r} -> alpha 0"
            )
        if volume is not None and volume < ILLIQUID_VOLUME_FLOOR_USD:
            if alpha > ILLIQUID_ALPHA_CAP:
                notes.append(
                    f"ILLIQUID: volume {volume:.0f} < "
                    f"{ILLIQUID_VOLUME_FLOOR_USD:.0f} -> alpha capped "
                    f"{ILLIQUID_ALPHA_CAP}"
                )
            alpha = min(alpha, ILLIQUID_ALPHA_CAP)
        if phrasing < WEAK_PHRASING_FLOOR:
            if alpha > WEAK_PHRASING_ALPHA_CAP:
                notes.append(
                    f"WEAK_PHRASING: {phrasing} < {WEAK_PHRASING_FLOOR} -> "
                    f"alpha capped {WEAK_PHRASING_ALPHA_CAP}"
                )
            alpha = min(alpha, WEAK_PHRASING_ALPHA_CAP)
        if not url:
            alpha = 0.0
            notes.append("UNCITED_CONTRACT: no source URL -> alpha 0")

        branch_info = branches.get(branch, {})
        if _branch_has_official_evidence(branch_info):
            if alpha > OFFICIAL_OVERRIDE_ALPHA_CAP:
                notes.append(
                    "OFFICIAL_FACT_GUARD: branch has official evidence -> "
                    f"alpha capped at {OFFICIAL_OVERRIDE_ALPHA_CAP}"
                )
            alpha = min(alpha, OFFICIAL_OVERRIDE_ALPHA_CAP)

        classification = (
            MATCH_NONE if alpha == 0.0
            else MATCH_WEAK if alpha < WEAK_ALPHA_THRESHOLD
            else MATCH_OK
        )
        matches.append({
            "market": str(row.get("market") or row.get("source") or "UNKNOWN"),
            "contract_id": str(row.get("contract_id") or row.get("id") or ""),
            "contract_title": title,
            "yes_probability": max(0.0, min(1.0, yes_p)),
            "volume_usd": volume,
            "liquidity_score": round(liquidity, 4),
            "phrasing_match_score": phrasing,
            "branch": branch,
            "alpha": round(alpha, 4),
            "classification": classification,
            "reason": (
                f"mapped to {branch} via title keywords; "
                f"alpha=min(1, vol x liq x phrasing)"
            ),
            "evidence_url": url or None,
            "notes": notes,
        })

    # Per-branch blend: strongest-alpha contract per branch wins.
    best_by_branch: dict[str, dict[str, Any]] = {}
    for m in matches:
        held = best_by_branch.get(m["branch"])
        if held is None or m["alpha"] > held["alpha"]:
            best_by_branch[m["branch"]] = m

    blended: dict[str, dict[str, Any]] = {}
    for branch in BRANCHES:
        info = branches.get(branch, {})
        p_model = float(info.get("p", 0.5))
        best = best_by_branch.get(branch)
        if best is None or best["alpha"] <= 0.0:
            blended[branch] = {
                "p_model": p_model, "p_market": None, "alpha": 0.0,
                "p_blend": p_model, "source": "MODEL_ONLY",
            }
        else:
            alpha = best["alpha"]
            p_blend = alpha * best["yes_probability"] + (1 - alpha) * p_model
            blended[branch] = {
                "p_model": p_model,
                "p_market": best["yes_probability"],
                "alpha": alpha,
                "p_blend": round(p_blend, 4),
                "source": best["classification"],
                "contract_id": best["contract_id"],
                "evidence_url": best["evidence_url"],
            }

    # Structural invariant survives blending: venue <= core (and the other
    # core-bounded branches likewise).
    core_blend = blended["core_event"]["p_blend"]
    for branch in ("venue_specific", "delegation_intact", "deals_or_mous",
                   "sector_impact"):
        if blended[branch]["p_blend"] > core_blend:
            blended[branch]["p_blend"] = core_blend
            blended[branch]["capped_by_core_blend"] = True

    return {
        "version": MARKET_BRIDGE_VERSION,
        "matches": matches,
        "unmatched": unmatched,
        "blended_branches": blended,
        "any_market_signal": any(
            b["alpha"] > 0 for b in blended.values()
        ),
    }


# ---------------------------------------------------------------------------
# v1.3 auto-fetch — adapter-probing + injectable fetcher, fail-closed
# ---------------------------------------------------------------------------

MARKET_CONTRACTS_PATH = REPO_ROOT / "runtime" / "nbi_market_contracts.json"
MARKET_RAW_PATH = REPO_ROOT / "runtime" / "nbi_market_contracts_raw.json"
FETCH_OK = "FETCHED"
FETCH_ADAPTER_UNAVAILABLE = "ADAPTER_UNAVAILABLE"
FETCH_NO_QUERIES = "NO_QUERIES"

# A fetcher takes a list of query strings and returns raw contract rows.
Fetcher = Callable[[list[str]], list[dict[str, Any]]]


def _event_queries(event_definition: dict[str, Any]) -> list[str]:
    for key in ("prediction_market_queries", "query_terms", "keywords"):
        values = event_definition.get(key)
        if isinstance(values, list) and values:
            return [str(v) for v in values if str(v).strip()]
    return []


def normalize_contract_row(
    raw: dict[str, Any], *, fetched_at: str, market_source: str,
) -> dict[str, Any] | None:
    """Adapter row -> the bridge's contract schema.  Unusable rows -> None."""
    title = str(raw.get("title") or raw.get("question") or raw.get("name") or "")
    yes = raw.get("yes_probability")
    if yes is None:
        yes = raw.get("yes_price") or raw.get("last_price") or raw.get("p_yes")
    try:
        yes = float(yes)
    except (TypeError, ValueError):
        return None
    if yes > 1.0:  # cents-style quote
        yes = yes / 100.0
    url = str(raw.get("url") or raw.get("source_url") or "").strip()
    return {
        "market": market_source,
        "contract_id": str(raw.get("contract_id") or raw.get("id")
                           or raw.get("ticker") or ""),
        "title": title,
        "description": str(raw.get("description") or "")[:500],
        "yes_probability": max(0.0, min(1.0, yes)),
        "volume_usd": raw.get("volume_usd") or raw.get("volume"),
        "liquidity_score": raw.get("liquidity_score"),
        "close_time": raw.get("close_time") or raw.get("end_date"),
        "url": url,
        "fetched_at": fetched_at,
        "is_live": bool(raw.get("is_live", True)),
        "raw_payload_ref": str(MARKET_RAW_PATH),
    }


KALSHI_PUBLIC_MARKETS_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
_FETCH_TIMEOUT_SECONDS = 10
_FETCH_MAX_MARKETS_PER_QUERY = 50
_FETCH_MAX_PAGES = 5

# v1.5 deterministic query expansion.  Country codes -> names; small
# synonym families for the narrative arenas this repo actually watches.
_COUNTRY_NAMES: dict[str, tuple[str, ...]] = {
    "US": ("united states", "america", "u.s."),
    "IN": ("india", "indian"),
    "JP": ("japan", "japanese"),
    "CN": ("china", "chinese"),
    "GB": ("united kingdom", "uk", "britain"),
    "DE": ("germany", "german"),
    "EG": ("egypt", "suez"),
    "KR": ("korea", "korean"),
    "NL": ("netherlands", "dutch"),
}
_SYNONYMS: dict[str, tuple[str, ...]] = {
    "tariff": ("trade deal", "duties", "trade agreement", "trade war"),
    "trade": ("tariff", "trade deal", "trade agreement"),
    "export controls": ("chip ban", "export restrictions", "semiconductor ban"),
    "export": ("export restrictions", "export ban"),
    "chip": ("semiconductor", "chips"),
    "semiconductor": ("chip", "chips", "fab"),
    "shipping": ("freight", "container", "vessel", "transit"),
    "summit": ("meeting", "talks", "state visit"),
    "sanction": ("sanctions", "embargo"),
}


def expand_event_queries(definition: dict[str, Any]) -> dict[str, list[str]]:
    """Deterministic query expansion for market search + matching.

    QuerySet = base terms u country names u sector tags u synonyms u
    entity/official-source stems u prediction_market_queries.  Purely
    deterministic — no model, so a zero-match result is reproducible and
    diagnosable term by term.
    """
    base = [q.lower() for q in _event_queries(definition)]
    market = [
        str(q).lower()
        for q in (definition.get("prediction_market_queries") or [])
        if str(q).strip()
    ]
    country: list[str] = []
    for code in definition.get("country_scope") or []:
        country.extend(_COUNTRY_NAMES.get(str(code).upper(), ()))
    sector = [
        str(t).lower().replace("_", " ")
        for t in (definition.get("sector_tags") or []) if str(t).strip()
    ]
    name_terms = [
        str(definition.get("event_name") or definition.get("name") or "").lower()
    ]
    synonyms: list[str] = []
    for term in base + market + sector + name_terms:
        for key, values in _SYNONYMS.items():
            if key in term:
                synonyms.extend(values)
    entities: list[str] = []
    for source in definition.get("official_sources") or []:
        stem = str(source).split(".")[0].strip().lower()
        if len(stem) >= 3:
            entities.append(stem)
    combined = list(dict.fromkeys(
        base + market + country + sector + synonyms + entities
    ))
    return {
        "base": base, "market": market, "country": country,
        "sector": sector, "synonyms": sorted(set(synonyms)),
        "entities": entities, "combined": combined,
    }


def _title_matches(title_lower: str, queries: list[str]) -> str | None:
    """Phrase hit, or (v1.5 broad mode) >=2 shared tokens with any query."""
    for q in queries:
        if q in title_lower:
            return q
    title_tokens = _tokens(title_lower)
    for q in queries:
        q_tokens = _tokens(q)
        if len(q_tokens) >= 2 and len(title_tokens & q_tokens) >= 2:
            return q
    return None


def build_kalshi_public_fetcher(
    timeout: int = _FETCH_TIMEOUT_SECONDS,
    *, max_pages: int = _FETCH_MAX_PAGES,
) -> Fetcher:
    """Real read-only fetcher against Kalshi's PUBLIC market list.

    No API key, no secrets, no trading endpoints — the public GET /markets
    listing only, now cursor-paginated (v1.5) so matching scans up to
    ``max_pages`` x 200 open markets instead of the first page.  Title
    filtering is client-side: phrase hit or >=2-token overlap with any
    query.  Any network/HTTP/parse failure raises, which the caller
    converts to ADAPTER_UNAVAILABLE (fail closed, never invented rows).
    """
    def fetch(queries: list[str]) -> list[dict[str, Any]]:
        import requests  # local import: network dependency stays optional

        lowered_queries = [q.lower() for q in queries if q.strip()]
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        pages_scanned = 0
        while pages_scanned < max_pages:
            params: dict[str, Any] = {"limit": 200, "status": "open"}
            if cursor:
                params["cursor"] = cursor
            response = requests.get(
                KALSHI_PUBLIC_MARKETS_URL, params=params, timeout=timeout,
                headers={
                    "User-Agent": "sleeping-passenger-nbi-advisory-readonly"
                },
            )
            response.raise_for_status()
            payload = response.json() or {}
            markets = payload.get("markets", [])
            pages_scanned += 1
            for market in markets:
                if not isinstance(market, dict):
                    continue
                title = str(market.get("title") or "")
                matched_query = _title_matches(title.lower(), lowered_queries)
                if matched_query is None:
                    continue
                ticker = str(market.get("ticker") or "")
                rows.append({
                    "market": "kalshi",
                    "id": ticker,
                    "title": title,
                    "description": str(market.get("subtitle") or ""),
                    "yes_price": market.get("yes_bid")
                    or market.get("last_price"),
                    "volume": market.get("volume"),
                    "close_time": market.get("close_time"),
                    "url": (
                        f"https://kalshi.com/markets/{ticker}" if ticker else ""
                    ),
                    "is_live": True,
                    "adapter_status": "LIVE",
                    "query_used": matched_query,
                })
                if len(rows) >= _FETCH_MAX_MARKETS_PER_QUERY:
                    return rows
            cursor = payload.get("cursor")
            if not cursor or not markets:
                break
        return rows

    return fetch


def _default_adapter_fetcher(source: str = "") -> Fetcher | None:
    """Resolve the real fetch path for a named source.

    ``kalshi`` -> the public read-only fetcher.  Anything else (including
    the default '' used by scheduled refreshes, so no unrequested network
    calls happen) -> None, reported as ADAPTER_UNAVAILABLE.  Polymarket's
    repo adapter has no clean query->rows surface yet — honestly absent.
    """
    if source.lower() == "kalshi":
        return build_kalshi_public_fetcher()
    return None


def fetch_prediction_market_contracts(
    event_definition: dict[str, Any],
    *,
    fetcher: Fetcher | None = None,
    source: str = "",
    broad: bool = False,
    now_iso: str | None = None,
) -> dict[str, Any]:
    if broad:
        queries = expand_event_queries(event_definition)["combined"]
    else:
        queries = _event_queries(event_definition)
    stamp = now_iso or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat()
    if not queries:
        return {"status": FETCH_NO_QUERIES, "contracts": [], "queries": []}
    resolved = fetcher or _default_adapter_fetcher(source)
    if resolved is None:
        return {
            "status": FETCH_ADAPTER_UNAVAILABLE,
            "contracts": [],
            "queries": queries,
            "note": (
                "no live market fetcher for source "
                f"{source or '<default>'!r}; model-only blending (alpha=0). "
                "Use --source kalshi for the public read-only path."
            ),
        }
    try:
        raw_rows = resolved(queries)
    except Exception as exc:  # noqa: BLE001 - fail closed, disclose
        return {
            "status": FETCH_ADAPTER_UNAVAILABLE,
            "contracts": [], "queries": queries,
            "error_message": f"{type(exc).__name__}",
            "note": "fetcher failed; no rows invented (fail closed)",
        }
    contracts = []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        normalized = normalize_contract_row(
            raw, fetched_at=stamp,
            market_source=str(raw.get("market") or raw.get("source") or "UNKNOWN"),
        )
        if normalized is not None:
            normalized["adapter_status"] = str(
                raw.get("adapter_status") or "LIVE"
            )
            normalized["query_used"] = str(
                raw.get("query_used") or ";".join(queries)
            )
            normalized["error_message"] = None
            contracts.append(normalized)
    return {
        "status": FETCH_OK, "contracts": contracts, "queries": queries,
        "fetched_at": stamp,
    }


# ---------------------------------------------------------------------------
# v1.5 match diagnostics — MatchScore components, explainable term by term
# ---------------------------------------------------------------------------

MATCH_WEIGHTS = {
    "token": 0.35, "entity": 0.25, "sector": 0.15,
    "branch_specificity": 0.15, "recency": 0.10,
}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compute_match_score(
    contract: dict[str, Any],
    definition: dict[str, Any],
    *, now_iso: str | None = None,
) -> dict[str, Any]:
    """Component MatchScore for one contract against one event definition.

        MatchScore = .35 Token + .25 Entity + .15 Sector
                   + .15 BranchSpecificity + .10 Recency
    """
    expansion = expand_event_queries(definition)
    title = str(contract.get("title") or contract.get("contract_title") or "")
    c_tokens = _tokens(title)

    token = max(
        (_jaccard(c_tokens, _tokens(q)) for q in expansion["combined"]),
        default=0.0,
    )
    entities = expansion["entities"]
    entity = (
        sum(1 for e in entities if e in title.lower()) / len(entities)
        if entities else 0.0
    )
    sectors = expansion["sector"]
    sector = (
        sum(1 for s in sectors if _tokens(s) & c_tokens) / len(sectors)
        if sectors else 0.0
    )
    branch = map_contract_to_branch(title)
    branch_specificity = 1.0 if branch and branch != "core_event" else 0.5
    recency, _ = _recency_score(contract.get("fetched_at"), now_iso)

    components = {
        "token": round(token, 4),
        "entity": round(entity, 4),
        "sector": round(sector, 4),
        "branch_specificity": branch_specificity,
        "recency": round(recency, 4),
    }
    score = sum(MATCH_WEIGHTS[k] * v for k, v in components.items())
    return {
        "contract_title": title,
        "branch": branch,
        "components": components,
        "weights": MATCH_WEIGHTS,
        "match_score": round(score, 4),
    }


def diagnose_event_matching(
    definition: dict[str, Any],
    contracts: list[dict[str, Any]] | None,
    *, now_iso: str | None = None,
) -> dict[str, Any]:
    """Why did (or didn't) contracts match?  Term-by-term, honestly."""
    expansion = expand_event_queries(definition)
    scored = sorted(
        (compute_match_score(c, definition, now_iso=now_iso)
         for c in contracts or [] if isinstance(c, dict)),
        key=lambda s: -s["match_score"],
    )
    matched = [s for s in scored if s["match_score"] >= 0.2]
    near_misses = [s for s in scored if 0.0 < s["match_score"] < 0.2][:5]
    reasons: list[str] = []
    if not contracts:
        reasons.append(
            "no contracts supplied/fetched: run "
            "`fetch --source kalshi` (narrow) or `search --broad` "
            "(expanded QuerySet + pagination)"
        )
    if contracts and not matched:
        reasons.append(
            "contracts present but none reach match_score >= 0.2 — the "
            "arena may genuinely have no listed market"
        )
    if not expansion["market"]:
        reasons.append(
            "definition has no prediction_market_queries: add phrasing "
            "that mirrors how contracts are titled"
        )
    if len(expansion["combined"]) < 5:
        reasons.append(
            f"QuerySet is small ({len(expansion['combined'])} terms): add "
            "sector_tags/country_scope for expansion"
        )
    return {
        "report": "nbi_market_match_diagnosis",
        "event_id": definition.get("event_id"),
        "query_expansion": expansion,
        "queryset_size": len(expansion["combined"]),
        "contracts_examined": len(contracts or []),
        "matched": matched[:10],
        "near_misses": near_misses,
        "reasons": reasons,
        "honest_zero_note": (
            "zero matches is a finding, not a failure: it is recorded, "
            "never padded" if not matched else None
        ),
    }


def bridge_status(
    contracts_path: Path | str | None = None,
) -> dict[str, Any]:
    """Last-fetch census over the persisted contracts file."""
    target = Path(contracts_path) if contracts_path else MARKET_CONTRACTS_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if not isinstance(payload, dict):
        return {
            "report": "nbi_market_bridge_status",
            "contracts_file_present": False,
            "events": {}, "live_rows": 0, "last_fetched_at": None,
            "adapter_health": "NO_FETCH_RECORDED",
        }
    events: dict[str, Any] = {}
    live_rows = 0
    stamps: list[str] = []
    for event_id, rows in payload.items():
        if not isinstance(rows, list):
            continue
        live = [
            r for r in rows
            if isinstance(r, dict)
            and str(r.get("adapter_status") or "LIVE") == "LIVE"
        ]
        live_rows += len(live)
        stamps.extend(
            str(r.get("fetched_at")) for r in rows
            if isinstance(r, dict) and r.get("fetched_at")
        )
        events[event_id] = {"rows": len(rows), "live": len(live)}
    return {
        "report": "nbi_market_bridge_status",
        "contracts_file_present": True,
        "events": events,
        "live_rows": live_rows,
        "last_fetched_at": max(stamps) if stamps else None,
        "adapter_health": "LIVE_ROWS_PRESENT" if live_rows else "NO_LIVE_ROWS",
    }


def refresh_all_contracts(
    definitions: list[dict[str, Any]],
    *,
    fetcher: Fetcher | None = None,
    broad: bool = False,
    out_path: Path | str | None = None,
    raw_path: Path | str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Fetch contracts per event and persist the contracts file the factory
    reads.  Raw payloads are persisted for traceability (cite-or-drop)."""
    per_event: dict[str, list[dict[str, Any]]] = {}
    statuses: dict[str, str] = {}
    raw_dump: dict[str, Any] = {}
    for definition in definitions:
        event_id = str(definition.get("event_id") or "")
        if not event_id:
            continue
        result = fetch_prediction_market_contracts(
            definition, fetcher=fetcher, broad=broad, now_iso=now_iso
        )
        statuses[event_id] = result["status"]
        if result["contracts"]:
            per_event[event_id] = result["contracts"]
            raw_dump[event_id] = result
    target = Path(out_path) if out_path else MARKET_CONTRACTS_PATH
    if per_event:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(per_event, indent=2), encoding="utf-8")
        raw_target = Path(raw_path) if raw_path else MARKET_RAW_PATH
        raw_target.write_text(
            json.dumps(raw_dump, indent=2), encoding="utf-8"
        )
    return {
        "report": "nbi_market_refresh_all",
        "statuses": statuses,
        "events_with_contracts": sorted(per_event),
        "contracts_path": str(target),
        "written": bool(per_event),
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(
        description="NBI prediction-market bridge (advisory-only, read-only)."
    )
    sub = parser.add_subparsers(dest="command")
    m = sub.add_parser("match", help="match a contracts file to a report file")
    m.add_argument("--report-json", required=True)
    m.add_argument("--contracts-json", required=True)
    fe = sub.add_parser("fetch", help="fetch contracts for one event")
    fe.add_argument("--event-json", default=None,
                    help="path to a definition JSON (alternative to --event-id)")
    fe.add_argument("--event-id", default=None,
                    help="event id resolved from runtime definitions")
    fe.add_argument("--source", default="",
                    help="'kalshi' enables the public read-only fetcher")
    ra = sub.add_parser("refresh-all", help="fetch for all event definitions")
    ra.add_argument("--definitions-json", default=None)
    ra.add_argument("--source", default="",
                    help="'kalshi' enables the public read-only fetcher")
    ra.add_argument("--broad", action="store_true",
                    help="use the expanded QuerySet")
    sub.add_parser("status", help="last-fetch census / adapter health")
    dg = sub.add_parser("diagnose", help="explain (non-)matching per event")
    dg.add_argument("--event-id", required=True)
    se = sub.add_parser("search", help="broad live search for one event")
    se.add_argument("--event-id", required=True)
    se.add_argument("--source", default="kalshi")
    ex = sub.add_parser("explain-match",
                        help="MatchScore components for stored contracts")
    ex.add_argument("--event-id", required=True)
    args = parser.parse_args(argv)

    if args.command == "match":
        with open(args.report_json, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        with open(args.contracts_json, "r", encoding="utf-8") as fh:
            contracts = json.load(fh)
        print(json.dumps(
            match_prediction_markets_to_nbi_event(report, contracts), indent=2
        ))
    elif args.command == "fetch":
        if args.event_json:
            with open(args.event_json, "r", encoding="utf-8") as fh:
                definition = json.load(fh)
        elif args.event_id:
            from scripts.nbi_evidence_factory import load_event_definitions
            definition = next(
                (d for d in (load_event_definitions() or [])
                 if str(d.get("event_id")) == args.event_id), None,
            )
            if definition is None:
                print(json.dumps({"status": "EVENT_NOT_FOUND",
                                  "event_id": args.event_id}))
                return 1
        else:
            print("--event-json or --event-id required")
            return 2
        print(json.dumps(
            fetch_prediction_market_contracts(definition, source=args.source),
            indent=2,
        ))
    elif args.command == "refresh-all":
        from scripts.nbi_evidence_factory import load_event_definitions
        definitions = (
            json.loads(Path(args.definitions_json).read_text(encoding="utf-8"))
            if args.definitions_json else (load_event_definitions() or [])
        )
        fetcher = _default_adapter_fetcher(args.source)
        print(json.dumps(
            refresh_all_contracts(
                definitions, fetcher=fetcher,
                broad=getattr(args, "broad", False),
            ), indent=2,
        ))
    elif args.command == "status":
        print(json.dumps(bridge_status(), indent=2))
    elif args.command in ("diagnose", "search", "explain-match"):
        from scripts.nbi_evidence_factory import load_event_definitions
        definition = next(
            (d for d in (load_event_definitions() or [])
             if str(d.get("event_id")) == args.event_id), None,
        )
        if definition is None:
            print(json.dumps({"status": "EVENT_NOT_FOUND",
                              "event_id": args.event_id}))
            return 1
        stored = _read_contracts_for(args.event_id)
        if args.command == "search":
            result = fetch_prediction_market_contracts(
                definition, source=args.source, broad=True,
            )
            print(json.dumps(result, indent=2))
            print(json.dumps(diagnose_event_matching(
                definition, result.get("contracts")), indent=2))
        elif args.command == "diagnose":
            print(json.dumps(
                diagnose_event_matching(definition, stored), indent=2
            ))
        else:
            print(json.dumps(
                [compute_match_score(c, definition) for c in stored],
                indent=2,
            ))
    else:
        parser.print_help()
        return 2
    return 0


def _read_contracts_for(event_id: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(
            MARKET_CONTRACTS_PATH.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return []
    rows = payload.get(event_id) if isinstance(payload, dict) else None
    return rows if isinstance(rows, list) else []


__all__ = [
    "MARKET_BRIDGE_VERSION", "MATCH_NONE", "MATCH_WEAK", "MATCH_OK",
    "WEAK_ALPHA_THRESHOLD", "OFFICIAL_OVERRIDE_ALPHA_CAP",
    "ILLIQUID_VOLUME_FLOOR_USD", "ILLIQUID_ALPHA_CAP",
    "WEAK_PHRASING_FLOOR", "WEAK_PHRASING_ALPHA_CAP",
    "FETCH_OK", "FETCH_ADAPTER_UNAVAILABLE", "FETCH_NO_QUERIES",
    "MARKET_CONTRACTS_PATH",
    "KALSHI_PUBLIC_MARKETS_URL", "RECENCY_LAMBDA_PER_HOUR",
    "phrasing_match_score", "map_contract_to_branch",
    "match_prediction_markets_to_nbi_event", "normalize_contract_row",
    "build_kalshi_public_fetcher", "fetch_prediction_market_contracts",
    "refresh_all_contracts", "bridge_status",
    "expand_event_queries", "compute_match_score",
    "diagnose_event_matching", "MATCH_WEIGHTS", "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
