"""Kronos price-path *evidence* layer — advisory-only, read-only.

KRONOS_PRICE_PATH_EVIDENCE
==========================

This is the **internal math/helper module** behind the canonical runtime
integration point, :class:`scripts.external_adapters.kronos_adapter.KronosAdapter`.
It is *not* a standalone runtime path: ``KronosAdapter.collect()`` imports
:func:`generate_evidence` / :func:`apply_kronos_to_signal` here and wraps the
result in the repo's canonical ``ExternalEvidence(CANDLESTICK_FORECAST)``
contract, which is then routed by
:class:`scripts.core.external_evidence_router.ExternalEvidenceRouter`.  Do not
add a second consumer that bypasses the adapter.

It integrates the Kronos financial K-line foundation model
(https://github.com/shiyu-coder/Kronos) into the Sleeping Passenger
advisory signal-refinery as a **technical witness, not the judge**.

It answers exactly one question::

    "Does the recent OHLCV / candlestick price path AGREE with an
     already-existing candidate signal thesis?"

It must NEVER answer "should we buy / sell / enter / execute".  Kronos
here is a read-only forecast layer that turns recent OHLCV into a small
set of *evidence fields* and an advisory *classification*.  It can only
nudge an existing advisory score within hard caps; it can never create a
trade, raise leverage, override a chaos/safety veto, place a broker
order, or run autonomous execution.

Allowed output labels
---------------------
SUPPORTIVE, CONTRADICTORY, UNSTABLE, NOISY, INSUFFICIENT_DATA,
DISABLED, ERROR_SAFE.

Forbidden output labels (never produced by this module)
------------------------------------------------------
BUY, SELL, ENTER, EXIT_NOW, EXECUTE, PLACE_ORDER, AUTO_TRADE.

Modes
-----
* ``DISABLED``       — ``KRONOS_ENABLED`` is not true.  Zero decision impact.
* ``STUB_SAFE``      — Kronos package/model unavailable; a deterministic,
  dependency-free extrapolation is used so tests + CI stay green without
  any Hugging Face download.
* ``LIVE_ADVISORY``  — Kronos tokenizer + model are available locally and a
  real forecast is produced.  Still advisory-only.

Contract — read-only / safe-on-failure
--------------------------------------
* Importing this module has no side effects and never imports a broker
  library.  Heavy ML deps (torch / Kronos) are imported lazily, inside a
  ``try/except`` so a missing dependency degrades to ``STUB_SAFE`` /
  ``ERROR_SAFE`` rather than hard-failing the repo.
* Every output carries the canonical advisory safety stamps:
  ``advisory_only=True``, ``human_execution_required=True``,
  ``execution_gate="LOCKED"``, ``broker_api_called=False``,
  ``ai_execution_count=0``.

Mathematics (see docs/KRONOS_PRICE_PATH_EVIDENCE.md)
---------------------------------------------------
Observed closes ``C_t`` for ``t = 1..T``; Kronos forecast closes
``F_{T+h}`` for ``h = 1..H`` with ``F_T = C_T``.

    R_f                    = (F_{T+H} - C_T) / C_T            forecast return
    forecast_return_pct    = 100 * R_f
    r_h                    = (F_{T+h} - F_{T+h-1}) / F_{T+h-1}
    sigma_f                = sqrt( (1/max(H-1,1)) * Σ (r_h - mean(r))^2 )
    forecast_volatility_pct= 100 * sigma_f
    peak_h                 = max(F_T, ..., F_{T+h})
    drawdown_h             = (F_{T+h} - peak_h) / peak_h
    MDD_f                  = min_h drawdown_h
    downside_path_risk     = clip(|min(MDD_f,0)| / D_ref, 0, 1)
    upside_path_score      = clip(max(R_f,0) / U_ref, 0, 1)
    noise_ratio            = forecast_volatility_pct / max(|forecast_return_pct|, eps)
    noise_penalty          = MAX_NOISE_PENALTY * clip((noise_ratio-1.5)/3.0, 0, 1)
    confidence_raw         = clip(0.40*|R_f|/U_ref + 0.30*upside_path_score
                                  + 0.30*(1-downside_path_risk), 0, 1)
    confidence_calibrated  = clip(confidence_raw * calibration_multiplier, 0, 1)
    alignment_bonus        = I(agree)*MAX_ALIGNMENT_BONUS*confidence_calibrated
                              *(1-downside_path_risk)
                              *(1 - min(noise_penalty/MAX_NOISE_PENALTY, 1))
    downside_penalty       = MAX_DOWNSIDE_PENALTY*downside_path_risk
                              *max(confidence_calibrated, 0.25)
    final_score_delta      = clip(alignment_bonus - downside_penalty
                                  - noise_penalty, -1.00, +0.50)

Kronos can help by at most +0.50 and hurt by up to -1.00 — it is a
stronger risk-reducer than hype-booster, by design.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

# Optional heavy dependency.  Imported lazily (NOT at module import time) so
# that the always-loaded adapter package — which imports this helper — does not
# pay torch's import cost.  A missing torch must degrade to STUB_SAFE, never
# hard-fail import.
_TORCH_UNSET: Any = object()
_torch_cache: Any = _TORCH_UNSET


def _get_torch() -> Any:
    """Lazily import torch once; return the module or ``None`` if absent."""
    global _torch_cache
    if _torch_cache is _TORCH_UNSET:
        try:  # pragma: no cover - depends on local install
            import torch as _t  # type: ignore
        except Exception:  # noqa: BLE001 - any failure means "unavailable"
            _t = None
        _torch_cache = _t
    return _torch_cache

try:
    from scripts.advisory_contract import (
        advisory_safety_stamps as _advisory_safety_stamps,
    )
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    try:
        from advisory_contract import (  # type: ignore[no-redef]
            advisory_safety_stamps as _advisory_safety_stamps,
        )
    except ModuleNotFoundError:  # pragma: no cover - contract optional

        def _advisory_safety_stamps() -> dict[str, Any]:  # type: ignore[misc]
            return {
                "advisory_status": "ADVISORY_ONLY",
                "execution_gate": "LOCKED",
                "broker_api_called": False,
                "ai_execution_count": 0,
                "execution_permission": False,
                "can_execute": False,
                "broker_order_id": "NONE",
                "human_review_required": True,
            }


# ---------------------------------------------------------------------------
# Status / mode / class vocabulary
# ---------------------------------------------------------------------------

STATUS_SUPPORTIVE = "SUPPORTIVE"
STATUS_CONTRADICTORY = "CONTRADICTORY"
STATUS_UNSTABLE = "UNSTABLE"
STATUS_NOISY = "NOISY"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_DISABLED = "DISABLED"
STATUS_ERROR_SAFE = "ERROR_SAFE"

ALLOWED_STATUSES: tuple[str, ...] = (
    STATUS_SUPPORTIVE,
    STATUS_CONTRADICTORY,
    STATUS_UNSTABLE,
    STATUS_NOISY,
    STATUS_INSUFFICIENT_DATA,
    STATUS_DISABLED,
    STATUS_ERROR_SAFE,
)

# Labels this module is structurally forbidden from ever emitting as a
# status.  Kept here so the self-tests can assert no output ever lands on
# an execution instruction.
FORBIDDEN_STATUS_LABELS: tuple[str, ...] = (
    "BUY",
    "SELL",
    "ENTER",
    "EXIT_NOW",
    "EXECUTE",
    "PLACE_ORDER",
    "AUTO_TRADE",
)

MODE_DISABLED = "disabled"
MODE_STUB_SAFE = "stub_safe"
MODE_LIVE_ADVISORY = "live_advisory"

# Safety / decision-role constants — these are invariant in this MVP.
USED_IN_DECISION_EVIDENCE_ONLY = "EVIDENCE_ONLY"
EXECUTION_GATE_LOCKED = "LOCKED"
PROOF_OK = "OK_ADVISORY_EVIDENCE"
PROOF_DISABLED = "DISABLED_NO_DECISION_IMPACT"
PROOF_INSUFFICIENT = "INSUFFICIENT_DATA_NO_DECISION_IMPACT"
PROOF_ERROR_SAFE = "FAILED_SAFE_NO_DECISION_IMPACT"
PROOF_ERROR_SAFE_ALT = "ERROR_SAFE_NO_DECISION_IMPACT"

# Advisory signal classes used by the gating helper (Section 7).  These
# mirror the repo's existing veto vocabulary; Kronos can never upgrade
# past any of them.
CLASS_WATCHLIST = "WATCHLIST"
CLASS_BUY_CANDIDATE = "BUY-CANDIDATE"
SAFETY_VETO_CLASSES: frozenset[str] = frozenset(
    {"DIABLO", "NO_NEW_RISK", "CHAOS_VETO"}
)
WARNING_NO_NEW_RISK = "NO_NEW_RISK"


# ---------------------------------------------------------------------------
# Tunable constants — overridable via env (Section 3)
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "KRONOS_ENABLED": "false",
    "KRONOS_MODEL_NAME": "NeoQuasar/Kronos-small",
    "KRONOS_TOKENIZER_NAME": "NeoQuasar/Kronos-Tokenizer-base",
    "KRONOS_MODE": "stub_safe",
    "KRONOS_DEVICE": "auto",
    "KRONOS_MAX_CONTEXT": "512",
    "KRONOS_DEFAULT_HORIZON_BARS": "20",
    "KRONOS_MIN_LOOKBACK_BARS": "120",
    "KRONOS_MAX_LOOKBACK_BARS": "512",
    "KRONOS_MAX_ALIGNMENT_BONUS": "0.50",
    "KRONOS_MAX_DOWNSIDE_PENALTY": "0.75",
    "KRONOS_MAX_NOISE_PENALTY": "0.50",
}

# Reference scales for normalising drawdown / upside, per asset class.
# Configurable via KRONOS_D_REF / KRONOS_U_REF (global override) — kept
# narrow on purpose.
_DREF_EQUITY_DEFAULT = 0.08
_UREF_EQUITY_DEFAULT = 0.10
_DREF_CRYPTO_DEFAULT = 0.12
_UREF_CRYPTO_DEFAULT = 0.15

_CRYPTO_ASSET_CLASSES: frozenset[str] = frozenset(
    {"crypto", "cryptocurrency", "digital_asset", "coin", "token"}
)

# Directional + noise thresholds (Section 5).
_THETA_RETURN_PCT = 0.50  # |forecast_return_pct| threshold for a direction
_NOISE_EPSILON_PCT = 0.25  # division floor in noise_ratio
_CALIBRATION_DEFAULT = 0.50  # no-history haircut

# Status thresholds (Section 6).
_UNSTABLE_DOWNSIDE_RISK = 0.70
_NOISY_PENALTY_FLOOR = 0.35


def _env(name: str) -> str:
    return str(os.environ.get(name, _DEFAULTS.get(name, ""))).strip()


def _env_float(name: str) -> float:
    try:
        return float(_env(name))
    except (TypeError, ValueError):
        return float(_DEFAULTS.get(name, 0.0) or 0.0)


def _env_int(name: str) -> int:
    try:
        return int(float(_env(name)))
    except (TypeError, ValueError):
        return int(float(_DEFAULTS.get(name, 0) or 0))


def kronos_enabled() -> bool:
    return _env("KRONOS_ENABLED").lower() in {"1", "true", "yes", "on"}


def resolve_mode() -> str:
    """Resolve the operating mode from env.

    ``DISABLED`` wins whenever ``KRONOS_ENABLED`` is not true, regardless
    of ``KRONOS_MODE``.  Otherwise the requested mode is honoured, with
    ``LIVE_ADVISORY`` silently degrading to ``STUB_SAFE`` when the Kronos
    package / torch are not importable.
    """
    if not kronos_enabled():
        return MODE_DISABLED
    requested = _env("KRONOS_MODE").lower()
    if requested == MODE_LIVE_ADVISORY:
        if _get_torch() is None or not _kronos_package_available():
            return MODE_STUB_SAFE
        return MODE_LIVE_ADVISORY
    if requested == MODE_DISABLED:
        # Enabled but explicitly mode=disabled is contradictory; treat the
        # explicit ENABLED flag as authoritative and fall back to stub.
        return MODE_STUB_SAFE
    return MODE_STUB_SAFE


def _kronos_package_available() -> bool:
    """True if the Kronos model package looks importable (cheap check)."""
    import importlib.util

    try:
        return importlib.util.find_spec("model") is not None or (
            importlib.util.find_spec("kronos") is not None
        )
    except Exception:  # noqa: BLE001
        return False


def live_available() -> bool:
    """True iff a real Kronos forecast can run locally (torch + package).

    Used by :class:`KronosAdapter` to decide between LIVE_ADVISORY and the
    deterministic STUB_SAFE forecast without consulting ``KRONOS_ENABLED``
    (the adapter's own ``enabled`` config is the runtime gate).
    """
    return _get_torch() is not None and _kronos_package_available()


def _refs_for(asset_class: Optional[str]) -> tuple[float, float]:
    """Return ``(D_ref, U_ref)`` for an asset class, honouring env overrides."""
    ac = str(asset_class or "").strip().lower()
    if ac in _CRYPTO_ASSET_CLASSES:
        d_ref, u_ref = _DREF_CRYPTO_DEFAULT, _UREF_CRYPTO_DEFAULT
    else:
        d_ref, u_ref = _DREF_EQUITY_DEFAULT, _UREF_EQUITY_DEFAULT
    env_d = os.environ.get("KRONOS_D_REF")
    env_u = os.environ.get("KRONOS_U_REF")
    if env_d:
        try:
            d_ref = float(env_d)
        except ValueError:
            pass
    if env_u:
        try:
            u_ref = float(env_u)
        except ValueError:
            pass
    # Guard against zero/negative references blowing up the division.
    d_ref = d_ref if d_ref > 1e-9 else _DREF_EQUITY_DEFAULT
    u_ref = u_ref if u_ref > 1e-9 else _UREF_EQUITY_DEFAULT
    return d_ref, u_ref


def _clip(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


# ---------------------------------------------------------------------------
# Data structures (Section 4)
# ---------------------------------------------------------------------------


@dataclass
class KronosOHLCVBar:
    timestamp_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None


@dataclass
class KronosEvidenceRequest:
    ticker: str
    asset_class: str
    bars: list[KronosOHLCVBar]
    existing_signal_score: float
    existing_signal_class: str
    jurisdiction: Optional[str] = None
    prediction_horizon_bars: int = 0
    market_regime: Optional[str] = None
    source_signal_id: Optional[str] = None
    model_name: Optional[str] = None
    advisory_only: bool = True


@dataclass
class KronosEvidence:
    ticker: str
    status: str
    model_name: str
    tokenizer_name: str
    lookback_bars: int
    prediction_horizon_bars: int
    forecast_return_pct: Optional[float]
    forecast_volatility_pct: Optional[float]
    downside_path_risk: Optional[float]
    upside_path_score: Optional[float]
    directional_agreement: Optional[bool]
    confidence_raw: Optional[float]
    confidence_calibrated: Optional[float]
    alignment_bonus: float
    downside_penalty: float
    noise_penalty: float
    final_score_delta: float
    reason: str
    proof_status: str
    generated_at_utc: str
    used_in_decision: str = USED_IN_DECISION_EVIDENCE_ONLY
    advisory_only: bool = True
    human_execution_required: bool = True
    execution_gate: str = EXECUTION_GATE_LOCKED
    broker_api_called: bool = False
    ai_execution_count: int = 0
    mode: str = MODE_DISABLED
    sign_forecast: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict with canonical advisory stamps merged.

        The hard safety invariants are *re-stamped* here so the returned
        dict can never disagree with the contract even if a field were
        mutated upstream.
        """
        out: dict[str, Any] = {
            "ticker": self.ticker,
            "status": self.status,
            "mode": self.mode,
            "model_name": self.model_name,
            "tokenizer_name": self.tokenizer_name,
            "lookback_bars": self.lookback_bars,
            "prediction_horizon_bars": self.prediction_horizon_bars,
            "forecast_return_pct": self.forecast_return_pct,
            "forecast_volatility_pct": self.forecast_volatility_pct,
            "downside_path_risk": self.downside_path_risk,
            "upside_path_score": self.upside_path_score,
            "directional_agreement": self.directional_agreement,
            "sign_forecast": self.sign_forecast,
            "confidence_raw": self.confidence_raw,
            "confidence_calibrated": self.confidence_calibrated,
            "alignment_bonus": self.alignment_bonus,
            "downside_penalty": self.downside_penalty,
            "noise_penalty": self.noise_penalty,
            "final_score_delta": self.final_score_delta,
            "used_in_decision": USED_IN_DECISION_EVIDENCE_ONLY,
            "reason": self.reason,
            "proof_status": self.proof_status,
            "generated_at_utc": self.generated_at_utc,
        }
        # Hard, non-negotiable safety stamps — always re-applied.
        out.update(_advisory_safety_stamps())
        out["advisory_only"] = True
        out["human_execution_required"] = True
        out["execution_gate"] = EXECUTION_GATE_LOCKED
        out["broker_api_called"] = False
        out["ai_execution_count"] = 0
        return out


# ---------------------------------------------------------------------------
# Forecast metrics (pure math, Section 5)
# ---------------------------------------------------------------------------


@dataclass
class _ForecastMetrics:
    forecast_return_pct: float
    forecast_volatility_pct: float
    downside_path_risk: float
    upside_path_score: float
    noise_ratio: float
    noise_penalty: float
    sign_forecast: int
    confidence_raw: float
    horizon: int


def compute_forecast_metrics(
    last_close: float,
    forecast_closes: Sequence[float],
    *,
    asset_class: Optional[str] = None,
) -> _ForecastMetrics:
    """Pure transform: observed last close + forecast closes -> metrics.

    ``forecast_closes`` are ``F_{T+1} .. F_{T+H}``.  The path used for the
    per-step return / drawdown maths prepends ``F_T = C_T = last_close``.
    """
    d_ref, u_ref = _refs_for(asset_class)
    closes = [float(c) for c in forecast_closes if c is not None]
    horizon = len(closes)
    if horizon == 0 or last_close <= 0:
        # Degenerate — treat as a flat, zero-information forecast.
        return _ForecastMetrics(
            forecast_return_pct=0.0,
            forecast_volatility_pct=0.0,
            downside_path_risk=0.0,
            upside_path_score=0.0,
            noise_ratio=0.0,
            noise_penalty=0.0,
            sign_forecast=0,
            confidence_raw=0.0,
            horizon=0,
        )

    path = [float(last_close)] + closes  # F_T, F_{T+1}, ..., F_{T+H}

    # Forecast return R_f = (F_{T+H} - C_T) / C_T
    r_f = (path[-1] - path[0]) / path[0]
    forecast_return_pct = 100.0 * r_f

    # Per-step returns r_h = (F_{T+h} - F_{T+h-1}) / F_{T+h-1}
    step_returns: list[float] = []
    for prev, cur in zip(path[:-1], path[1:]):
        if prev != 0:
            step_returns.append((cur - prev) / prev)
        else:
            step_returns.append(0.0)
    if step_returns:
        mean_r = sum(step_returns) / len(step_returns)
        var = sum((r - mean_r) ** 2 for r in step_returns) / max(horizon - 1, 1)
        sigma_f = math.sqrt(var)
    else:
        sigma_f = 0.0
    forecast_volatility_pct = 100.0 * sigma_f

    # Max drawdown over the forecast path.
    peak = path[0]
    mdd = 0.0
    for point in path:
        if point > peak:
            peak = point
        if peak > 0:
            drawdown = (point - peak) / peak
            if drawdown < mdd:
                mdd = drawdown
    downside_path_risk = _clip(abs(min(mdd, 0.0)) / d_ref, 0.0, 1.0)

    upside_path_score = _clip(max(r_f, 0.0) / u_ref, 0.0, 1.0)

    noise_ratio = forecast_volatility_pct / max(
        abs(forecast_return_pct), _NOISE_EPSILON_PCT
    )
    max_noise = _env_float("KRONOS_MAX_NOISE_PENALTY")
    noise_penalty = max_noise * _clip((noise_ratio - 1.5) / 3.0, 0.0, 1.0)

    if forecast_return_pct >= _THETA_RETURN_PCT:
        sign_forecast = 1
    elif forecast_return_pct <= -_THETA_RETURN_PCT:
        sign_forecast = -1
    else:
        sign_forecast = 0

    confidence_raw = _clip(
        0.40 * (abs(r_f) / u_ref)
        + 0.30 * upside_path_score
        + 0.30 * (1.0 - downside_path_risk),
        0.0,
        1.0,
    )

    return _ForecastMetrics(
        forecast_return_pct=forecast_return_pct,
        forecast_volatility_pct=forecast_volatility_pct,
        downside_path_risk=downside_path_risk,
        upside_path_score=upside_path_score,
        noise_ratio=noise_ratio,
        noise_penalty=noise_penalty,
        sign_forecast=sign_forecast,
        confidence_raw=confidence_raw,
        horizon=horizon,
    )


# ---------------------------------------------------------------------------
# Forecast producers
# ---------------------------------------------------------------------------


def _stub_forecast_closes(
    bars: Sequence[KronosOHLCVBar], horizon: int
) -> list[float]:
    """Deterministic, dependency-free forecast used by STUB_SAFE / CI.

    Persistence-style extrapolation: continue the recent average log-return
    drift forward ``horizon`` steps.  Pure and stable across platforms — it
    never downloads a model and never touches the network.  It is *not* a
    real forecast; LIVE_ADVISORY replaces it with the Kronos model output.
    """
    closes = [float(b.close) for b in bars if b.close and b.close > 0]
    if len(closes) < 2 or horizon <= 0:
        last = closes[-1] if closes else 0.0
        return [last] * max(horizon, 0)
    window = closes[-min(len(closes), 30):]
    log_returns = [
        math.log(cur / prev)
        for prev, cur in zip(window[:-1], window[1:])
        if prev > 0 and cur > 0
    ]
    drift = sum(log_returns) / len(log_returns) if log_returns else 0.0
    last = closes[-1]
    out: list[float] = []
    level = last
    for _ in range(horizon):
        level = level * math.exp(drift)
        out.append(level)
    return out


def _live_forecast_closes(
    request: KronosEvidenceRequest, horizon: int
) -> list[float]:  # pragma: no cover - requires torch + Kronos weights
    """Produce forecast closes via the real Kronos model (LIVE_ADVISORY).

    Imported lazily so a missing dependency degrades cleanly.  Any failure
    here propagates to :func:`generate_evidence`, which converts it to an
    ``ERROR_SAFE`` result with zero decision impact.  This function never
    places an order and never returns anything but a price-path forecast.
    """
    # Lazy import — kept inside the function so import-time stays dependency
    # free.  The exact import surface depends on how the operator vendored
    # the Kronos repo locally; both common layouts are attempted.
    KronosPredictor = None  # noqa: N806
    Kronos = None  # noqa: N806
    KronosTokenizer = None  # noqa: N806
    try:
        from model import Kronos, KronosPredictor, KronosTokenizer  # type: ignore
    except Exception:  # noqa: BLE001
        from kronos import (  # type: ignore
            Kronos,
            KronosPredictor,
            KronosTokenizer,
        )

    import pandas as pd  # type: ignore

    torch = _get_torch()
    model_name = request.model_name or _env("KRONOS_MODEL_NAME")
    tokenizer_name = _env("KRONOS_TOKENIZER_NAME")
    device = _env("KRONOS_DEVICE")
    if device == "auto":
        device = "cuda" if (torch is not None and torch.cuda.is_available()) else "cpu"

    max_context = _env_int("KRONOS_MAX_CONTEXT")
    bars = list(request.bars)[-max_context:]

    tokenizer = KronosTokenizer.from_pretrained(tokenizer_name)
    model = Kronos.from_pretrained(model_name)
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=max_context)

    df = pd.DataFrame(
        {
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
            "amount": [
                float(b.amount) if b.amount is not None else float(b.volume)
                for b in bars
            ],
        }
    )
    timestamps = pd.to_datetime([b.timestamp_utc for b in bars], utc=True, errors="coerce")
    # Forecast timestamps are advisory placeholders; the model only needs a
    # monotonically increasing index of length ``horizon``.
    freq = timestamps[-1] - timestamps[-2] if len(timestamps) >= 2 else pd.Timedelta(days=1)
    pred_index = pd.date_range(
        start=timestamps[-1] + freq, periods=horizon, freq=freq
    )

    pred_df = predictor.predict(
        df=df,
        x_timestamp=pd.Series(timestamps),
        y_timestamp=pd.Series(pred_index),
        pred_len=horizon,
    )
    return [float(v) for v in list(pred_df["close"])]


def _now_utc() -> str:
    try:
        from scripts.runtime_common import utc_timestamp  # type: ignore

        return utc_timestamp()
    except Exception:  # noqa: BLE001
        try:
            from runtime_common import utc_timestamp  # type: ignore

            return utc_timestamp()
        except Exception:  # noqa: BLE001
            import datetime as _dt

            return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Evidence generation (Sections 5 + 6)
# ---------------------------------------------------------------------------


def _disabled_evidence(
    request: KronosEvidenceRequest, *, mode: str, reason: str, proof: str, status: str
) -> KronosEvidence:
    """Build a zero-impact evidence object (DISABLED / INSUFFICIENT / ERROR)."""
    return KronosEvidence(
        ticker=request.ticker,
        status=status,
        mode=mode,
        model_name=request.model_name or _env("KRONOS_MODEL_NAME"),
        tokenizer_name=_env("KRONOS_TOKENIZER_NAME"),
        lookback_bars=len(request.bars or []),
        prediction_horizon_bars=_effective_horizon(request),
        forecast_return_pct=None,
        forecast_volatility_pct=None,
        downside_path_risk=None,
        upside_path_score=None,
        directional_agreement=None,
        sign_forecast=0,
        confidence_raw=None,
        confidence_calibrated=None,
        alignment_bonus=0.0,
        downside_penalty=0.0,
        noise_penalty=0.0,
        final_score_delta=0.0,
        reason=reason,
        proof_status=proof,
        generated_at_utc=_now_utc(),
    )


def _effective_horizon(request: KronosEvidenceRequest) -> int:
    h = int(request.prediction_horizon_bars or 0)
    if h <= 0:
        h = _env_int("KRONOS_DEFAULT_HORIZON_BARS")
    return max(h, 1)


def generate_evidence(
    request: KronosEvidenceRequest,
    *,
    forecast_closes: Optional[Sequence[float]] = None,
    forecast_fn: Optional[Callable[[KronosEvidenceRequest, int], Sequence[float]]] = None,
    calibration_multiplier: Optional[float] = None,
    mode: Optional[str] = None,
) -> KronosEvidence:
    """Produce a :class:`KronosEvidence` for an existing candidate signal.

    Parameters
    ----------
    request:
        The candidate signal + OHLCV context.
    forecast_closes:
        Optional explicit forecast path (``F_{T+1}..F_{T+H}``).  When given
        it bypasses both the stub and live producers — this is how the
        deterministic unit tests inject a known path.
    forecast_fn:
        Optional callable producing the forecast path.  Used by tests to
        force a failure (it may raise) so the ``ERROR_SAFE`` branch can be
        exercised without a real model.
    calibration_multiplier:
        Moltbook-derived confidence haircut.  Defaults to ``0.50`` (no
        prior proof => Kronos confidence is halved).
    mode:
        Explicit operating mode (``stub_safe`` / ``live_advisory`` /
        ``disabled``).  When ``None`` (the default) it is resolved from the
        ``KRONOS_ENABLED`` / ``KRONOS_MODE`` env.  :class:`KronosAdapter`
        passes this explicitly so the adapter's own ``enabled`` config — not
        a separate env var — is the single runtime gate.
    """
    mode = mode or resolve_mode()
    horizon = _effective_horizon(request)

    # --- DISABLED ----------------------------------------------------------
    if mode == MODE_DISABLED:
        return _disabled_evidence(
            request,
            mode=mode,
            reason=(
                "Kronos is disabled (KRONOS_ENABLED is not true). "
                "Evidence only; no decision impact."
            ),
            proof=PROOF_DISABLED,
            status=STATUS_DISABLED,
        )

    bars = list(request.bars or [])
    min_lookback = _env_int("KRONOS_MIN_LOOKBACK_BARS")

    # --- INSUFFICIENT_DATA -------------------------------------------------
    if not bars or len(bars) < min_lookback:
        return _disabled_evidence(
            request,
            mode=mode,
            reason=(
                f"Insufficient OHLCV history: have {len(bars)} bar(s), need "
                f">= {min_lookback}. Evidence only; no decision impact."
            ),
            proof=PROOF_INSUFFICIENT,
            status=STATUS_INSUFFICIENT_DATA,
        )

    # --- Resolve a forecast path; any failure => ERROR_SAFE ----------------
    try:
        if forecast_closes is not None:
            closes = list(forecast_closes)
        elif forecast_fn is not None:
            closes = list(forecast_fn(request, horizon))
        elif mode == MODE_LIVE_ADVISORY:
            closes = list(_live_forecast_closes(request, horizon))
        else:  # STUB_SAFE
            closes = list(_stub_forecast_closes(bars, horizon))
        if not closes:
            raise ValueError("empty forecast path")
    except Exception as exc:  # noqa: BLE001 - degrade safely on ANY failure
        ev = _disabled_evidence(
            request,
            mode=mode,
            reason=(
                "Kronos forecast failed; degraded safe. Evidence only; no "
                f"decision impact. ({type(exc).__name__})"
            ),
            proof=PROOF_ERROR_SAFE,
            status=STATUS_ERROR_SAFE,
        )
        return ev

    last_close = float(bars[-1].close)
    metrics = compute_forecast_metrics(
        last_close, closes, asset_class=request.asset_class
    )

    # Calibrated confidence — no-history haircut by default.
    cal = (
        float(calibration_multiplier)
        if calibration_multiplier is not None
        else _CALIBRATION_DEFAULT
    )
    confidence_calibrated = _clip(metrics.confidence_raw * cal, 0.0, 1.0)

    # Directional agreement vs the long-only advisory signal (sign_signal=+1).
    sign_signal = 1
    directional_agreement = metrics.sign_forecast == sign_signal

    max_align = _env_float("KRONOS_MAX_ALIGNMENT_BONUS")
    max_down = _env_float("KRONOS_MAX_DOWNSIDE_PENALTY")
    max_noise = _env_float("KRONOS_MAX_NOISE_PENALTY")

    noise_attenuation = 1.0 - min(
        metrics.noise_penalty / max_noise if max_noise > 0 else 0.0, 1.0
    )
    alignment_bonus = (
        (max_align if directional_agreement else 0.0)
        * confidence_calibrated
        * (1.0 - metrics.downside_path_risk)
        * noise_attenuation
    )
    downside_penalty = (
        max_down * metrics.downside_path_risk * max(confidence_calibrated, 0.25)
    )
    final_score_delta = _clip(
        alignment_bonus - downside_penalty - metrics.noise_penalty,
        -1.00,
        0.50,
    )

    status, reason = _classify_status(
        metrics=metrics,
        directional_agreement=directional_agreement,
        final_score_delta=final_score_delta,
    )

    return KronosEvidence(
        ticker=request.ticker,
        status=status,
        mode=mode,
        model_name=request.model_name or _env("KRONOS_MODEL_NAME"),
        tokenizer_name=_env("KRONOS_TOKENIZER_NAME"),
        lookback_bars=len(bars),
        prediction_horizon_bars=metrics.horizon,
        forecast_return_pct=round(metrics.forecast_return_pct, 6),
        forecast_volatility_pct=round(metrics.forecast_volatility_pct, 6),
        downside_path_risk=round(metrics.downside_path_risk, 6),
        upside_path_score=round(metrics.upside_path_score, 6),
        directional_agreement=directional_agreement,
        sign_forecast=metrics.sign_forecast,
        confidence_raw=round(metrics.confidence_raw, 6),
        confidence_calibrated=round(confidence_calibrated, 6),
        alignment_bonus=round(alignment_bonus, 6),
        downside_penalty=round(downside_penalty, 6),
        noise_penalty=round(metrics.noise_penalty, 6),
        final_score_delta=round(final_score_delta, 6),
        reason=reason,
        proof_status=PROOF_OK,
        generated_at_utc=_now_utc(),
    )


def _classify_status(
    *,
    metrics: _ForecastMetrics,
    directional_agreement: bool,
    final_score_delta: float,
) -> tuple[str, str]:
    """Map metrics to an allowed status label (Section 6).

    Ordering is significant: instability and noise are evaluated *before*
    any supportive reading, so a structurally dangerous path can never be
    re-labelled SUPPORTIVE.
    """
    if metrics.downside_path_risk >= _UNSTABLE_DOWNSIDE_RISK:
        return (
            STATUS_UNSTABLE,
            (
                "Forecast path shows large drawdown "
                f"(downside_path_risk={metrics.downside_path_risk:.2f} "
                f">= {_UNSTABLE_DOWNSIDE_RISK}). Treat as destabilising; "
                "no-new-risk recommended."
            ),
        )
    if metrics.noise_penalty >= _NOISY_PENALTY_FLOOR:
        return (
            STATUS_NOISY,
            (
                "Forecast path is noisy relative to net move "
                f"(noise_ratio={metrics.noise_ratio:.2f}). Low-confidence "
                "evidence; human review recommended."
            ),
        )
    if directional_agreement and final_score_delta > 0:
        return (
            STATUS_SUPPORTIVE,
            (
                "Forecast path agrees with the existing long thesis "
                f"(forecast_return_pct={metrics.forecast_return_pct:.2f}). "
                "Small supportive evidence only; execution stays LOCKED."
            ),
        )
    if (not directional_agreement) and metrics.sign_forecast == -1:
        return (
            STATUS_CONTRADICTORY,
            (
                "Forecast path contradicts the existing long thesis "
                f"(forecast_return_pct={metrics.forecast_return_pct:.2f}). "
                "Human review required."
            ),
        )
    return (
        STATUS_NOISY,
        (
            "Forecast path is directionally inconclusive "
            f"(forecast_return_pct={metrics.forecast_return_pct:.2f}). "
            "Treated as noisy; no decision impact beyond evidence."
        ),
    )


# ---------------------------------------------------------------------------
# Hard gating (Section 7)
# ---------------------------------------------------------------------------


def apply_kronos_to_signal(
    base_signal: dict[str, Any],
    kronos_evidence: KronosEvidence,
    *,
    kronos_is_only_positive_evidence: bool = False,
) -> dict[str, Any]:
    """Apply Kronos evidence to a base advisory signal under hard gates.

    Kronos is *evidence, not authority*.  The returned dict carries the
    updated advisory score + class plus the rationale, but it can never:
      * upgrade a safety-veto class (DIABLO / NO_NEW_RISK / CHAOS_VETO),
      * lift a Kronos-only positive past WATCHLIST,
      * unlock execution, call a broker, or run autonomous execution.
    """
    base_score = float(base_signal.get("score", base_signal.get("signal_score", 0.0)) or 0.0)
    base_class = str(
        base_signal.get("signal_class", base_signal.get("class", "")) or ""
    ).strip()
    base_class_upper = base_class.upper()

    status = kronos_evidence.status
    delta = float(kronos_evidence.final_score_delta or 0.0)

    notes: list[str] = []
    human_review_required = bool(base_signal.get("human_review_required", False))

    # Rule 6 / no-impact statuses: score is unchanged.
    if status in {STATUS_ERROR_SAFE, STATUS_DISABLED, STATUS_INSUFFICIENT_DATA}:
        final_score = base_score
        final_class = base_class
        notes.append(
            f"Kronos {status}: no decision impact; final score equals base score."
        )
        proof = (
            PROOF_ERROR_SAFE_ALT
            if status == STATUS_ERROR_SAFE
            else kronos_evidence.proof_status
        )
        return _gated_result(
            base_score=base_score,
            final_score=final_score,
            base_class=base_class,
            final_class=final_class,
            status=status,
            delta=0.0,
            human_review_required=human_review_required,
            safety_veto_preserved=False,
            kronos_only_positive_evidence=False,
            notes=notes,
            proof=proof,
        )

    # Candidate score before gating.
    s_candidate = _clip(base_score + delta, 0.0, 10.0)

    safety_veto = base_class_upper in SAFETY_VETO_CLASSES
    final_class = base_class

    # Rule 4: contradictory => require human review.
    if status == STATUS_CONTRADICTORY:
        human_review_required = True
        notes.append("Kronos CONTRADICTORY: human review required.")

    # Rule 3: unstable => add/preserve a no-new-risk warning.
    if status == STATUS_UNSTABLE:
        human_review_required = True
        if not safety_veto:
            final_class = WARNING_NO_NEW_RISK
            notes.append(
                "Kronos UNSTABLE: NO_NEW_RISK warning applied "
                "(destabilising forecast path)."
            )
        else:
            notes.append("Kronos UNSTABLE: existing safety veto preserved.")

    # Rule 2 + formal safety-veto clamp: Kronos can never upgrade a veto.
    if safety_veto:
        final_score = min(s_candidate, base_score)
        final_class = base_class  # original veto class is authoritative
        notes.append(
            f"Safety veto ({base_class}) preserved: Kronos cannot upgrade a "
            "veto class; score capped at base."
        )
        return _gated_result(
            base_score=base_score,
            final_score=final_score,
            base_class=base_class,
            final_class=final_class,
            status=status,
            delta=round(final_score - base_score, 6),
            human_review_required=human_review_required,
            safety_veto_preserved=True,
            kronos_only_positive_evidence=False,
            notes=notes,
            proof=kronos_evidence.proof_status,
        )

    final_score = s_candidate

    # Rule 1: Kronos as the only positive evidence can never exceed WATCHLIST.
    kronos_only = bool(kronos_is_only_positive_evidence) and delta > 0
    if kronos_only:
        final_class = CLASS_WATCHLIST
        notes.append(
            "Kronos is the only positive evidence: capped at WATCHLIST "
            "(never BUY-CANDIDATE)."
        )

    # Rule 5: supportive only adds a small delta; execution stays LOCKED.
    if status == STATUS_SUPPORTIVE:
        notes.append(
            "Kronos SUPPORTIVE: small advisory score delta applied; "
            "execution gate stays LOCKED."
        )

    return _gated_result(
        base_score=base_score,
        final_score=final_score,
        base_class=base_class,
        final_class=final_class,
        status=status,
        delta=round(final_score - base_score, 6),
        human_review_required=human_review_required,
        safety_veto_preserved=False,
        kronos_only_positive_evidence=kronos_only,
        notes=notes,
        proof=kronos_evidence.proof_status,
    )


def _gated_result(
    *,
    base_score: float,
    final_score: float,
    base_class: str,
    final_class: str,
    status: str,
    delta: float,
    human_review_required: bool,
    safety_veto_preserved: bool,
    kronos_only_positive_evidence: bool,
    notes: list[str],
    proof: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "base_score": round(base_score, 6),
        "final_score": round(final_score, 6),
        "base_signal_class": base_class,
        "final_signal_class": final_class,
        "kronos_status": status,
        "kronos_applied_delta": delta,
        "used_in_decision": USED_IN_DECISION_EVIDENCE_ONLY,
        "human_review_required": human_review_required,
        "safety_veto_preserved": safety_veto_preserved,
        "kronos_only_positive_evidence": kronos_only_positive_evidence,
        "notes": notes,
        "proof_status": proof,
    }
    out.update(_advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["execution_gate"] = EXECUTION_GATE_LOCKED
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    return out


__all__ = [
    "KronosOHLCVBar",
    "KronosEvidenceRequest",
    "KronosEvidence",
    "ALLOWED_STATUSES",
    "FORBIDDEN_STATUS_LABELS",
    "STATUS_SUPPORTIVE",
    "STATUS_CONTRADICTORY",
    "STATUS_UNSTABLE",
    "STATUS_NOISY",
    "STATUS_INSUFFICIENT_DATA",
    "STATUS_DISABLED",
    "STATUS_ERROR_SAFE",
    "MODE_DISABLED",
    "MODE_STUB_SAFE",
    "MODE_LIVE_ADVISORY",
    "kronos_enabled",
    "resolve_mode",
    "live_available",
    "compute_forecast_metrics",
    "generate_evidence",
    "apply_kronos_to_signal",
]
