from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ExternalAdapterStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    DISABLED = "DISABLED"


class ExternalEvidenceType(str, Enum):
    PREDICTION_MARKET = "PREDICTION_MARKET"
    CANDLESTICK_FORECAST = "CANDLESTICK_FORECAST"
    AGENT_COMMITTEE = "AGENT_COMMITTEE"
    NARRATIVE_TREND = "NARRATIVE_TREND"
    MISSION_SAFETY = "MISSION_SAFETY"
    TERMINAL_ANALYTICS = "TERMINAL_ANALYTICS"
    UNKNOWN = "UNKNOWN"


class ExternalExecutionPermission(str, Enum):
    NEVER_REAL_EXECUTION = "NEVER_REAL_EXECUTION"
    PAPER_ONLY = "PAPER_ONLY"
    WATCH_ONLY = "WATCH_ONLY"
    REJECT_ONLY = "REJECT_ONLY"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def bounded_score(value: Any, default: float = 0.0) -> float:
    score = safe_float(value, default=default)
    return max(0.0, min(1.0, score))


def hash_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class ExternalEvidence:
    source: str
    evidence_type: ExternalEvidenceType
    adapter_status: ExternalAdapterStatus
    generated_at: str
    data_truth_origin: str
    license_boundary: str
    real_execution_allowed: bool
    execution_permission: ExternalExecutionPermission
    raw_payload_hash: str
    normalized_payload: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    confidence_proxy: float = 0.0
    evidence_quality_score: float = 0.0
    context_tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_type"] = self.evidence_type.value
        payload["adapter_status"] = self.adapter_status.value
        payload["execution_permission"] = self.execution_permission.value
        return payload


def validate_external_evidence(evidence: ExternalEvidence | dict[str, Any]) -> list[str]:
    payload = evidence.to_dict() if isinstance(evidence, ExternalEvidence) else dict(evidence)
    errors: list[str] = []
    if not safe_str(payload.get("license_boundary")):
        errors.append("license_boundary is required")
    if not safe_str(payload.get("data_truth_origin")):
        errors.append("data_truth_origin is required")
    if bool(payload.get("real_execution_allowed")):
        errors.append("real_execution_allowed must remain false")
    permission = safe_str(payload.get("execution_permission"))
    if permission not in {item.value for item in ExternalExecutionPermission}:
        errors.append("execution_permission is invalid")
    if not safe_str(payload.get("raw_payload_hash")):
        errors.append("raw_payload_hash is required")
    return errors


class ExternalAdapter:
    source_name = "external_adapter"
    evidence_type = ExternalEvidenceType.UNKNOWN
    license_boundary = "UNSPECIFIED"
    real_execution_allowed = False
    default_execution_permission = ExternalExecutionPermission.WATCH_ONLY

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        if bool(self.config.get("real_execution_allowed", False)):
            errors.append("adapter config cannot enable real execution")
        return errors

    def status(self) -> ExternalAdapterStatus:
        if not bool(self.config.get("enabled", False)):
            return ExternalAdapterStatus.DISABLED
        config_errors = self.validate_config()
        if config_errors:
            return ExternalAdapterStatus.ERROR
        return ExternalAdapterStatus.AVAILABLE

    def normalize(self, raw: Any) -> ExternalEvidence:
        payload = raw if isinstance(raw, dict) else {"value": raw}
        return ExternalEvidence(
            source=self.source_name,
            evidence_type=self.evidence_type,
            adapter_status=self.status(),
            generated_at=utc_now_iso(),
            data_truth_origin="external_adapter_raw",
            license_boundary=self.license_boundary,
            real_execution_allowed=False,
            execution_permission=self.default_execution_permission,
            raw_payload_hash=hash_payload(payload),
            normalized_payload=payload,
            confidence_proxy=0.0,
            evidence_quality_score=0.0,
            context_tags=[self.source_name],
        )

    def build_evidence(
        self,
        *,
        normalized_payload: dict[str, Any],
        data_truth_origin: str,
        adapter_status: ExternalAdapterStatus | None = None,
        execution_permission: ExternalExecutionPermission | None = None,
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        confidence_proxy: float = 0.0,
        evidence_quality_score: float = 0.0,
        context_tags: list[str] | None = None,
    ) -> ExternalEvidence:
        return ExternalEvidence(
            source=self.source_name,
            evidence_type=self.evidence_type,
            adapter_status=adapter_status or self.status(),
            generated_at=utc_now_iso(),
            data_truth_origin=data_truth_origin,
            license_boundary=self.license_boundary,
            real_execution_allowed=False,
            execution_permission=execution_permission or self.default_execution_permission,
            raw_payload_hash=hash_payload(normalized_payload),
            normalized_payload=normalized_payload,
            warnings=list(warnings or []),
            errors=list(errors or []),
            confidence_proxy=bounded_score(confidence_proxy),
            evidence_quality_score=bounded_score(evidence_quality_score),
            context_tags=list(context_tags or [self.source_name]),
        )

    def build_failure_evidence(
        self,
        *,
        message: str,
        adapter_status: ExternalAdapterStatus,
        data_truth_origin: str,
        errors: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> ExternalEvidence:
        return self.build_evidence(
            normalized_payload={"message": message},
            data_truth_origin=data_truth_origin,
            adapter_status=adapter_status,
            execution_permission=ExternalExecutionPermission.REJECT_ONLY,
            errors=errors or [message],
            warnings=warnings or [],
            confidence_proxy=0.0,
            evidence_quality_score=0.0,
        )

    def collect(self, context: dict[str, Any] | None = None) -> list[ExternalEvidence]:
        raise NotImplementedError

    def healthcheck(self) -> dict[str, Any]:
        return {
            "source": self.source_name,
            "status": self.status().value,
            "license_boundary": self.license_boundary,
            "real_execution_allowed": False,
        }
