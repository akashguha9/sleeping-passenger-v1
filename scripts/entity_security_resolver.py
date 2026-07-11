"""Entity → security resolution — deterministic ladder, honest UNRESOLVED.

Resolution order (first hit wins; each rung records its method):

    1. EXACT_TICKER          symbol present in the securities master
    2. ALIAS                 global_security_aliases exact match
    3. CURATED_NAME          legal/brand name rows from the securities
                             master (name -> canonical_symbol)
    4. FUZZY_NAME            difflib ratio >= 0.90 against master names
                             (high-confidence only; ties -> AMBIGUOUS)
    5. UNRESOLVED            never forced

Ambiguity is surfaced, never silently broken: two candidates above the
fuzzy floor produce selected_ticker=None with both candidates listed.

Reuses the existing securities master (persistence.get/search) and alias
table; adds no new storage.  Pure lookups; advisory-only.
"""

from __future__ import annotations

import difflib
import re
import time
from typing import Any

try:
    from scripts import persistence
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import persistence  # type: ignore[no-redef]

RESOLVER_VERSION = "entity_security_resolver_v1"
FUZZY_FLOOR = 0.90
_CACHE_TTL_S = 300.0

_master_cache: dict[str, Any] = {"at": 0.0, "rows": None}

_CLEAN_RE = re.compile(
    r"\b(inc|corp|corporation|ltd|limited|plc|se|sa|ag|nv|co|company|holdings|group)\b\.?",
    re.IGNORECASE,
)


def clear_cache() -> None:
    _master_cache.update({"at": 0.0, "rows": None})


def _clean_name(name: str) -> str:
    cleaned = _CLEAN_RE.sub("", name or "")
    return re.sub(r"[^a-z0-9 ]", "", cleaned.lower()).strip()


def _load_master() -> list[dict[str, Any]]:
    now = time.monotonic()
    if _master_cache["rows"] is not None and now - _master_cache["at"] < _CACHE_TTL_S:
        return _master_cache["rows"]
    rows: list[dict[str, Any]] = []
    try:
        conn = persistence._get_conn(persistence.DB_PATH)  # noqa: SLF001 - read-only
        try:
            rows = [
                dict(r)
                for r in conn.execute(
                    "SELECT canonical_symbol, name, country, exchange_code, sector"
                    " FROM global_securities WHERE active=1 LIMIT 5000"
                ).fetchall()
            ]
        finally:
            conn.close()
    except Exception:
        rows = []
    _master_cache.update({"at": now, "rows": rows})
    return rows


def resolve_entity(entity_text: str) -> dict[str, Any]:
    """Resolve one entity mention to a security, or honestly refuse."""
    base: dict[str, Any] = {
        "entity_id": str(entity_text or "").strip(),
        "candidate_tickers": [],
        "selected_ticker": None,
        "resolution_method": "UNRESOLVED",
        "confidence": 0.0,
        "ambiguity": [],
        "market": None,
        "country": None,
        "resolver_version": RESOLVER_VERSION,
    }
    text = str(entity_text or "").strip()
    if not text:
        return base
    master = _load_master()
    upper = text.upper()

    # 1. Exact ticker.
    for row in master:
        if str(row.get("canonical_symbol", "")).upper() == upper:
            return {
                **base,
                "candidate_tickers": [row["canonical_symbol"]],
                "selected_ticker": row["canonical_symbol"],
                "resolution_method": "EXACT_TICKER",
                "confidence": 1.0,
                "country": row.get("country"),
            }

    # 2. Alias table (exact, upper-cased by convention).
    try:
        # db_path passed explicitly: resolve_alias's default binds DB_PATH
        # eagerly at import time, which would ignore test monkeypatching.
        alias_hit = persistence.resolve_alias(upper, db_path=persistence.DB_PATH)
    except Exception:
        alias_hit = None
    if alias_hit:
        return {
            **base,
            "candidate_tickers": [alias_hit],
            "selected_ticker": alias_hit,
            "resolution_method": "ALIAS",
            "confidence": 0.95,
        }

    # 3. Curated name (cleaned exact match against master names).
    cleaned = _clean_name(text)
    if cleaned:
        exact_names = [
            row for row in master if _clean_name(str(row.get("name", ""))) == cleaned
        ]
        if len(exact_names) == 1:
            row = exact_names[0]
            return {
                **base,
                "candidate_tickers": [row["canonical_symbol"]],
                "selected_ticker": row["canonical_symbol"],
                "resolution_method": "CURATED_NAME",
                "confidence": 0.9,
                "country": row.get("country"),
            }
        if len(exact_names) > 1:
            return {
                **base,
                "candidate_tickers": [r["canonical_symbol"] for r in exact_names],
                "resolution_method": "AMBIGUOUS",
                "ambiguity": [r["canonical_symbol"] for r in exact_names],
            }

    # 4. High-confidence fuzzy (>= FUZZY_FLOOR); ties are ambiguity.
    if cleaned and len(cleaned) >= 4:
        scored = []
        for row in master:
            name = _clean_name(str(row.get("name", "")))
            if not name:
                continue
            ratio = difflib.SequenceMatcher(None, cleaned, name).ratio()
            if ratio >= FUZZY_FLOOR:
                scored.append((ratio, row))
        scored.sort(key=lambda pair: -pair[0])
        if len(scored) == 1 or (
            len(scored) > 1 and scored[0][0] - scored[1][0] > 0.05
        ):
            ratio, row = scored[0]
            return {
                **base,
                "candidate_tickers": [row["canonical_symbol"]],
                "selected_ticker": row["canonical_symbol"],
                "resolution_method": "FUZZY_NAME",
                "confidence": round(ratio, 4),
                "country": row.get("country"),
            }
        if len(scored) > 1:
            return {
                **base,
                "candidate_tickers": [r["canonical_symbol"] for _, r in scored[:4]],
                "resolution_method": "AMBIGUOUS",
                "ambiguity": [r["canonical_symbol"] for _, r in scored[:4]],
            }

    return base


__all__ = ["RESOLVER_VERSION", "FUZZY_FLOOR", "resolve_entity", "clear_cache"]
