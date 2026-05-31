"""Score the Real Rows Sprint — Phase 1/2/3: the real-row score-vector contract.

The previous sprint ingested REAL canonical ``signal_events`` from three live
read-only sources (yfinance, Polymarket, SEC EDGAR), but those rows were
*unscored*: they carried no six-axis advisory vector, so ``model_probability``
was always NULL and ``n_valid_p`` could never grow off real evidence.

This module is the pure, deterministic, advisory-only score-vector stage.  It
turns one real canonical record into a transparent six-axis vector::

    EMS  Event Momentum Score
    EQS  Evidence Quality Score
    DS   Decision Strength
    LS   Liquidity / live signal strength
    EFS  External Freshness Score
    APS  Alpha Prior Score

Hard rules (all enforced here):

* It is PURE — no DB, no network, no broker, no order, no execution path.
* Every vector carries the advisory-only stamps (``execution_gate = LOCKED``,
  ``broker_api_called = False``, ``ai_execution_count = 0``).
* Missing required fields => ``score_status = "SCORE_UNAVAILABLE"`` with an
  explicit ``score_reason``; axes are left ``None``.  Values are NEVER invented.
* A ``mock`` row never scores as real (``real_row = False``).
* A ``backfill`` row never scores as fresh-live.
* It NEVER claims calibration and NEVER claims edge — the source-reliability
  priors are data-quality weights, not predictive-power claims.

Score math (per record):

    age_hours     = hours(now_utc - event_timestamp_utc)
    FreshnessScore = exp(-age_hours / TTL_hours)

    SchemaValid    = I(required_fields_present) · I(timestamp_valid)
                   · I(source_name_present) · I(not mock) · I(not backfill)

    EQS = clip(R_source · FreshnessScore · SchemaValid · DedupIntegrity, 0, 1)
    DS  = clip(0.40·EventMagnitude + 0.30·SourceReliability + 0.30·Freshness, 0, 1)
    LS  = clip(0.50·VolumeOrLiquidity + 0.30·Depth/Breadth + 0.20·Freshness, 0, 1)
    EFS = clip(FreshnessScore · R_source · SchemaValid, 0, 1)
    APS = clip(0.50·EventMagnitude + 0.25·EvidenceQuality + 0.25·(1-Chaos), 0, 1)
    EMS = clip(source_specific_momentum, 0, 1)

The per-source ``EMS``/``DS``/``LS``/``APS`` specialisations live in
:func:`score_market_row`, :func:`score_polymarket_row` and
:func:`score_sec_edgar_row`.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import math
from typing import Any, Mapping

# Scoring + model versions stamped on every vector (idempotency depends on the
# scoring version, so bump it whenever the math below changes).
SCORING_VERSION = "real-row-score-v1"
# Mirrors decision_probability_snapshot.MODEL_VERSION so downstream snapshots
# and score vectors agree on the model identity.
MODEL_VERSION = "advisory-logistic-v1"

# Status vocabulary.
SCORED = "SCORED"
PARTIAL_SCORE = "PARTIAL_SCORE"
SCORE_UNAVAILABLE = "SCORE_UNAVAILABLE"

# Freshness defaults.
DEFAULT_TTL_HOURS = 24.0
SEC_FILING_TTL_HOURS = 72.0

# Polymarket liquidity reference (denominator of the log-liquidity score).
LIQUIDITY_REF = 100_000.0

# Source-reliability priors.  These are DATA-QUALITY weights, never claims of
# predictive edge.  A higher value means "this source's rows tend to be cleaner
# / better-formed", not "this source predicts the future".
R_SOURCE: dict[str, float] = {
    "yfinance": 0.75,
    "market_data": 0.75,
    "market": 0.75,
    "yahoo": 0.75,
    "market_data_yahoo": 0.75,
    "polymarket": 0.70,
    "sec_edgar": 0.90,
    "sec": 0.90,
    "edgar": 0.90,
    "gdelt": 0.65,
}
DEFAULT_R_SOURCE = 0.50

# SEC EDGAR materiality map (form_type -> prior).
_SEC_MATERIALITY: dict[str, float] = {
    "8-K": 1.00, "10-K": 1.00, "10-Q": 1.00, "S-1": 1.00, "13D": 1.00,
    "SC 13D": 1.00, "4": 1.00,
    "6-K": 0.80, "DEF 14A": 0.80, "20-F": 0.80,
    "13F": 0.60, "13F-HR": 0.60, "424B": 0.60, "424B4": 0.60, "SC 13G": 0.60,
}
_SEC_KNOWN_OTHER = 0.40
_SEC_UNKNOWN = 0.20

# Advisory-only safety stamps stamped on every score vector.
_SAFETY = {
    "advisory_status": "ADVISORY_ONLY",
    "human_execution_required": True,
    "execution_gate": "LOCKED",
    "broker_api_called": False,
    "ai_execution_count": 0,
}

_AXES = ("EMS", "EQS", "DS", "LS", "EFS", "APS")

# Canonical source-type buckets.
SOURCE_TYPE_MARKET = "market_data"
SOURCE_TYPE_PREDICTION_MARKET = "prediction_market"
SOURCE_TYPE_REGULATORY_FILING = "regulatory_filing"
SOURCE_TYPE_NEWS = "news"
SOURCE_TYPE_UNKNOWN = "unknown"


# --------------------------------------------------------------------------- #
# Pure math helpers
# --------------------------------------------------------------------------- #
def clip01(x: float) -> float:
    """Clamp to [0, 1]; NaN/inf collapse to 0.0."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return max(0.0, min(1.0, v))


def sigmoid(x: float) -> float:
    """Numerically-safe sigmoid in (0, 1)."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def freshness_score(age_hours: float | None, ttl_hours: float = DEFAULT_TTL_HOURS) -> float:
    """exp(-age/ttl); 0 when age is unknown or ttl invalid."""
    if age_hours is None or ttl_hours <= 0:
        return 0.0
    return math.exp(-max(0.0, float(age_hours)) / float(ttl_hours))


def _to_float(value: Any) -> float | None:
    """Best-effort float coercion; None on failure / NaN / inf."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _parse_timestamp(value: Any) -> _dt.datetime | None:
    """Parse a wide range of timestamp strings into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, _dt.datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    raw = text.replace("Z", "+00:00")
    # Try full ISO first, then a date-only fallback.
    for parser in (
        lambda s: _dt.datetime.fromisoformat(s),
        lambda s: _dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S"),
        lambda s: _dt.datetime.strptime(s[:10], "%Y-%m-%d"),
    ):
        try:
            dt = parser(raw)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return dt.astimezone(_dt.timezone.utc)
    return None


def _age_hours(event_ts: Any, now: _dt.datetime) -> float | None:
    """Hours between ``event_ts`` and ``now`` (UTC); None when unparsable."""
    dt = _parse_timestamp(event_ts)
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def _resolve_now(now_iso: str | None) -> _dt.datetime:
    if now_iso:
        parsed = _parse_timestamp(now_iso)
        if parsed is not None:
            return parsed
    return _dt.datetime.now(_dt.timezone.utc)


def r_source_for(source_name: str) -> float:
    """Data-quality prior for a source (NOT an edge claim)."""
    return R_SOURCE.get(str(source_name or "").strip().lower(), DEFAULT_R_SOURCE)


def source_type_for(source_name: str) -> str:
    key = str(source_name or "").strip().lower()
    if key in ("yfinance", "market_data", "market", "yahoo", "market_data_yahoo"):
        return SOURCE_TYPE_MARKET
    if key == "polymarket":
        return SOURCE_TYPE_PREDICTION_MARKET
    if key in ("sec_edgar", "sec", "edgar"):
        return SOURCE_TYPE_REGULATORY_FILING
    if key == "gdelt":
        return SOURCE_TYPE_NEWS
    return SOURCE_TYPE_UNKNOWN


def sec_materiality(form_type: str | None) -> float:
    """Materiality prior for an SEC form type (data-quality weight)."""
    if not form_type:
        return _SEC_UNKNOWN
    key = str(form_type).strip().upper()
    if key in _SEC_MATERIALITY:
        return _SEC_MATERIALITY[key]
    # A handful of forms vary by suffix (424B1..5, 4/A, SC 13D/A).
    for prefix, score in (
        ("424B", 0.60), ("SC 13D", 1.00), ("SC 13G", 0.60), ("13F", 0.60),
        ("10-K", 1.00), ("10-Q", 1.00), ("8-K", 1.00), ("20-F", 0.80),
        ("6-K", 0.80), ("DEF 14A", 0.80),
    ):
        if key.startswith(prefix):
            return score
    return _SEC_KNOWN_OTHER


def score_key(event_id: str, source_name: str, scoring_version: str = SCORING_VERSION) -> str:
    """Stable idempotency key: hash(event_id | source_name | scoring_version)."""
    basis = f"{event_id}|{source_name}|{scoring_version}".encode("utf-8")
    return "SK_" + hashlib.sha1(basis).hexdigest()[:24]


# --------------------------------------------------------------------------- #
# Vector envelope helpers
# --------------------------------------------------------------------------- #
def _base_vector(
    *,
    source_name: str,
    source_type: str,
    real_row: bool,
    mock_flag: bool,
    backfill_flag: bool,
) -> dict[str, Any]:
    """A fully-stamped, axis-null vector envelope."""
    vector: dict[str, Any] = {axis: None for axis in _AXES}
    vector.update({
        "score_status": SCORE_UNAVAILABLE,
        "score_reason": "",
        "source_name": source_name,
        "source_type": source_type,
        "scoring_version": SCORING_VERSION,
        "model_version": MODEL_VERSION,
        "real_row": bool(real_row),
        "mock_flag": bool(mock_flag),
        "backfill_flag": bool(backfill_flag),
        # Never a predictive claim — calibration stays locked.
        "predictive_claim_allowed": False,
        "edge_claimed": False,
    })
    vector.update(_SAFETY)
    return vector


def _unavailable(
    *,
    source_name: str,
    source_type: str,
    reason: str,
    real_row: bool,
    mock_flag: bool = False,
    backfill_flag: bool = False,
) -> dict[str, Any]:
    vector = _base_vector(
        source_name=source_name, source_type=source_type, real_row=real_row,
        mock_flag=mock_flag, backfill_flag=backfill_flag,
    )
    vector["score_status"] = SCORE_UNAVAILABLE
    vector["score_reason"] = reason
    return vector


def axes_complete(vector: Mapping[str, Any]) -> bool:
    """True only when all six axes are non-null floats in [0, 1] and SCORED."""
    if vector.get("score_status") != SCORED:
        return False
    for axis in _AXES:
        v = vector.get(axis)
        if v is None:
            return False
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return False
        if math.isnan(fv) or math.isinf(fv) or fv < 0.0 or fv > 1.0:
            return False
    return True


def axes_dict(vector: Mapping[str, Any]) -> dict[str, float] | None:
    """Return the six axes as a float dict, or None when not fully present."""
    out: dict[str, float] = {}
    for axis in _AXES:
        v = vector.get(axis)
        if v is None:
            return None
        fv = _to_float(v)
        if fv is None:
            return None
        out[axis] = fv
    return out


# --------------------------------------------------------------------------- #
# Source-specific scorers
# --------------------------------------------------------------------------- #
def score_market_row(
    record: Mapping[str, Any],
    *,
    source_name: str = "yfinance",
    now_iso: str | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Score a yfinance / market-data row.

    Required: a current price and a parseable timestamp.  A missing previous
    price yields PARTIAL_SCORE (EventMagnitude unknown) rather than a fabricated
    momentum reading.
    """
    src_type = SOURCE_TYPE_MARKET
    vector = _base_vector(
        source_name=source_name, source_type=src_type, real_row=True,
        mock_flag=False, backfill_flag=False,
    )
    now = _resolve_now(now_iso)
    R = r_source_for(source_name)

    price = _to_float(record.get("latest_price"))
    if price is None:
        price = _to_float(record.get("price"))
    if price is None:
        price = _to_float(record.get("close"))
    if price is None:
        return _unavailable(
            source_name=source_name, source_type=src_type,
            reason="MISSING_PRICE", real_row=True,
        )

    ts = record.get("timestamp") or fetched_at
    age = _age_hours(ts, now)
    timestamp_valid = age is not None
    if not timestamp_valid:
        # Fall back to fetched_at observation time if the bar timestamp is bad.
        age = _age_hours(fetched_at, now)
        timestamp_valid = age is not None
    F = freshness_score(age, ttl_hours)

    schema_valid = 1.0 if (timestamp_valid and bool(source_name)) else 0.0
    dedup_integrity = 1.0  # event_id uniqueness is enforced by the persistence layer

    # ----- EventMagnitude / MomentumScore --------------------------------- #
    prev = _to_float(record.get("previous_close"))
    if prev is None:
        prev = _to_float(record.get("previous_price"))
    pct = _to_float(record.get("price_change_pct"))

    r_1d: float | None = None
    if pct is not None:
        r_1d = pct / 100.0
    elif prev is not None and prev != 0.0:
        r_1d = (price - prev) / prev

    status = SCORED
    reason = "OK"
    if r_1d is not None:
        # No price window in a single record => normalise the 1-day return
        # against a conservative 2% reference move, then sigmoid-squash it.
        z_return = r_1d / 0.02
        momentum = sigmoid(z_return)
        event_magnitude = clip01(abs(r_1d) / 0.03)  # |move| vs 3% reference
    else:
        # Previous price unavailable — do not fabricate momentum.  Use the
        # loader's market_confirmation_score as a transparent proxy when present
        # and report PARTIAL_SCORE; otherwise it is SCORE_UNAVAILABLE.
        mcs = _to_float(record.get("market_confirmation_score"))
        if mcs is None:
            return _unavailable(
                source_name=source_name, source_type=src_type,
                reason="MISSING_PREVIOUS_PRICE", real_row=True,
            )
        momentum = clip01(mcs)
        event_magnitude = clip01(mcs)
        status = PARTIAL_SCORE
        reason = "PREVIOUS_PRICE_UNAVAILABLE_USED_CONFIRMATION_PROXY"

    # ----- VolumeScore ---------------------------------------------------- #
    vcr = _to_float(record.get("volume_change_ratio"))
    volume = _to_float(record.get("volume"))
    avg_volume = _to_float(record.get("average_volume"))
    if vcr is not None:
        volume_score: float | None = clip01(max(0.0, min(3.0, vcr)) / 3.0)
    elif volume is not None and avg_volume not in (None, 0.0):
        volume_score = clip01(max(0.0, min(3.0, volume / avg_volume)) / 3.0)
    else:
        volume_score = None

    EMS = clip01(momentum)
    EQS = clip01(R * F * schema_valid * dedup_integrity)
    DS = clip01(0.50 * abs(EMS - 0.5) * 2.0 + 0.30 * EQS + 0.20 * F)
    LS = clip01(volume_score) if volume_score is not None else clip01(0.5 * F)
    EFS = clip01(F * R * schema_valid)
    APS = clip01(0.40 * EMS + 0.30 * EQS + 0.30 * DS)

    vector.update({
        "EMS": EMS, "EQS": EQS, "DS": DS, "LS": LS, "EFS": EFS, "APS": APS,
        "score_status": status, "score_reason": reason,
    })
    return vector


def score_polymarket_row(
    record: Mapping[str, Any],
    *,
    source_name: str = "polymarket",
    now_iso: str | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Score a Polymarket prediction-market row.

    Required: an implied (YES-side) probability in [0, 1].
    """
    src_type = SOURCE_TYPE_PREDICTION_MARKET
    vector = _base_vector(
        source_name=source_name, source_type=src_type, real_row=True,
        mock_flag=False, backfill_flag=False,
    )
    now = _resolve_now(now_iso)
    R = r_source_for(source_name)

    p_market = _to_float(record.get("implied_probability"))
    if p_market is None:
        p_market = _to_float(record.get("p_market"))
    if p_market is None or not (0.0 <= p_market <= 1.0):
        return _unavailable(
            source_name=source_name, source_type=src_type,
            reason="MISSING_PROBABILITY", real_row=True,
        )

    ts = record.get("timestamp") or fetched_at
    age = _age_hours(ts, now)
    timestamp_valid = age is not None
    F = freshness_score(age, ttl_hours)
    schema_valid = 1.0 if (timestamp_valid and bool(source_name)) else 0.0
    dedup_integrity = 1.0

    # ----- MomentumScore -------------------------------------------------- #
    prev_p = _to_float(record.get("previous_implied_probability"))
    if prev_p is None:
        prev_p = _to_float(record.get("previous_p"))
    if prev_p is not None and 0.0 <= prev_p <= 1.0:
        momentum = clip01(abs(p_market - prev_p) / 0.10)
    else:
        momentum = clip01(abs(p_market - 0.5) * 2.0)

    # ----- LiquidityScore ------------------------------------------------- #
    liquidity = _to_float(record.get("liquidity"))
    if liquidity is None:
        liquidity = _to_float(record.get("volume"))
    if liquidity is not None and liquidity >= 0.0:
        liquidity_score = clip01(math.log1p(liquidity) / math.log1p(LIQUIDITY_REF))
    else:
        liquidity_score = 0.0

    EMS = clip01(momentum)
    EQS = clip01(R * F * schema_valid * dedup_integrity)
    DS = clip01(0.45 * momentum + 0.35 * liquidity_score + 0.20 * EQS)
    LS = clip01(liquidity_score)
    EFS = clip01(F * R * schema_valid)
    APS = clip01(0.40 * momentum + 0.30 * EQS + 0.30 * liquidity_score)

    vector.update({
        "EMS": EMS, "EQS": EQS, "DS": DS, "LS": LS, "EFS": EFS, "APS": APS,
        "score_status": SCORED, "score_reason": "OK",
    })
    return vector


def score_sec_edgar_row(
    record: Mapping[str, Any],
    *,
    source_name: str = "sec_edgar",
    now_iso: str | None = None,
    ttl_hours: float = SEC_FILING_TTL_HOURS,
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Score an SEC EDGAR filing row.

    Required: a recognisable ``form_type`` and a parseable filing date.
    """
    src_type = SOURCE_TYPE_REGULATORY_FILING
    vector = _base_vector(
        source_name=source_name, source_type=src_type, real_row=True,
        mock_flag=False, backfill_flag=False,
    )
    now = _resolve_now(now_iso)
    R = r_source_for(source_name)

    form_type = record.get("form_type") or record.get("form")
    if not form_type:
        return _unavailable(
            source_name=source_name, source_type=src_type,
            reason="MISSING_FORM_TYPE", real_row=True,
        )

    ts = record.get("filing_date") or record.get("timestamp") or fetched_at
    age = _age_hours(ts, now)
    timestamp_valid = age is not None
    if not timestamp_valid:
        age = _age_hours(fetched_at, now)
        timestamp_valid = age is not None

    accession_present = bool(record.get("accession_number") or record.get("accession"))
    schema_valid = 1.0 if (timestamp_valid and bool(source_name) and accession_present) else 0.0

    materiality = sec_materiality(str(form_type))
    filing_freshness = freshness_score(age, ttl_hours)

    status = SCORED
    reason = "OK"
    if not timestamp_valid:
        status = PARTIAL_SCORE
        reason = "FILING_DATE_UNPARSABLE"

    EMS = clip01(materiality * filing_freshness)
    EQS = clip01(R * filing_freshness * schema_valid)
    DS = clip01(0.60 * materiality + 0.25 * EQS + 0.15 * filing_freshness)
    LS = clip01(0.5 * filing_freshness)
    EFS = clip01(filing_freshness * R * schema_valid)
    APS = clip01(0.50 * materiality + 0.30 * EQS + 0.20 * filing_freshness)

    vector.update({
        "EMS": EMS, "EQS": EQS, "DS": DS, "LS": LS, "EFS": EFS, "APS": APS,
        "score_status": status, "score_reason": reason,
    })
    return vector


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def score_signal_event(
    record: Mapping[str, Any],
    *,
    source_name: str | None = None,
    now_iso: str | None = None,
    ttl_hours: float | None = None,
    fetched_at: str | None = None,
    mock_flag: bool = False,
    backfill_flag: bool = False,
) -> dict[str, Any]:
    """Score one real canonical signal-event record into a six-axis vector.

    ``mock``/``backfill`` rows are honestly refused: a mock row never scores as
    real, and a backfill row never scores as fresh-live.  Both return a fully
    stamped SCORE_UNAVAILABLE envelope (axes None) so the caller can record the
    honest reason without ever feeding a fabricated probability downstream.
    """
    if not isinstance(record, Mapping):
        return _unavailable(
            source_name=str(source_name or ""), source_type=SOURCE_TYPE_UNKNOWN,
            reason="RECORD_NOT_A_MAPPING", real_row=False,
        )

    resolved_source = str(
        source_name or record.get("source_name") or record.get("source") or ""
    ).strip()
    src_type = source_type_for(resolved_source)

    if mock_flag:
        return _unavailable(
            source_name=resolved_source, source_type=src_type,
            reason="MOCK_ROW_NOT_REAL", real_row=False,
            mock_flag=True, backfill_flag=bool(backfill_flag),
        )
    if backfill_flag:
        return _unavailable(
            source_name=resolved_source, source_type=src_type,
            reason="BACKFILL_ROW_NOT_FRESH_LIVE", real_row=False,
            mock_flag=False, backfill_flag=True,
        )
    if not resolved_source:
        return _unavailable(
            source_name="", source_type=SOURCE_TYPE_UNKNOWN,
            reason="MISSING_SOURCE_NAME", real_row=False,
        )

    if src_type == SOURCE_TYPE_MARKET:
        return score_market_row(
            record, source_name=resolved_source, now_iso=now_iso,
            ttl_hours=ttl_hours if ttl_hours is not None else DEFAULT_TTL_HOURS,
            fetched_at=fetched_at,
        )
    if src_type == SOURCE_TYPE_PREDICTION_MARKET:
        return score_polymarket_row(
            record, source_name=resolved_source, now_iso=now_iso,
            ttl_hours=ttl_hours if ttl_hours is not None else DEFAULT_TTL_HOURS,
            fetched_at=fetched_at,
        )
    if src_type == SOURCE_TYPE_REGULATORY_FILING:
        return score_sec_edgar_row(
            record, source_name=resolved_source, now_iso=now_iso,
            ttl_hours=ttl_hours if ttl_hours is not None else SEC_FILING_TTL_HOURS,
            fetched_at=fetched_at,
        )

    return _unavailable(
        source_name=resolved_source, source_type=src_type,
        reason=f"UNSUPPORTED_SOURCE_TYPE:{src_type}", real_row=False,
    )


__all__ = [
    "SCORING_VERSION",
    "MODEL_VERSION",
    "SCORED",
    "PARTIAL_SCORE",
    "SCORE_UNAVAILABLE",
    "DEFAULT_TTL_HOURS",
    "SEC_FILING_TTL_HOURS",
    "LIQUIDITY_REF",
    "R_SOURCE",
    "SOURCE_TYPE_MARKET",
    "SOURCE_TYPE_PREDICTION_MARKET",
    "SOURCE_TYPE_REGULATORY_FILING",
    "SOURCE_TYPE_NEWS",
    "SOURCE_TYPE_UNKNOWN",
    "clip01",
    "sigmoid",
    "freshness_score",
    "r_source_for",
    "source_type_for",
    "sec_materiality",
    "score_key",
    "axes_complete",
    "axes_dict",
    "score_market_row",
    "score_polymarket_row",
    "score_sec_edgar_row",
    "score_signal_event",
]
