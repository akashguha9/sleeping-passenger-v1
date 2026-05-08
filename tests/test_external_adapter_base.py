from __future__ import annotations

from scripts.external_adapters.base import (
    ExternalAdapter,
    ExternalAdapterStatus,
    ExternalEvidenceType,
    ExternalExecutionPermission,
    hash_payload,
    validate_external_evidence,
)


class DummyAdapter(ExternalAdapter):
    source_name = "dummy"
    evidence_type = ExternalEvidenceType.UNKNOWN
    license_boundary = "dummy-boundary"

    def collect(self, context=None):
        if context and context.get("fail"):
            raise RuntimeError("boom")
        return [
            self.build_evidence(
                normalized_payload={"value": 1},
                data_truth_origin="dummy_origin",
                adapter_status=ExternalAdapterStatus.AVAILABLE,
                execution_permission=ExternalExecutionPermission.WATCH_ONLY,
            )
        ]


def test_missing_license_fails_validation() -> None:
    evidence = DummyAdapter({"enabled": True}).build_evidence(
        normalized_payload={"x": 1},
        data_truth_origin="dummy",
    )
    evidence.license_boundary = ""
    assert "license_boundary is required" in validate_external_evidence(evidence)


def test_missing_data_truth_origin_fails_validation() -> None:
    evidence = DummyAdapter({"enabled": True}).build_evidence(
        normalized_payload={"x": 1},
        data_truth_origin="dummy",
    )
    evidence.data_truth_origin = ""
    assert "data_truth_origin is required" in validate_external_evidence(evidence)


def test_real_execution_allowed_true_fails_validation() -> None:
    evidence = DummyAdapter({"enabled": True}).build_evidence(
        normalized_payload={"x": 1},
        data_truth_origin="dummy",
    )
    evidence.real_execution_allowed = True
    assert "real_execution_allowed must remain false" in validate_external_evidence(evidence)


def test_payload_hash_stable() -> None:
    payload = {"b": 2, "a": 1}
    assert hash_payload(payload) == hash_payload({"a": 1, "b": 2})


def test_adapter_failure_becomes_structured_output() -> None:
    adapter = DummyAdapter({"enabled": True})
    evidence = adapter.build_failure_evidence(
        message="failed safely",
        adapter_status=ExternalAdapterStatus.ERROR,
        data_truth_origin="adapter_error",
    )
    assert evidence.adapter_status == ExternalAdapterStatus.ERROR
    assert evidence.real_execution_allowed is False
    assert evidence.errors
