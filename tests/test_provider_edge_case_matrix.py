"""Provider edge-case matrix — proof_loop_hardening_sprint, Phase 10.

Asserts the classification of every (provider, error_class) combination
never overclaims ``LIVE_VERIFIED``.
"""
from __future__ import annotations

import pytest

from scripts.provider_edge_case_matrix import (
    ADAPTER_STATUS_TO_SPRINT_LABEL,
    ALL_LABELS,
    ERROR_CLASSES,
    LABEL_ADAPTER_PARTIAL,
    LABEL_DEGRADED,
    LABEL_ERROR,
    LABEL_FILTERED,
    LABEL_LIVE_VERIFIED,
    LABEL_NOT_CONFIGURED,
    LABEL_RATE_LIMITED,
    LABEL_STALE,
    LABEL_ZERO_FRESH_ROWS,
    PROVIDERS,
    classify,
    map_adapter_status_to_sprint_label,
    matrix_report,
)


pytestmark = [
    pytest.mark.reliability,
    pytest.mark.safety_floor,
]


def test_missing_credentials_is_not_configured():
    assert classify("missing_credentials") == LABEL_NOT_CONFIGURED


def test_partial_adapter_is_adapter_partial():
    assert classify("partial_adapter") == LABEL_ADAPTER_PARTIAL


def test_http_429_is_rate_limited():
    assert classify("http_429") == LABEL_RATE_LIMITED


def test_timeout_and_5xx_are_degraded():
    assert classify("timeout") == LABEL_DEGRADED
    assert classify("http_5xx") == LABEL_DEGRADED


def test_malformed_payload_is_error_not_live():
    assert classify("malformed_payload") == LABEL_ERROR
    assert classify("malformed_payload") != LABEL_LIVE_VERIFIED


def test_empty_response_is_zero_fresh_rows():
    assert classify("empty_response") == LABEL_ZERO_FRESH_ROWS


def test_filtered_zero_rows_is_filtered():
    assert classify("filtered_zero_rows") == LABEL_FILTERED


def test_stale_timestamp_is_stale():
    assert classify("stale_timestamp") == LABEL_STALE


def test_fresh_rows_only_live_verified_when_ttl_passes():
    # No TTL pass yet → not LIVE_VERIFIED.
    assert classify("fresh_canonical_rows", canonical_ttl_passes=False) == LABEL_ZERO_FRESH_ROWS
    # TTL passes → LIVE_VERIFIED.
    assert classify("fresh_canonical_rows", canonical_ttl_passes=True) == LABEL_LIVE_VERIFIED


@pytest.mark.parametrize("provider", PROVIDERS)
def test_provider_never_overclaims_live_for_any_error_class(provider):
    """For every provider, every error class must NOT collapse to LIVE_VERIFIED."""
    for ec in ERROR_CLASSES:
        if ec == "fresh_canonical_rows":
            continue
        label = classify(ec, canonical_ttl_passes=False)
        assert label != LABEL_LIVE_VERIFIED, (
            f"{provider}/{ec} overclaimed LIVE_VERIFIED: got {label}"
        )


def test_adapter_status_mapping_is_complete():
    # Every adapter status that the existing registry uses must map to a
    # sprint label so downstream readers do not invent a parallel taxonomy.
    expected = {"implemented", "partial", "planned", "not_configured"}
    assert expected.issubset(set(ADAPTER_STATUS_TO_SPRINT_LABEL.keys()))


def test_unknown_adapter_status_degrades_to_error():
    assert map_adapter_status_to_sprint_label("nonsense") == LABEL_ERROR


def test_matrix_report_covers_every_provider_and_error_class():
    rep = matrix_report()
    assert len(rep["providers"]) == len(PROVIDERS)
    assert len(rep["error_classes"]) == len(ERROR_CLASSES)
    assert len(rep["rows"]) == len(PROVIDERS) * len(ERROR_CLASSES)
    for row in rep["rows"]:
        assert row["classification"] in ALL_LABELS
        assert row["classification_when_ttl_passes"] in ALL_LABELS


def test_all_labels_set_is_disjoint_from_arbitrary_strings():
    assert "LIVE_OK" not in ALL_LABELS
    assert "OK" not in ALL_LABELS
