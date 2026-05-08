from __future__ import annotations

from pathlib import Path

from scripts.external_adapters.base import ExternalAdapter, ExternalEvidenceType
from scripts.external_adapters.registry import ExternalAdapterRegistry


class FailingAdapter(ExternalAdapter):
    source_name = "failing"
    evidence_type = ExternalEvidenceType.UNKNOWN
    license_boundary = "failing-boundary"

    def collect(self, context=None):
        raise RuntimeError("adapter crashed")


def test_registry_defaults_and_apollo_enabled() -> None:
    registry = ExternalAdapterRegistry(config_path=Path("tests/fixtures/external_adapters/missing_registry_config.yaml"))
    report = registry.status_report()
    assert report["external_adapters_available"] is True
    assert report["statuses"]["apollo"] == "AVAILABLE"


def test_registry_graceful_degradation_on_adapter_failure() -> None:
    registry = ExternalAdapterRegistry(config_path=Path("tests/fixtures/external_adapters/missing_registry_config.yaml"))
    adapter = FailingAdapter({"enabled": True})
    registry.register(adapter)
    evidence = registry.collect_external_evidence()
    failing_rows = [row for row in evidence if row.source == "failing"]
    assert failing_rows
    assert failing_rows[0].errors
