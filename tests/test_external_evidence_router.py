from __future__ import annotations

from scripts.core.external_evidence_router import ExternalEvidenceRouter
from scripts.external_adapters.base import (
    ExternalAdapterStatus,
    ExternalEvidence,
    ExternalEvidenceType,
    ExternalExecutionPermission,
)


def make_evidence(evidence_type: ExternalEvidenceType, source: str = "test") -> ExternalEvidence:
    return ExternalEvidence(
        source=source,
        evidence_type=evidence_type,
        adapter_status=ExternalAdapterStatus.AVAILABLE,
        generated_at="2026-05-08T00:00:00+00:00",
        data_truth_origin="test_origin",
        license_boundary="test_boundary",
        real_execution_allowed=False,
        execution_permission=ExternalExecutionPermission.WATCH_ONLY,
        raw_payload_hash="abc123",
        normalized_payload={"x": 1},
        warnings=[],
        errors=[],
        confidence_proxy=0.5,
        evidence_quality_score=0.5,
        context_tags=[],
    )


def test_external_evidence_router_route_rules() -> None:
    router = ExternalEvidenceRouter()
    route = router.route(make_evidence(ExternalEvidenceType.AGENT_COMMITTEE), pipeline_context={})
    assert route["max_allowed_action"] == "PAPER_TRADE"
    assert route["real_execution_allowed"] is False
    trend_route = router.route(make_evidence(ExternalEvidenceType.NARRATIVE_TREND), pipeline_context={})
    assert trend_route["max_allowed_action"] == "WATCH"


def test_missing_license_boundary_blocks() -> None:
    router = ExternalEvidenceRouter()
    evidence = make_evidence(ExternalEvidenceType.PREDICTION_MARKET)
    evidence.license_boundary = ""
    route = router.route(evidence, pipeline_context={})
    assert route["max_allowed_action"] == "REJECT"
    assert "PAPER_TRADE" in route["blocked_actions"]
