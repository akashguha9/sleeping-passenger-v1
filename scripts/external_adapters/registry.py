from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    validate_external_evidence,
)
from scripts.external_adapters.fincept_terminal_adapter import FinceptTerminalAdapter
from scripts.external_adapters.kronos_adapter import KronosAdapter
from scripts.external_adapters.poly_data_adapter import PolyDataAdapter
from scripts.external_adapters.tradingagents_adapter import TradingAgentsAdapter
from scripts.external_adapters.trendradar_adapter import TrendRadarAdapter

DEFAULT_EXTERNAL_ADAPTER_CONFIG: dict[str, Any] = {
    "external_adapters": {
        "poly_data": {
            "enabled": False,
            "mode": "csv_sidecar",
            "path_env": "POLY_DATA_PATH",
            "fallback_path": "external/poly_data",
            "max_rows": 5000,
            "real_execution_allowed": False,
        },
        "kronos": {
            "enabled": False,
            "mode": "optional_python",
            "lazy_import": True,
            "mock_mode": True,
            "real_execution_allowed": False,
        },
        "tradingagents": {
            "enabled": False,
            "mode": "mock",
            "dry_run": True,
            "allow_api_keys_in_tests": False,
            "sanitize_actions": True,
            "force_paper_only": True,
            "real_execution_allowed": False,
        },
        "trendradar": {
            "enabled": False,
            "mode": "output_sidecar",
            "path_env": "TRENDRADAR_OUTPUT_PATH",
            "fallback_path": "external/trendradar/output",
            "max_items": 1000,
            "real_execution_allowed": False,
        },
        "apollo": {
            "enabled": True,
            "mode": "internal_doctrine",
            "chaos_threshold": 0.75,
            "durability_threshold": 0.65,
            "evidence_quality_threshold": 0.60,
            "minimum_source_count": 2,
            "real_execution_allowed": False,
        },
        "fincept_terminal": {
            "enabled": False,
            "mode": "exported_analytics_sidecar",
            "path_env": "FINCEPT_EXPORT_PATH",
            "fallback_path": "external/fincept/exports",
            "real_execution_allowed": False,
        },
    }
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ExternalAdapterRegistry:
    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or Path("config/external_adapters.yaml")
        self.config = self.load_config()
        self.adapters: dict[str, ExternalAdapter] = {}
        self._register_default_adapters()

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return DEFAULT_EXTERNAL_ADAPTER_CONFIG
        payload = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
        return _deep_merge(DEFAULT_EXTERNAL_ADAPTER_CONFIG, payload)

    def register(self, adapter: ExternalAdapter) -> None:
        self.adapters[adapter.source_name] = adapter

    def _register_default_adapters(self) -> None:
        adapter_configs = self.config.get("external_adapters", {})
        self.register(PolyDataAdapter(adapter_configs.get("poly_data", {})))
        self.register(KronosAdapter(adapter_configs.get("kronos", {})))
        self.register(TradingAgentsAdapter(adapter_configs.get("tradingagents", {})))
        self.register(TrendRadarAdapter(adapter_configs.get("trendradar", {})))
        self.register(FinceptTerminalAdapter(adapter_configs.get("fincept_terminal", {})))

    def enabled_adapters(self) -> list[ExternalAdapter]:
        return [adapter for adapter in self.adapters.values() if bool(adapter.config.get("enabled", False))]

    def _apollo_evidence(self) -> list[ExternalEvidence]:
        config = self.config.get("external_adapters", {}).get("apollo", {})
        if not bool(config.get("enabled", True)):
            return []
        evidence = ExternalEvidence(
            source="apollo",
            evidence_type=ExternalEvidenceType.MISSION_SAFETY,
            adapter_status=ExternalAdapterStatus.AVAILABLE,
            generated_at="doctrine_reference",
            data_truth_origin="public_domain_doctrine_reference",
            license_boundary="Public-domain doctrine reference",
            real_execution_allowed=False,
            execution_permission=ExternalExecutionPermission.REJECT_ONLY,
            raw_payload_hash="apollo_doctrine_reference",
            normalized_payload={
                "mode": config.get("mode", "internal_doctrine"),
                "chaos_threshold": config.get("chaos_threshold", 0.75),
                "durability_threshold": config.get("durability_threshold", 0.65),
                "evidence_quality_threshold": config.get("evidence_quality_threshold", 0.60),
                "minimum_source_count": config.get("minimum_source_count", 2),
            },
            warnings=[],
            errors=[],
            confidence_proxy=1.0,
            evidence_quality_score=1.0,
            context_tags=["mission_safety", "apollo_doctrine"],
        )
        return [evidence]

    def collect_external_evidence(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        evidence_rows: list[ExternalEvidence] = []
        for adapter in self.enabled_adapters():
            try:
                collected = adapter.collect(context=context)
            except Exception as exc:  # pragma: no cover - defensive
                collected = [
                    adapter.build_failure_evidence(
                        message=f"adapter failure: {exc}",
                        adapter_status=ExternalAdapterStatus.ERROR,
                        data_truth_origin="adapter_error",
                    )
                ]
            for evidence in collected:
                validation_errors = validate_external_evidence(evidence)
                if validation_errors:
                    evidence.adapter_status = ExternalAdapterStatus.DEGRADED
                    evidence.errors.extend(validation_errors)
                evidence_rows.append(evidence)
        evidence_rows.extend(self._apollo_evidence())
        return evidence_rows

    def status_report(self) -> dict[str, Any]:
        enabled = self.enabled_adapters()
        statuses = {name: adapter.status().value for name, adapter in self.adapters.items()}
        statuses["apollo"] = "AVAILABLE" if self.config.get("external_adapters", {}).get("apollo", {}).get("enabled", True) else "DISABLED"
        return {
            "external_adapters_available": bool(enabled) or bool(self.config.get("external_adapters", {}).get("apollo", {}).get("enabled", True)),
            "external_adapter_count": len(self.adapters) + 1,
            "enabled_adapter_count": len(enabled) + (1 if self.config.get("external_adapters", {}).get("apollo", {}).get("enabled", True) else 0),
            "statuses": statuses,
        }
