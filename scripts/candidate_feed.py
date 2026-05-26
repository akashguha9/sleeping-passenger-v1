"""Candidate Feed loader — discovers existing daily candidate artefacts
and normalises them into ``CandidateContext`` rows that the Buy
Admission Board can grade.

Why this exists
---------------
Before this module the Buy Admission Board was silently empty unless a
caller hand-fed it candidates.  The repo already writes several daily
candidate artefacts (``yesterday_final_candidates.json`` in the daily
payload directory; ``candidate_promotion_contract_summary.json``,
``why_today_summary.json``, ``fresh_discovery_summary.json`` in the
release directory).  This loader reads those files, normalises ticker
forms, and applies a conservative score fallback so honestly-scored
admission rows can be produced without inventing data.

Contract — pure module
----------------------
- Importing has no side effects.
- No broker calls.  No network.  No AI execution.  No web scraping.
- The loader *reads* existing artefacts.  It never generates new
  financial recommendations.  Unknown / static / stale rows get
  conservative fallback scores, never inflated ones.
- Every produced CandidateContext carries the advisory-only invariant.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT
    from scripts.economic_exposure import (
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from scripts.position_context import normalize_position_ticker
except ModuleNotFoundError:  # pragma: no cover — flat-layout fallback
    from runtime_common import REPO_ROOT  # type: ignore
    from economic_exposure import (  # type: ignore
        map_theme_buckets,
        normalize_economic_exposure,
    )
    from position_context import normalize_position_ticker  # type: ignore


DEFAULT_RELEASE_DIR = REPO_ROOT / "runtime" / "release"
DEFAULT_PAYLOAD_DIR = REPO_ROOT / "data" / "daily_payload"


# Feed status vocabulary.
STATUS_CANDIDATES_LOADED = "CANDIDATES_LOADED"
STATUS_NO_CANDIDATE_FILE = "NO_CANDIDATE_FILE"
STATUS_CANDIDATE_FILE_STALE = "CANDIDATE_FILE_STALE"
STATUS_CANDIDATE_FILE_INVALID = "CANDIDATE_FILE_INVALID"

ALL_FEED_STATUSES: tuple[str, ...] = (
    STATUS_CANDIDATES_LOADED,
    STATUS_NO_CANDIDATE_FILE,
    STATUS_CANDIDATE_FILE_STALE,
    STATUS_CANDIDATE_FILE_INVALID,
)

# Reason codes.
REASON_NO_CANDIDATE_FILE = "NO_CANDIDATE_FILE"
REASON_CANDIDATE_FILE_STALE = "CANDIDATE_FILE_STALE"
REASON_CANDIDATE_FILE_INVALID = "CANDIDATE_FILE_INVALID"
REASON_FALLBACK_SCORES_APPLIED = "FALLBACK_SCORES_APPLIED"
REASON_STATIC_UNIVERSE_ONLY = "STATIC_UNIVERSE_ONLY"
REASON_STALE_CARRYOVER = "STALE_CARRYOVER"
REASON_WATCHLIST_ONLY = "WATCHLIST_ONLY"
REASON_SOURCE_VERIFIED = "SOURCE_VERIFIED"
REASON_SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"


# The discovery order is deliberate: ticker-bearing artefacts win over
# id-based gate summaries (which use synthetic ids like "ALL_GREEN" in
# the fixtures and so don't yield admission-board rows).
_CANDIDATE_FILENAMES_RELEASE: tuple[str, ...] = (
    "operator_daily_signal_candidates.json",
    "operator_daily_signal.json",
    "today_candidates.json",
    "candidate_board.json",
    "candidate_board_summary.json",
    "five_model_synthesis.json",
    "five_model_synthesis_summary.json",
)


@dataclass
class CandidateContext:
    """One normalised candidate row, advisory-only."""

    ticker: str
    raw_ticker: str | None = None
    economic_exposure_key: str = ""
    theme_buckets: list[str] = field(default_factory=list)

    candidate_score: float = 0.0
    execution_readiness_score: float = 0.0
    why_today_score: float = 0.0
    freshness_score: float = 0.0
    data_quality_score: float = 0.0

    source_health: str = "UNVERIFIED"
    thesis: str | None = None
    catalyst: str | None = None
    risk_notes: str | None = None
    high_beta: bool = False

    source_file: str | None = None
    generated_at: str | None = None
    missing_fields: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)

    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CandidateFeedResult:
    """Bag of CandidateContexts plus diagnostics for the summary."""

    candidates: list[CandidateContext] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    feed_status: str = STATUS_NO_CANDIDATE_FILE
    reason_codes: list[str] = field(default_factory=list)
    candidate_count: int = 0
    generated_at_utc: str | None = None
    advisory_only: bool = True
    broker_api_called: bool = False
    ai_execution_count: int = 0
    human_execution_required: bool = True
    execution_permission: str = "ADVISORY_ONLY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "source_files": list(self.source_files),
            "feed_status": self.feed_status,
            "reason_codes": list(self.reason_codes),
            "candidate_count": self.candidate_count,
            "generated_at_utc": self.generated_at_utc,
            "advisory_only": self.advisory_only,
            "broker_api_called": self.broker_api_called,
            "ai_execution_count": self.ai_execution_count,
            "human_execution_required": self.human_execution_required,
            "execution_permission": self.execution_permission,
        }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _parse_iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _load_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _has_real_ticker(row: dict[str, Any]) -> bool:
    """Reject placeholder id-only rows like ``{"id": "ALL_GREEN"}`` —
    we only admit rows that carry a recognisable ticker so the
    admission board never grades a synthetic fixture id.
    """
    candidate = row.get("ticker") or row.get("symbol")
    if candidate:
        text = str(candidate).strip()
        if text:
            return True
    # Some gate summaries store the ticker under "normalized_ticker".
    candidate = row.get("normalized_ticker")
    if candidate and str(candidate).strip():
        return True
    return False


def _row_candidates(payload: Any) -> list[dict[str, Any]]:
    """Pull a list of candidate-shaped dicts out of a loaded payload.

    Supports the half-dozen shapes we currently write.
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("candidates", "rows", "final_candidates", "results"):
        block = payload.get(key)
        if isinstance(block, list):
            # If the list is a list of plain strings (ticker symbols),
            # promote each into a thin dict.  Used by
            # ``yesterday_final_candidates.json``.
            if block and all(isinstance(x, str) for x in block):
                return [{"ticker": t, "_source_kind": "static_universe"} for t in block]
            return [r for r in block if isinstance(r, dict)]
    return []


# ---------------------------------------------------------------------------
# Discovery + freshness
# ---------------------------------------------------------------------------


def discover_candidate_files(
    release_dir: Path | None,
    *,
    include_daily_payload_fallback: bool | None = None,
) -> list[Path]:
    """Return every existing candidate artefact path in ``release_dir``.

    Order: release_dir files first (most curated), then
    ``yesterday_final_candidates.json`` from the daily-payload dir as
    the last-resort static universe — but the daily-payload fallback
    is only consulted when the caller is reading the *default* release
    dir.  Tests that point at a tmp dir get a clean isolated read.

    Pass ``include_daily_payload_fallback=True`` to force the fallback
    even for non-default release dirs (used by the default-flow CLI).
    """
    base = Path(release_dir) if release_dir else DEFAULT_RELEASE_DIR
    found: list[Path] = []
    seen: set[str] = set()
    for name in _CANDIDATE_FILENAMES_RELEASE:
        path = base / name
        if path.exists() and str(path) not in seen:
            found.append(path)
            seen.add(str(path))

    if include_daily_payload_fallback is None:
        include_daily_payload_fallback = base == DEFAULT_RELEASE_DIR
    if include_daily_payload_fallback:
        yesterday = DEFAULT_PAYLOAD_DIR / "yesterday_final_candidates.json"
        if yesterday.exists() and str(yesterday) not in seen:
            found.append(yesterday)
    return found


# ---------------------------------------------------------------------------
# Score fallback math (Section 7)
# ---------------------------------------------------------------------------


def _conservative_fallback_scores(raw: dict[str, Any]) -> dict[str, float]:
    """Conservative defaults — see Section 7 of the sprint brief."""
    source_kind = str(raw.get("_source_kind") or "").lower()
    static_only = source_kind == "static_universe"
    return {
        "M": 0.50,
        "F": 0.25 if static_only else 0.40,
        "D": 0.25,
        "W": 0.25 if not raw.get("catalyst") else 0.50,
        "Q": 0.50,
        "R": 0.20,
        "O": 0.00,
    }


def _candidate_score_from_components(raw: dict[str, Any]) -> float:
    explicit = _safe_float(raw.get("candidate_score"))
    if explicit is not None:
        return _clamp(explicit, 0.0, 1.0)
    parts = _conservative_fallback_scores(raw)
    raw_score = (
        0.25 * parts["M"]
        + 0.20 * parts["F"]
        + 0.20 * parts["D"]
        + 0.20 * parts["W"]
        + 0.15 * parts["Q"]
        - 0.15 * parts["R"]
        - 0.10 * parts["O"]
    )
    return _clamp(raw_score, 0.0, 1.0)


def _execution_readiness_from_components(raw: dict[str, Any]) -> float:
    explicit = _safe_float(raw.get("execution_readiness_score"))
    if explicit is not None:
        return _clamp(explicit, 0.0, 1.0)
    live = 1.0 if raw.get("live_price") not in (None, "", 0) else 0.0
    src_verified = 1.0 if str(raw.get("source_health") or "").upper() in {
        "LIVE_VERIFIED",
        "FIXTURE_VERIFIED",
        "VERIFIED",
    } else 0.0
    invalidation = 1.0 if raw.get("invalidation_level") or raw.get("stop_loss") else 0.0
    currency_valid = 1.0 if raw.get("currency") else 0.0
    freshness = _safe_float(raw.get("freshness_score"))
    if freshness is None:
        freshness = 0.25
    raw_score = (
        0.35 * live
        + 0.25 * src_verified
        + 0.20 * invalidation
        + 0.10 * currency_valid
        + 0.10 * _clamp(freshness, 0.0, 1.0)
    )
    return _clamp(raw_score, 0.0, 1.0)


def _why_today_fallback(raw: dict[str, Any]) -> float:
    explicit = _safe_float(raw.get("why_today_score"))
    if explicit is not None:
        return _clamp(explicit, 0.0, 1.0)
    if raw.get("catalyst") or raw.get("fresh_catalyst_score"):
        return 0.50
    source_kind = str(raw.get("_source_kind") or "").lower()
    if source_kind == "static_universe":
        return 0.25
    if raw.get("stale_repeated"):
        return 0.10
    return 0.25


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def normalize_candidate(raw: dict[str, Any]) -> CandidateContext | None:
    """Adapt a raw candidate dict into a CandidateContext.

    Returns ``None`` if the row does not carry a usable ticker — we
    refuse to invent admission rows out of synthetic fixture ids.
    """
    if not isinstance(raw, dict):
        return None
    if not _has_real_ticker(raw):
        return None

    raw_ticker = raw.get("ticker") or raw.get("symbol") or raw.get("normalized_ticker")
    ticker = normalize_position_ticker(raw_ticker)
    if not ticker:
        return None

    metadata = {
        "country": raw.get("country"),
        "leverage": raw.get("leverage"),
        "sector": raw.get("sector"),
    }

    candidate_score = _candidate_score_from_components(raw)
    execution_readiness = _execution_readiness_from_components(raw)
    why_today = _why_today_fallback(raw)
    freshness = _safe_float(raw.get("freshness_score"))
    if freshness is None:
        freshness = 0.25
    data_quality = _safe_float(
        raw.get("data_quality_score") or raw.get("source_reliability_weighted_mean")
    )
    if data_quality is None:
        data_quality = 0.25

    explicit_present = (
        raw.get("candidate_score") is not None
        or raw.get("execution_readiness_score") is not None
        or raw.get("why_today_score") is not None
    )

    source_health_raw = str(raw.get("source_health") or "").upper().strip()
    if source_health_raw in {"LIVE_VERIFIED", "FIXTURE_VERIFIED", "VERIFIED"}:
        source_health = "VERIFIED"
    elif source_health_raw in {"STATIC_FALLBACK", "FALLBACK", "STATIC"}:
        source_health = "STATIC_FALLBACK"
    elif source_health_raw:
        source_health = source_health_raw
    else:
        source_health = "UNVERIFIED"

    ctx = CandidateContext(
        ticker=ticker,
        raw_ticker=str(raw_ticker) if raw_ticker is not None else None,
        economic_exposure_key=normalize_economic_exposure(raw_ticker or ticker),
        theme_buckets=map_theme_buckets(raw_ticker or ticker, metadata),
        candidate_score=round(_clamp(candidate_score, 0.0, 1.0), 4),
        execution_readiness_score=round(_clamp(execution_readiness, 0.0, 1.0), 4),
        why_today_score=round(_clamp(why_today, 0.0, 1.0), 4),
        freshness_score=round(_clamp(float(freshness), 0.0, 1.0), 4),
        data_quality_score=round(_clamp(float(data_quality), 0.0, 1.0), 4),
        source_health=source_health,
        thesis=raw.get("thesis"),
        catalyst=raw.get("catalyst"),
        risk_notes=raw.get("risk_notes"),
        high_beta=bool(raw.get("high_beta") or raw.get("speculative")),
        source_file=raw.get("_source_file"),
        generated_at=raw.get("generated_at") or raw.get("generated_at_utc"),
    )

    missing: list[str] = []
    if not explicit_present:
        missing.append("scores")
        ctx.reason_codes.append(REASON_FALLBACK_SCORES_APPLIED)
    if str(raw.get("_source_kind") or "").lower() == "static_universe":
        ctx.reason_codes.append(REASON_STATIC_UNIVERSE_ONLY)
    if raw.get("stale_repeated"):
        ctx.reason_codes.append(REASON_STALE_CARRYOVER)
    if source_health == "VERIFIED":
        ctx.reason_codes.append(REASON_SOURCE_VERIFIED)
    else:
        ctx.reason_codes.append(REASON_SOURCE_UNVERIFIED)
    if not raw.get("catalyst") and ctx.why_today_score < 0.30:
        missing.append("catalyst")
    if not raw.get("thesis"):
        missing.append("thesis")

    ctx.missing_fields = missing
    return ctx


def candidate_to_admission_input(candidate: CandidateContext) -> dict[str, Any]:
    """Adapt a CandidateContext into the dict shape that
    ``build_buy_admission_board`` consumes."""
    return {
        "ticker": candidate.ticker,
        "symbol": candidate.ticker,
        "candidate_score": candidate.candidate_score,
        "execution_readiness_score": candidate.execution_readiness_score,
        "why_today_score": candidate.why_today_score,
        "freshness_score": candidate.freshness_score,
        "data_quality_score": candidate.data_quality_score,
        "high_beta": candidate.high_beta,
        "thesis": candidate.thesis,
        "catalyst": candidate.catalyst,
        "risk_notes": candidate.risk_notes,
        "advisory_only": True,
        "broker_api_called": False,
        "ai_execution_count": 0,
    }


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------


def load_candidate_feed(
    *,
    release_dir: Path | None = None,
    candidate_path: Path | None = None,
    max_age_hours: float = 72,
    now_utc: datetime | None = None,
) -> CandidateFeedResult:
    """Discover and load candidate artefacts.

    If ``candidate_path`` is provided, only that single file is read.
    Otherwise ``discover_candidate_files(release_dir)`` is used.

    The loader is intentionally conservative: missing files become
    ``NO_CANDIDATE_FILE`` rather than an exception; an invalid JSON
    body becomes ``CANDIDATE_FILE_INVALID``; a file older than
    ``max_age_hours`` becomes ``CANDIDATE_FILE_STALE`` but its rows
    are still returned (with reason codes) so the operator can decide.
    """
    now = now_utc or datetime.now(timezone.utc)
    result = CandidateFeedResult()

    if candidate_path is not None:
        files = [Path(candidate_path)] if Path(candidate_path).exists() else []
    else:
        files = discover_candidate_files(
            release_dir or DEFAULT_RELEASE_DIR
        )

    if not files:
        result.feed_status = STATUS_NO_CANDIDATE_FILE
        result.reason_codes.append(REASON_NO_CANDIDATE_FILE)
        return result

    seen_tickers: set[str] = set()
    any_loaded = False
    any_stale = False
    any_invalid = False

    for path in files:
        result.source_files.append(str(path))
        payload = _load_json(path)
        if payload is None:
            any_invalid = True
            result.reason_codes.append(REASON_CANDIDATE_FILE_INVALID)
            continue
        # Stamp source-file metadata onto each raw row.
        rows = _row_candidates(payload)
        if not rows:
            continue
        generated_at = (
            payload.get("generated_at_utc")
            if isinstance(payload, dict)
            else None
        ) or (payload.get("run_date") if isinstance(payload, dict) else None)
        if result.generated_at_utc is None and generated_at:
            result.generated_at_utc = str(generated_at)

        # Staleness check.
        file_stale = False
        gen_dt = _parse_iso_dt(generated_at)
        if gen_dt is not None:
            age_hours = (now - gen_dt).total_seconds() / 3600.0
            if age_hours > max_age_hours:
                file_stale = True
                any_stale = True

        if isinstance(payload, dict):
            watchlist = payload.get("watchlist")
            if isinstance(watchlist, list) and watchlist:
                # Watchlist tickers count as low-information candidates
                # so the operator can see what was carried over.
                for ticker in watchlist:
                    if not isinstance(ticker, str):
                        continue
                    rows.append(
                        {
                            "ticker": ticker,
                            "_source_kind": "watchlist",
                            "_source_file": str(path),
                        }
                    )

        for raw in rows:
            raw.setdefault("_source_file", str(path))
            if file_stale:
                raw.setdefault("_stale_file", True)
            ctx = normalize_candidate(raw)
            if ctx is None:
                continue
            if ctx.ticker in seen_tickers:
                continue
            seen_tickers.add(ctx.ticker)
            if file_stale:
                if REASON_CANDIDATE_FILE_STALE not in ctx.reason_codes:
                    ctx.reason_codes.append(REASON_CANDIDATE_FILE_STALE)
            if str(raw.get("_source_kind") or "").lower() == "watchlist":
                if REASON_WATCHLIST_ONLY not in ctx.reason_codes:
                    ctx.reason_codes.append(REASON_WATCHLIST_ONLY)
            result.candidates.append(ctx)
            any_loaded = True

    if any_loaded:
        result.feed_status = (
            STATUS_CANDIDATE_FILE_STALE if any_stale else STATUS_CANDIDATES_LOADED
        )
        if any_stale and REASON_CANDIDATE_FILE_STALE not in result.reason_codes:
            result.reason_codes.append(REASON_CANDIDATE_FILE_STALE)
    elif any_invalid:
        result.feed_status = STATUS_CANDIDATE_FILE_INVALID
    else:
        result.feed_status = STATUS_NO_CANDIDATE_FILE
        if REASON_NO_CANDIDATE_FILE not in result.reason_codes:
            result.reason_codes.append(REASON_NO_CANDIDATE_FILE)

    result.candidate_count = len(result.candidates)
    return result


__all__ = [
    "STATUS_CANDIDATES_LOADED",
    "STATUS_NO_CANDIDATE_FILE",
    "STATUS_CANDIDATE_FILE_STALE",
    "STATUS_CANDIDATE_FILE_INVALID",
    "ALL_FEED_STATUSES",
    "REASON_NO_CANDIDATE_FILE",
    "REASON_CANDIDATE_FILE_STALE",
    "REASON_CANDIDATE_FILE_INVALID",
    "REASON_FALLBACK_SCORES_APPLIED",
    "REASON_STATIC_UNIVERSE_ONLY",
    "REASON_STALE_CARRYOVER",
    "REASON_WATCHLIST_ONLY",
    "REASON_SOURCE_VERIFIED",
    "REASON_SOURCE_UNVERIFIED",
    "CandidateContext",
    "CandidateFeedResult",
    "discover_candidate_files",
    "normalize_candidate",
    "candidate_to_admission_input",
    "load_candidate_feed",
]
