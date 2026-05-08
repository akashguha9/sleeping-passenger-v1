from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    bounded_score,
    safe_str,
)


class FinceptTerminalAdapter(ExternalAdapter):
    source_name = "fincept_terminal"
    evidence_type = ExternalEvidenceType.TERMINAL_ANALYTICS
    license_boundary = "AGPL-3.0/commercial sidecar - no source code copied into MVP core"
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    def _resolve_root(self, context: dict[str, Any] | None = None) -> Path:
        ctx = context or {}
        candidate = safe_str(ctx.get("path"))
        if candidate:
            return Path(candidate)
        env_name = safe_str(self.config.get("path_env"), "FINCEPT_EXPORT_PATH")
        env_value = safe_str(os.environ.get(env_name))
        if env_value:
            return Path(env_value)
        return Path(safe_str(self.config.get("fallback_path"), "external/fincept/exports"))

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []
        root = self._resolve_root(context)
        if not root.exists():
            return [
                self.build_failure_evidence(
                    message=f"FinceptTerminal export path not found: {root}",
                    adapter_status=ExternalAdapterStatus.UNAVAILABLE,
                    data_truth_origin="external_fincept_terminal",
                    warnings=["adapter degraded gracefully; no sidecar path available"],
                )
            ]
        analytics: list[dict[str, Any]] = []
        warnings: list[str] = []
        errors: list[str] = []
        for path in sorted(root.glob("*")):
            try:
                if path.suffix.lower() == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    rows = payload if isinstance(payload, list) else [payload]
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        analytics.append(
                            {
                                "instrument_id": safe_str(row.get("instrument_id") or row.get("symbol")),
                                "analytics_type": safe_str(row.get("analytics_type"), "UNKNOWN"),
                                "payload": row.get("payload", row),
                                "data_sources": row.get("data_sources", []),
                                "generated_at": safe_str(row.get("generated_at")),
                            }
                        )
                elif path.suffix.lower() == ".csv":
                    with path.open("r", encoding="utf-8", newline="") as handle:
                        reader = csv.DictReader(handle)
                        for row in reader:
                            analytics.append(
                                {
                                    "instrument_id": safe_str(row.get("instrument_id") or row.get("symbol")),
                                    "analytics_type": safe_str(row.get("analytics_type"), "CSV_EXPORT"),
                                    "payload": dict(row),
                                    "data_sources": [],
                                    "generated_at": safe_str(row.get("generated_at")),
                                }
                            )
                elif path.suffix.lower() == ".txt":
                    analytics.append(
                        {
                            "instrument_id": "",
                            "analytics_type": "TEXT_EXPORT",
                            "payload": {"text": path.read_text(encoding="utf-8").strip()},
                            "data_sources": [],
                            "generated_at": "",
                        }
                    )
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"failed to read {path.name}: {exc}")
        status = ExternalAdapterStatus.AVAILABLE if analytics else ExternalAdapterStatus.DEGRADED
        return [
            self.build_evidence(
                normalized_payload={"root_path": root.as_posix(), "analytics": analytics},
                data_truth_origin="external_fincept_terminal",
                adapter_status=status,
                warnings=warnings,
                errors=errors,
                confidence_proxy=0.4 if analytics else 0.0,
                evidence_quality_score=bounded_score(0.35 + (0.1 if analytics else 0.0)),
                context_tags=["terminal_analytics", "sidecar", "agpl_boundary"],
            )
        ]
