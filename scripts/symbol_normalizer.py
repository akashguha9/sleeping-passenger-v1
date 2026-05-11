"""
Symbol normalizer — advisory-only, dependency-free.

Resolves an input symbol string to its canonical form by:
  1. Direct lookup in global_securities (already canonical).
  2. Alias lookup in global_security_aliases.
  3. Fallback: UNKNOWN_SYMBOL result with discovery + backfill commands.

No yfinance import. No FastAPI import. No network calls.
Safe for CI, safe for import at test time.

Safety invariants (always present in every returned dict):
  advisory_status      = ADVISORY_ONLY
  execution_gate       = LOCKED
  human_review_required = True
  ai_execution_count   = 0
  broker_api_called    = False
  broker_order_id      = NONE
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_ADVISORY_STATUS = "ADVISORY_ONLY"
_AI_EXECUTION_COUNT = 0

_SAFE_BASE: dict[str, Any] = {
    "advisory_status": _ADVISORY_STATUS,
    "execution_gate": "LOCKED",
    "human_review_required": True,
    "ai_execution_count": _AI_EXECUTION_COUNT,
    "broker_api_called": False,
    "broker_order_id": "NONE",
}


def normalize_symbol(
    raw_symbol: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve *raw_symbol* to its canonical form.

    Returns a dict with keys:
      canonical_symbol   — resolved symbol (or raw_symbol.upper() on UNKNOWN)
      input_symbol       — original input
      resolution_path    — 'direct' | 'alias' | 'unknown'
      alias_used         — alias string if resolution_path == 'alias', else None
      security           — security record dict if found, else None
      unknown            — True iff symbol not found
      discovery_command  — exact CLI to discover this symbol
      backfill_command   — exact CLI to backfill OHLCV for this symbol
      + advisory safety fields
    """
    sym = raw_symbol.strip().upper()
    kwargs: dict = {} if db_path is None else {"db_path": db_path}

    try:
        try:
            from scripts.persistence import get_global_security, resolve_alias
        except ModuleNotFoundError:
            from persistence import get_global_security, resolve_alias  # type: ignore[no-redef]

        # Step 1: direct lookup
        security = get_global_security(sym, **kwargs)
        if security is not None:
            return {
                **_SAFE_BASE,
                "canonical_symbol": sym,
                "input_symbol": sym,
                "resolution_path": "direct",
                "alias_used": None,
                "security": security,
                "unknown": False,
                "discovery_command": (
                    f"python scripts/global_security_master_discovery.py --symbols {sym} --write"
                ),
                "backfill_command": (
                    f"python scripts/backfill_global_ohlcv.py --symbols {sym} --period max --interval 1d --write"
                ),
            }

        # Step 2: alias lookup
        canonical = resolve_alias(sym, **kwargs)
        if canonical is not None:
            security = get_global_security(canonical, **kwargs)
            return {
                **_SAFE_BASE,
                "canonical_symbol": canonical,
                "input_symbol": sym,
                "resolution_path": "alias",
                "alias_used": sym,
                "security": security,
                "unknown": False,
                "discovery_command": (
                    f"python scripts/global_security_master_discovery.py --symbols {canonical} --write"
                ),
                "backfill_command": (
                    f"python scripts/backfill_global_ohlcv.py --symbols {canonical} --period max --interval 1d --write"
                ),
            }

    except Exception:
        pass

    # Step 3: not found
    return {
        **_SAFE_BASE,
        "canonical_symbol": sym,
        "input_symbol": sym,
        "resolution_path": "unknown",
        "alias_used": None,
        "security": None,
        "unknown": True,
        "error": "UNKNOWN_SYMBOL",
        "message": (
            f"Symbol '{sym}' not found in global_securities or alias table. "
            "Run discovery to add it."
        ),
        "discovery_command": (
            f"python scripts/global_security_master_discovery.py --symbols {sym} --write"
        ),
        "backfill_command": (
            f"python scripts/backfill_global_ohlcv.py --symbols {sym} --period max --interval 1d --write"
        ),
    }
