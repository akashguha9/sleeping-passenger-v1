"""Kronos external adapter — the *canonical runtime integration* for Kronos.

This adapter is the single place Kronos enters the pipeline.  It owns the
Kronos price-path math by importing the internal helper
:mod:`scripts.kronos_price_path_evidence` and wrapping its output in the
repo's canonical :class:`ExternalEvidence` contract
(``evidence_type=CANDLESTICK_FORECAST``, ``execution_permission=WATCH_ONLY``).
The evidence is then routed by
:class:`scripts.core.external_evidence_router.ExternalEvidenceRouter`, which
caps candlestick-forecast evidence at ``WATCH`` and enforces Apollo / DIABLO
vetoes.

There is intentionally only ONE Kronos runtime path: config → registry →
``KronosAdapter`` → ``kronos_price_path_evidence`` helper → ``ExternalEvidence``
→ router.  Kronos never places an order, never unlocks execution, and (alone)
can never produce a paper trade.
"""
from __future__ import annotations

import csv
import importlib
from pathlib import Path
from typing import Any

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    bounded_score,
    safe_float,
    safe_str,
)

from scripts import kronos_price_path_evidence as kpe

# Statuses that represent a real forecast read (vs disabled / insufficient /
# error-safe), reused for adapter-status + quality scoring.
_REAL_FORECAST_STATUSES = frozenset(
    {
        kpe.STATUS_SUPPORTIVE,
        kpe.STATUS_CONTRADICTORY,
        kpe.STATUS_UNSTABLE,
        kpe.STATUS_NOISY,
    }
)

_ADVISORY_NOTICE = (
    "Kronos is advisory-only price-path evidence. "
    "It is not an execution provider."
)


class KronosAdapter(ExternalAdapter):
    source_name = "kronos"
    evidence_type = ExternalEvidenceType.CANDLESTICK_FORECAST
    license_boundary = "MIT optional dependency"
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    # ------------------------------------------------------------------ data
    def _load_rows(
        self, context: dict[str, Any] | None = None
    ) -> tuple[list[dict[str, Any]], list[str]]:
        ctx = context or {}
        warnings: list[str] = []
        if isinstance(ctx.get("ohlcv"), list):
            return [dict(item) for item in ctx["ohlcv"] if isinstance(item, dict)], warnings
        path_value = safe_str(ctx.get("path"))
        if path_value:
            path = Path(path_value)
            if path.exists():
                with path.open("r", encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    return [{str(k): v for k, v in row.items()} for row in reader], warnings
        if bool(self.config.get("lazy_import", True)) and bool(
            ctx.get("allow_optional_import", False)
        ):
            try:
                importlib.import_module("kronos")
            except ModuleNotFoundError:
                warnings.append("optional kronos dependency not installed; using stub mode")
        raw = ctx.get("raw_payload")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)], warnings
        return [], warnings

    @staticmethod
    def _rows_to_bars(rows: list[dict[str, Any]]) -> tuple[list[kpe.KronosOHLCVBar], list[str]]:
        bars: list[kpe.KronosOHLCVBar] = []
        errors: list[str] = []
        for row in rows:
            if not {"open", "high", "low", "close"}.issubset(row.keys()):
                errors.append("missing OHLC columns")
                continue
            amount = row.get("amount")
            bars.append(
                kpe.KronosOHLCVBar(
                    timestamp_utc=safe_str(row.get("timestamp_utc") or row.get("timestamp")),
                    open=safe_float(row.get("open")),
                    high=safe_float(row.get("high")),
                    low=safe_float(row.get("low")),
                    close=safe_float(row.get("close")),
                    volume=safe_float(row.get("volume")),
                    amount=safe_float(amount) if amount is not None else None,
                )
            )
        return bars, errors

    @staticmethod
    def _sanitize_action(raw_action: str, validation_flags: bool) -> str:
        """Collapse any incoming action to a WATCH-only advisory verb.

        Kronos never emits BUY/SELL/EXECUTE — those are forced to WATCH.
        """
        action = safe_str(raw_action, "WATCH").upper()
        if action in {"BUY", "SELL", "LONG", "SHORT", "EXECUTE", "STRONG_BUY"}:
            return "WATCH"
        if action in {"WATCH", "HOLD", "REJECT"}:
            return action
        if action == "PAPER_TRADE" and validation_flags:
            return "WATCH"
        return "WATCH"

    def _resolve_mode(self) -> str:
        """Adapter-driven mode: live only if requested AND importable."""
        live_requested = bool(self.config.get("live_advisory", False))
        if live_requested and kpe.live_available():
            return kpe.MODE_LIVE_ADVISORY
        return kpe.MODE_STUB_SAFE

    # --------------------------------------------------------------- collect
    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []

        ctx = context or {}
        rows, warnings = self._load_rows(ctx)
        if not rows and not bool(self.config.get("mock_mode", True)):
            return [
                self.build_failure_evidence(
                    message="kronos input unavailable",
                    adapter_status=ExternalAdapterStatus.UNAVAILABLE,
                    data_truth_origin="mock_technical_evidence",
                    warnings=warnings,
                )
            ]

        bars, errors = self._rows_to_bars(rows)
        mode = self._resolve_mode()

        request = kpe.KronosEvidenceRequest(
            ticker=safe_str(ctx.get("ticker"), "UNKNOWN"),
            asset_class=safe_str(ctx.get("asset_class"), "equity"),
            bars=bars,
            existing_signal_score=safe_float(ctx.get("existing_signal_score"), 0.0),
            existing_signal_class=safe_str(ctx.get("existing_signal_class"), "WATCHLIST"),
            prediction_horizon_bars=int(safe_float(ctx.get("prediction_horizon_bars"), 0)),
            source_signal_id=safe_str(ctx.get("source_signal_id")) or None,
        )

        cal = ctx.get("kronos_calibration_multiplier")
        evidence = kpe.generate_evidence(
            request,
            forecast_closes=ctx.get("forecast_closes"),
            calibration_multiplier=float(cal) if cal is not None else None,
            mode=mode,
        )

        # Apply the hard advisory gating (score delta + class/veto rules).
        # Still WATCH-only; the router has the final macro say.
        base_signal = {
            "score": request.existing_signal_score,
            "signal_class": request.existing_signal_class,
            "human_review_required": bool(ctx.get("human_review_required", False)),
        }
        gated = kpe.apply_kronos_to_signal(
            base_signal,
            evidence,
            kronos_is_only_positive_evidence=bool(
                ctx.get("kronos_is_only_positive_evidence", False)
            ),
        )

        real_forecast = evidence.status in _REAL_FORECAST_STATUSES
        fr = evidence.forecast_return_pct
        forecast_direction = (
            "UP" if (fr is not None and fr > 0)
            else "DOWN" if (fr is not None and fr < 0)
            else "FLAT"
        )
        raw_action = safe_str(ctx.get("action") or ("BUY" if (fr or 0.0) >= 0 else "SELL"))
        sanitized_action = self._sanitize_action(
            raw_action, validation_flags=bool(ctx.get("validation_flags", False))
        )

        payload: dict[str, Any] = {
            "technical_evidence_only": True,
            "ohlc_count": len(bars),
            "forecast_direction": forecast_direction,
            "sanitized_action": sanitized_action,
            # Rich Kronos metrics from the price-path math helper.
            "KRONOS_STATUS": evidence.status,
            "KRONOS_MODE": evidence.mode,
            "KRONOS_MODEL_NAME": evidence.model_name,
            "KRONOS_TOKENIZER_NAME": evidence.tokenizer_name,
            "KRONOS_LOOKBACK_BARS": evidence.lookback_bars,
            "KRONOS_PREDICTION_HORIZON_BARS": evidence.prediction_horizon_bars,
            "KRONOS_FORECAST_RETURN_PCT": evidence.forecast_return_pct,
            "KRONOS_FORECAST_VOLATILITY_PCT": evidence.forecast_volatility_pct,
            "KRONOS_DOWNSIDE_PATH_RISK": evidence.downside_path_risk,
            "KRONOS_UPSIDE_PATH_SCORE": evidence.upside_path_score,
            "KRONOS_DIRECTIONAL_AGREEMENT": evidence.directional_agreement,
            "KRONOS_CONFIDENCE_RAW": evidence.confidence_raw,
            "KRONOS_CONFIDENCE_CALIBRATED": evidence.confidence_calibrated,
            "KRONOS_ALIGNMENT_BONUS": evidence.alignment_bonus,
            "KRONOS_DOWNSIDE_PENALTY": evidence.downside_penalty,
            "KRONOS_NOISE_PENALTY": evidence.noise_penalty,
            "KRONOS_FINAL_SCORE_DELTA": evidence.final_score_delta,
            "KRONOS_PROOF_STATUS": evidence.proof_status,
            "KRONOS_USED_IN_DECISION": "EVIDENCE_ONLY",
            # Gated advisory application (advisory only — never an order).
            "KRONOS_BASE_SCORE": gated["base_score"],
            "KRONOS_CANDIDATE_FINAL_SCORE": gated["final_score"],
            "KRONOS_FINAL_SIGNAL_CLASS": gated["final_signal_class"],
            "KRONOS_SAFETY_VETO_PRESERVED": gated["safety_veto_preserved"],
            "human_review_required": gated["human_review_required"],
            # Hard, non-negotiable advisory stamps.
            "advisory_only": True,
            "human_execution_required": True,
            "execution_gate": "LOCKED",
            "broker_api_called": False,
            "ai_execution_count": 0,
        }

        if mode == kpe.MODE_LIVE_ADVISORY:
            data_truth_origin = "model_forecast"
        elif real_forecast:
            data_truth_origin = "stub_forecast"
        else:
            data_truth_origin = "mock_technical_evidence"

        if evidence.status == kpe.STATUS_ERROR_SAFE:
            adapter_status = ExternalAdapterStatus.DEGRADED
        elif real_forecast:
            adapter_status = ExternalAdapterStatus.AVAILABLE
        else:
            adapter_status = ExternalAdapterStatus.DEGRADED

        return [
            self.build_evidence(
                normalized_payload=payload,
                data_truth_origin=data_truth_origin,
                adapter_status=adapter_status,
                execution_permission=ExternalExecutionPermission.WATCH_ONLY,
                warnings=warnings,
                errors=errors,
                confidence_proxy=bounded_score(evidence.confidence_calibrated or 0.0),
                evidence_quality_score=bounded_score(0.45 + (0.25 if real_forecast else 0.0)),
                context_tags=[
                    "technical_evidence_only",
                    "watch_only",
                    "advisory_only",
                    "mit_optional",
                    f"kronos_{evidence.status.lower()}",
                ],
            )
        ]

    # ----------------------------------------------------------- healthcheck
    def healthcheck(self) -> dict[str, Any]:
        """Provider health folded into the canonical adapter surface.

        States mirror the prior standalone source-health module
        (DISABLED / MODEL_UNAVAILABLE / STUB_SAFE / LIVE_ADVISORY) but live
        here so there is no parallel health system.  None of these states
        ever implies broker connectivity.
        """
        enabled = bool(self.config.get("enabled", False))
        live_requested = bool(self.config.get("live_advisory", False))
        if not enabled:
            health_state = "DISABLED"
        elif live_requested and not kpe.live_available():
            health_state = "MODEL_UNAVAILABLE"
        elif live_requested:
            health_state = "LIVE_ADVISORY"
        else:
            health_state = "STUB_SAFE"
        return {
            "source": self.source_name,
            "status": self.status().value,
            "health_state": health_state,
            "license_boundary": self.license_boundary,
            "real_execution_allowed": False,
            "execution_permission": self.default_execution_permission.value,
            "advisory_only": True,
            "is_execution_provider": False,
            "broker_connected": False,
            "advisory_notice": _ADVISORY_NOTICE,
        }
