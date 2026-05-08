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
    safe_float,
    safe_str,
)


class TrendRadarAdapter(ExternalAdapter):
    source_name = "trendradar"
    evidence_type = ExternalEvidenceType.NARRATIVE_TREND
    license_boundary = "GPL-3.0 sidecar - no source code copied into MVP core"
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    def _resolve_root(self, context: dict[str, Any] | None = None) -> Path:
        ctx = context or {}
        candidate = safe_str(ctx.get("path"))
        if candidate:
            return Path(candidate)
        env_name = safe_str(self.config.get("path_env"), "TRENDRADAR_OUTPUT_PATH")
        env_value = safe_str(os.environ.get(env_name))
        if env_value:
            return Path(env_value)
        return Path(safe_str(self.config.get("fallback_path"), "external/trendradar/output"))

    @staticmethod
    def _engineered_noise_score(item: dict[str, Any]) -> float:
        return bounded_score(
            0.25 * bounded_score(item.get("emotional_intensity"))
            + 0.20 * bounded_score(item.get("urgency_score"))
            + 0.20 * bounded_score(item.get("evidence_absence"))
            + 0.15 * bounded_score(item.get("repetition_score"))
            + 0.10 * bounded_score(item.get("clickbait_score"))
            + 0.10 * bounded_score(item.get("source_vagueness"))
        )

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        if not bool(self.config.get("enabled", False)):
            return []
        root = self._resolve_root(context)
        warnings: list[str] = []
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        summaries: list[str] = []
        if not root.exists():
            return [
                self.build_failure_evidence(
                    message=f"TrendRadar sidecar path not found: {root}",
                    adapter_status=ExternalAdapterStatus.UNAVAILABLE,
                    data_truth_origin="external_trendradar_sidecar",
                    warnings=["adapter degraded gracefully; no sidecar path available"],
                )
            ]
        for path in sorted(root.glob("*")):
            if path.suffix.lower() == ".json":
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(f"failed to read {path.name}: {exc}")
                    continue
                rows = payload if isinstance(payload, list) else payload.get("trends", [])
                if not isinstance(rows, list):
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    normalized = {
                        "topic": safe_str(row.get("topic") or row.get("title")),
                        "title": safe_str(row.get("title")),
                        "summary": safe_str(row.get("summary")),
                        "url": safe_str(row.get("url")),
                        "platform": safe_str(row.get("platform")),
                        "observed_at": safe_str(row.get("observed_at")),
                        "attention_velocity": bounded_score(row.get("attention_velocity", 0.5)),
                        "sentiment_proxy": bounded_score(row.get("sentiment_proxy", 0.5)),
                        "engineered_noise_score": self._engineered_noise_score(row),
                        "narrative_state": safe_str(row.get("narrative_state"), "UNKNOWN").upper(),
                        "matched_market_ids": row.get("matched_market_ids", []),
                        "matched_keywords": row.get("matched_keywords", []),
                        "source_credibility_proxy": bounded_score(row.get("source_credibility_proxy", 0.5)),
                    }
                    items.append(normalized)
            elif path.suffix.lower() == ".txt":
                try:
                    summaries.append(path.read_text(encoding="utf-8").strip())
                except OSError as exc:
                    warnings.append(f"failed to read text sidecar {path.name}: {exc}")
            elif path.suffix.lower() == ".csv":
                try:
                    with path.open("r", encoding="utf-8", newline="") as handle:
                        reader = csv.DictReader(handle)
                        for row in reader:
                            items.append(
                                {
                                    "topic": safe_str(row.get("topic") or row.get("title")),
                                    "title": safe_str(row.get("title")),
                                    "summary": safe_str(row.get("summary")),
                                    "url": safe_str(row.get("url")),
                                    "platform": safe_str(row.get("platform")),
                                    "observed_at": safe_str(row.get("observed_at")),
                                    "attention_velocity": bounded_score(row.get("attention_velocity", 0.5)),
                                    "sentiment_proxy": bounded_score(row.get("sentiment_proxy", 0.5)),
                                    "engineered_noise_score": self._engineered_noise_score(row),
                                    "narrative_state": safe_str(row.get("narrative_state"), "UNKNOWN").upper(),
                                    "matched_market_ids": [],
                                    "matched_keywords": [],
                                    "source_credibility_proxy": bounded_score(row.get("source_credibility_proxy", 0.5)),
                                }
                            )
                except OSError as exc:
                    warnings.append(f"failed to read csv sidecar {path.name}: {exc}")
        status = ExternalAdapterStatus.AVAILABLE if items else ExternalAdapterStatus.DEGRADED
        avg_quality = bounded_score(
            sum((1.0 - item["engineered_noise_score"]) * item["source_credibility_proxy"] for item in items) / max(len(items), 1)
        )
        return [
            self.build_evidence(
                normalized_payload={
                    "root_path": root.as_posix(),
                    "items": items[: int(self.config.get("max_items", 1000) or 1000)],
                    "text_summaries": summaries,
                },
                data_truth_origin="external_trendradar_sidecar",
                adapter_status=status,
                warnings=warnings,
                errors=errors,
                confidence_proxy=0.45 if items else 0.0,
                evidence_quality_score=avg_quality,
                context_tags=["narrative_trend", "sidecar", "gpl_boundary"],
            )
        ]
