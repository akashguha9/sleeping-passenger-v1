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


class KronosAdapter(ExternalAdapter):
    source_name = "kronos"
    evidence_type = ExternalEvidenceType.CANDLESTICK_FORECAST
    license_boundary = "MIT optional dependency"
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    def _load_rows(self, context: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
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
        if bool(self.config.get("lazy_import", True)) and bool(ctx.get("allow_optional_import", False)):
            try:
                importlib.import_module("kronos")
            except ModuleNotFoundError:
                warnings.append("optional kronos dependency not installed; using mock mode")
        raw = ctx.get("raw_payload")
        if isinstance(raw, list):
            return [dict(item) for item in raw if isinstance(item, dict)], warnings
        return [], warnings

    @staticmethod
    def _sanitize_action(raw_action: str, validation_flags: bool) -> str:
        action = safe_str(raw_action, "WATCH").upper()
        if action in {"BUY", "SELL", "LONG", "SHORT", "EXECUTE", "STRONG_BUY"}:
            return "WATCH"
        if action in {"WATCH", "HOLD", "REJECT"}:
            return action
        if action == "PAPER_TRADE" and validation_flags:
            return "WATCH"
        return "WATCH"

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []
        rows, warnings = self._load_rows(context)
        if not rows and not bool(self.config.get("mock_mode", True)):
            return [
                self.build_failure_evidence(
                    message="kronos input unavailable",
                    adapter_status=ExternalAdapterStatus.UNAVAILABLE,
                    data_truth_origin="mock_technical_evidence",
                    warnings=warnings,
                )
            ]
        errors: list[str] = []
        closes: list[float] = []
        highs: list[float] = []
        lows: list[float] = []
        opens: list[float] = []
        for row in rows:
            if not {"open", "high", "low", "close"}.issubset(row.keys()):
                errors.append("missing OHLC columns")
                continue
            opens.append(safe_float(row.get("open")))
            highs.append(safe_float(row.get("high")))
            lows.append(safe_float(row.get("low")))
            closes.append(safe_float(row.get("close")))
        if not closes:
            opens = [100.0]
            highs = [101.0]
            lows = [99.0]
            closes = [100.5]
            warnings.append("using mock technical evidence")
        forecast_delta = closes[-1] - opens[0]
        confidence = bounded_score(abs(forecast_delta) / max(abs(opens[0]), 1.0))
        raw_action = safe_str((context or {}).get("action") or ("BUY" if forecast_delta > 0 else "SELL"))
        sanitized_action = self._sanitize_action(raw_action, validation_flags=bool((context or {}).get("validation_flags", False)))
        payload = {
            "technical_evidence_only": True,
            "ohlc_count": len(closes),
            "forecast_direction": "UP" if forecast_delta >= 0 else "DOWN",
            "sanitized_action": sanitized_action,
            "close_mean": sum(closes) / len(closes),
            "range_mean": sum(h - l for h, l in zip(highs, lows, strict=False)) / len(closes),
        }
        return [
            self.build_evidence(
                normalized_payload=payload,
                data_truth_origin="model_forecast" if rows else "mock_technical_evidence",
                adapter_status=ExternalAdapterStatus.AVAILABLE if rows else ExternalAdapterStatus.DEGRADED,
                warnings=warnings,
                errors=errors,
                confidence_proxy=confidence,
                evidence_quality_score=bounded_score(0.45 + (0.25 if rows else 0.0)),
                context_tags=["technical_evidence_only", "watch_only", "mit_optional"],
            )
        ]
