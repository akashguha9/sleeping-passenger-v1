from __future__ import annotations

import json
from numbers import Number
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MOLTBOOK_DIR = REPO_ROOT / "moltbook"

TLT_FILE = "tlt_2026q2_close.json"
TIP_FILE = "tip_2026q2_close.json"
UNG_FILE = "ung_2026q2_close.json"
FCG_FILE = "fcg_2026q2_close.json"
MW_FILE = "mw_direction_v1_2026_04_19.json"

ALL_JSON_FILES = [TLT_FILE, TIP_FILE, UNG_FILE, FCG_FILE, MW_FILE]
TRADE_CLOSE_FILES = [TLT_FILE, TIP_FILE, UNG_FILE, FCG_FILE]
RATE_CLUSTER_FILES = [TLT_FILE, TIP_FILE]
CHAOS_FILES = [UNG_FILE, FCG_FILE]

TRADE_CLOSE_REQUIRED_FIELDS = {
    "trade_id",
    "ticker",
    "thesis_cluster",
    "thesis",
    "exit_date",
    "exit_price",
    "pnl_pct",
    "pnl_dollars",
    "classification",
    "thesis_validation",
    "exit_reason",
    "sizing",
    "notes",
}

TRADE_CLASSIFICATIONS = {"GOOD_WIN", "MARGINAL_WIN", "CHAOS_LOSS"}
THESIS_VALIDATIONS = {"FULL", "PARTIAL", "INVERTED"}

TLT_TIP_TOP_LEVEL_KEYS = {
    "trade_id",
    "ticker",
    "thesis_cluster",
    "thesis",
    "entry_date",
    "entry_price",
    "exit_date",
    "exit_price",
    "pnl_pct",
    "pnl_dollars",
    "classification",
    "thesis_validation",
    "exit_reason",
    "sizing",
    "entry_mechanism_stack",
    "lpc_attribution",
    "notes",
}

CHAOS_COMMON_TOP_LEVEL_KEYS = {
    "trade_id",
    "ticker",
    "thesis_cluster",
    "thesis",
    "entry_classification",
    "entered_against_veto",
    "entry_price",
    "exit_date",
    "exit_price",
    "pnl_pct",
    "pnl_dollars",
    "classification",
    "thesis_validation",
    "veto_validated",
    "exit_reason",
    "sizing",
    "entry_mechanism_stack_estimated",
    "lpc_attribution",
    "mw_calibration_data_point",
    "notes",
}

UNG_TOP_LEVEL_KEYS = set(CHAOS_COMMON_TOP_LEVEL_KEYS)
FCG_TOP_LEVEL_KEYS = set(CHAOS_COMMON_TOP_LEVEL_KEYS) | {"stop_proximity_at_exit_pct"}

TLT_TIP_STACK_KEYS = {
    "ce_raw",
    "sbe_norm",
    "ass_q",
    "pse",
    "mtl",
    "nsd_premium",
    "rtt_port",
    "zpd_frac",
    "bcp_state",
    "sbc_tier",
    "ssd_score",
    "ssd_tier",
    "att_state",
    "ndi_state",
    "lalo_state",
    "osm_gate",
}

CHAOS_STACK_KEYS = {
    "ce_raw",
    "ce_tier",
    "sbe_norm",
    "ass_q",
    "pse",
    "mtl",
    "nsd_premium",
    "nsd_state",
    "rtt_port",
    "rtt_state",
    "zpd_frac",
    "bcp_state",
    "sbc_tier",
    "sbc_survivor_fraction",
    "sbc_penalty",
    "ssd_score_estimate",
    "ssd_tier",
    "att_state",
    "ndi_state",
    "lalo_state",
    "osm_state",
}

MW_TOP_LEVEL_KEYS = {
    "signal_id",
    "unlocked_at_t_count",
    "epsilon_before",
    "epsilon_after",
    "calibration_data_points_n",
    "clean_pattern_observed",
    "pattern",
    "provisional_weights",
    "next_milestones",
    "notes",
}

MW_PATTERN_KEYS = {
    "high_ce_approved_executed",
    "low_ce_chaos_executed",
    "ce_delta",
    "pnl_delta_pct",
    "mw_lift_per_ce_point",
}

MW_PATTERN_BRANCH_KEYS = {
    "trades",
    "outcomes",
    "mean_ce_at_entry",
    "mean_pnl_pct",
    "directional_bias",
}


def load_json_payload(filename: str) -> dict:
    path = MOLTBOOK_DIR / filename
    if not path.exists():
        pytest.fail(f"Expected Moltbook file is missing: {path}")

    raw = path.read_text(encoding="utf-8-sig")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"Invalid JSON in {path}: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        )

    assert isinstance(payload, dict), f"{path} must decode to a top-level JSON object"
    return payload


def assert_exact_keys(mapping: dict, expected_keys: set[str], context: str) -> None:
    actual_keys = set(mapping.keys())
    missing = sorted(expected_keys - actual_keys)
    extra = sorted(actual_keys - expected_keys)
    assert not missing and not extra, (
        f"{context} schema drift detected. "
        f"missing={missing or '[]'} extra={extra or '[]'}"
    )


def assert_required_keys(mapping: dict, required_keys: set[str], context: str) -> None:
    missing = sorted(required_keys - set(mapping.keys()))
    assert not missing, f"{context} missing required fields: {missing}"


def assert_is_number(value: object, context: str) -> None:
    assert isinstance(value, Number) and not isinstance(value, bool), (
        f"{context} must be numeric, got {type(value).__name__}"
    )


@pytest.mark.parametrize("filename", ALL_JSON_FILES)
def test_expected_moltbook_files_exist(filename: str) -> None:
    path = MOLTBOOK_DIR / filename
    assert path.exists(), f"Expected Moltbook file is missing: {path}"


@pytest.mark.parametrize("filename", ALL_JSON_FILES)
def test_expected_moltbook_files_are_valid_json(filename: str) -> None:
    load_json_payload(filename)


@pytest.mark.parametrize("filename", TRADE_CLOSE_FILES)
def test_trade_close_files_have_required_top_level_fields(filename: str) -> None:
    payload = load_json_payload(filename)
    assert_required_keys(payload, TRADE_CLOSE_REQUIRED_FIELDS, filename)


@pytest.mark.parametrize(
    ("filename", "expected_top_level_keys"),
    [
        (TLT_FILE, TLT_TIP_TOP_LEVEL_KEYS),
        (TIP_FILE, TLT_TIP_TOP_LEVEL_KEYS),
        (UNG_FILE, UNG_TOP_LEVEL_KEYS),
        (FCG_FILE, FCG_TOP_LEVEL_KEYS),
    ],
)
def test_trade_close_top_level_schema_does_not_drift(
    filename: str, expected_top_level_keys: set[str]
) -> None:
    payload = load_json_payload(filename)
    assert_exact_keys(payload, expected_top_level_keys, filename)


@pytest.mark.parametrize("filename", TRADE_CLOSE_FILES)
def test_trade_close_numeric_fields_are_numeric(filename: str) -> None:
    payload = load_json_payload(filename)

    numeric_fields = ["exit_price", "pnl_pct", "pnl_dollars"]
    if "entry_price" in payload:
        numeric_fields.append("entry_price")
    if "stop_proximity_at_exit_pct" in payload:
        numeric_fields.append("stop_proximity_at_exit_pct")

    for field in numeric_fields:
        assert_is_number(payload[field], f"{filename}:{field}")


@pytest.mark.parametrize("filename", TRADE_CLOSE_FILES)
def test_trade_close_enums_are_constrained(filename: str) -> None:
    payload = load_json_payload(filename)

    assert payload["classification"] in TRADE_CLASSIFICATIONS, (
        f"{filename}:classification must be one of {sorted(TRADE_CLASSIFICATIONS)}"
    )
    assert payload["thesis_validation"] in THESIS_VALIDATIONS, (
        f"{filename}:thesis_validation must be one of {sorted(THESIS_VALIDATIONS)}"
    )
    assert payload["sizing"] == "QUARTER_UNIT", (
        f"{filename}:sizing must be QUARTER_UNIT, got {payload['sizing']!r}"
    )


@pytest.mark.parametrize("filename", RATE_CLUSTER_FILES)
def test_tlt_tip_entry_mechanism_stack_schema(filename: str) -> None:
    payload = load_json_payload(filename)
    stack = payload["entry_mechanism_stack"]

    assert isinstance(stack, dict), f"{filename}:entry_mechanism_stack must be an object"
    assert_exact_keys(stack, TLT_TIP_STACK_KEYS, f"{filename}:entry_mechanism_stack")

    numeric_fields = [
        "ce_raw",
        "sbe_norm",
        "ass_q",
        "pse",
        "mtl",
        "nsd_premium",
        "rtt_port",
        "zpd_frac",
        "ssd_score",
    ]
    for field in numeric_fields:
        assert_is_number(stack[field], f"{filename}:entry_mechanism_stack.{field}")


@pytest.mark.parametrize("filename", CHAOS_FILES)
def test_ung_fcg_chaos_fields_and_constraints(filename: str) -> None:
    payload = load_json_payload(filename)

    assert payload["entry_classification"] == "CHAOS_ENTRY", (
        f"{filename}:entry_classification must be CHAOS_ENTRY"
    )
    assert payload["classification"] == "CHAOS_LOSS", (
        f"{filename}:classification must be CHAOS_LOSS"
    )
    assert payload["entered_against_veto"] is True, (
        f"{filename}:entered_against_veto must be true"
    )
    assert payload["veto_validated"] is True, (
        f"{filename}:veto_validated must be true"
    )
    assert isinstance(payload["mw_calibration_data_point"], bool), (
        f"{filename}:mw_calibration_data_point must be boolean"
    )


@pytest.mark.parametrize("filename", CHAOS_FILES)
def test_ung_fcg_estimated_stack_schema(filename: str) -> None:
    payload = load_json_payload(filename)
    stack = payload["entry_mechanism_stack_estimated"]

    assert isinstance(
        stack, dict
    ), f"{filename}:entry_mechanism_stack_estimated must be an object"
    assert_exact_keys(
        stack, CHAOS_STACK_KEYS, f"{filename}:entry_mechanism_stack_estimated"
    )

    numeric_fields = [
        "ce_raw",
        "sbe_norm",
        "ass_q",
        "pse",
        "mtl",
        "nsd_premium",
        "rtt_port",
        "zpd_frac",
        "sbc_survivor_fraction",
        "sbc_penalty",
        "ssd_score_estimate",
    ]
    for field in numeric_fields:
        assert_is_number(
            stack[field], f"{filename}:entry_mechanism_stack_estimated.{field}"
        )


def test_mw_file_top_level_schema_and_types() -> None:
    payload = load_json_payload(MW_FILE)

    assert_exact_keys(payload, MW_TOP_LEVEL_KEYS, MW_FILE)

    assert isinstance(payload["signal_id"], str) and payload["signal_id"], (
        f"{MW_FILE}:signal_id must be a non-empty string"
    )
    assert_is_number(payload["unlocked_at_t_count"], f"{MW_FILE}:unlocked_at_t_count")
    assert_is_number(payload["epsilon_before"], f"{MW_FILE}:epsilon_before")
    assert_is_number(payload["epsilon_after"], f"{MW_FILE}:epsilon_after")
    assert_is_number(
        payload["calibration_data_points_n"], f"{MW_FILE}:calibration_data_points_n"
    )
    assert isinstance(payload["clean_pattern_observed"], bool), (
        f"{MW_FILE}:clean_pattern_observed must be boolean"
    )
    assert isinstance(payload["provisional_weights"], dict), (
        f"{MW_FILE}:provisional_weights must be an object"
    )
    assert isinstance(payload["next_milestones"], dict), (
        f"{MW_FILE}:next_milestones must be an object"
    )


def test_mw_file_pattern_schema_and_numeric_fields() -> None:
    payload = load_json_payload(MW_FILE)
    pattern = payload["pattern"]

    assert isinstance(pattern, dict), f"{MW_FILE}:pattern must be an object"
    assert_exact_keys(pattern, MW_PATTERN_KEYS, f"{MW_FILE}:pattern")

    for field in ["ce_delta", "pnl_delta_pct", "mw_lift_per_ce_point"]:
        assert_is_number(pattern[field], f"{MW_FILE}:pattern.{field}")

    for branch_name in ["high_ce_approved_executed", "low_ce_chaos_executed"]:
        branch = pattern[branch_name]
        assert isinstance(branch, dict), f"{MW_FILE}:pattern.{branch_name} must be an object"
        assert_exact_keys(
            branch, MW_PATTERN_BRANCH_KEYS, f"{MW_FILE}:pattern.{branch_name}"
        )
        assert isinstance(branch["trades"], list) and branch["trades"], (
            f"{MW_FILE}:pattern.{branch_name}.trades must be a non-empty list"
        )
        assert all(isinstance(item, str) and item for item in branch["trades"]), (
            f"{MW_FILE}:pattern.{branch_name}.trades must contain non-empty strings"
        )
        assert isinstance(branch["outcomes"], str) and branch["outcomes"], (
            f"{MW_FILE}:pattern.{branch_name}.outcomes must be a non-empty string"
        )
        assert_is_number(
            branch["mean_ce_at_entry"],
            f"{MW_FILE}:pattern.{branch_name}.mean_ce_at_entry",
        )
        assert_is_number(
            branch["mean_pnl_pct"], f"{MW_FILE}:pattern.{branch_name}.mean_pnl_pct"
        )
        assert isinstance(branch["directional_bias"], str) and branch["directional_bias"], (
            f"{MW_FILE}:pattern.{branch_name}.directional_bias must be a non-empty string"
        )

