from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
MOLTBOOK_DIR = REPO_ROOT / "moltbook"

TRADE_CLASSIFICATIONS = {"GOOD_WIN", "MARGINAL_WIN", "CHAOS_LOSS"}
THESIS_VALIDATIONS = {"FULL", "PARTIAL", "INVERTED"}
SIZING_VALUES = {"QUARTER_UNIT"}

RATE_STACK_KEYS = {
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

MW_PATTERN_KEYS = {
    "high_ce_approved_executed",
    "low_ce_chaos_executed",
    "ce_delta",
    "pnl_delta_pct",
    "mw_lift_per_ce_point",
}

SUPPORTED_FILENAMES = {
    "tlt_2026q2_close.json",
    "tip_2026q2_close.json",
    "ung_2026q2_close.json",
    "fcg_2026q2_close.json",
    "mw_direction_v1_2026_04_19.json",
}


@dataclass
class MoltbookBundle:
    trade_closes: list[dict[str, Any]]
    mw_signals: list[dict[str, Any]]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Moltbook file: {path}")
    raw = path.read_text(encoding="utf-8-sig")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: top-level JSON must be an object")
    return payload


def _require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload.keys()))
    if missing:
        raise ValueError(f"{context}: missing keys {missing}")


def _require_exact_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    actual = set(payload.keys())
    missing = sorted(keys - actual)
    extra = sorted(actual - keys)
    if missing or extra:
        raise ValueError(f"{context}: schema drift missing={missing} extra={extra}")


def _require_number(value: Any, context: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context}: expected numeric, got {type(value).__name__}")


def _validate_trade_close(payload: dict[str, Any], context: str) -> None:
    required = {
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
    _require_keys(payload, required, context)

    if payload["classification"] not in TRADE_CLASSIFICATIONS:
        raise ValueError(f"{context}: invalid classification {payload['classification']}")
    if payload["thesis_validation"] not in THESIS_VALIDATIONS:
        raise ValueError(f"{context}: invalid thesis_validation {payload['thesis_validation']}")
    if payload["sizing"] not in SIZING_VALUES:
        raise ValueError(f"{context}: invalid sizing {payload['sizing']}")

    for field in ("exit_price", "pnl_pct", "pnl_dollars"):
        _require_number(payload[field], f"{context}.{field}")

    if "entry_price" in payload:
        _require_number(payload["entry_price"], f"{context}.entry_price")

    if "entry_mechanism_stack" in payload:
        stack = payload["entry_mechanism_stack"]
        if not isinstance(stack, dict):
            raise ValueError(f"{context}.entry_mechanism_stack: must be object")
        _require_exact_keys(stack, RATE_STACK_KEYS, f"{context}.entry_mechanism_stack")

    if "entry_mechanism_stack_estimated" in payload:
        stack = payload["entry_mechanism_stack_estimated"]
        if not isinstance(stack, dict):
            raise ValueError(f"{context}.entry_mechanism_stack_estimated: must be object")
        _require_exact_keys(stack, CHAOS_STACK_KEYS, f"{context}.entry_mechanism_stack_estimated")

    if payload.get("entry_classification") == "CHAOS_ENTRY":
        if payload["classification"] != "CHAOS_LOSS":
            raise ValueError(f"{context}: chaos entry must currently classify as CHAOS_LOSS in seed set")
        if payload.get("entered_against_veto") is not True:
            raise ValueError(f"{context}: entered_against_veto must be true")
        if payload.get("veto_validated") is not True:
            raise ValueError(f"{context}: veto_validated must be true")


def _validate_mw_signal(payload: dict[str, Any], context: str) -> None:
    required = {
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
    _require_exact_keys(payload, required, context)

    _require_number(payload["unlocked_at_t_count"], f"{context}.unlocked_at_t_count")
    _require_number(payload["epsilon_before"], f"{context}.epsilon_before")
    _require_number(payload["epsilon_after"], f"{context}.epsilon_after")
    _require_number(payload["calibration_data_points_n"], f"{context}.calibration_data_points_n")

    pattern = payload["pattern"]
    if not isinstance(pattern, dict):
        raise ValueError(f"{context}.pattern: must be object")
    _require_exact_keys(pattern, MW_PATTERN_KEYS, f"{context}.pattern")


def load_moltbook_bundle(directory: Path | None = None) -> MoltbookBundle:
    base = directory or MOLTBOOK_DIR
    if not base.exists():
        raise FileNotFoundError(f"Moltbook directory does not exist: {base}")

    trade_closes: list[dict[str, Any]] = []
    mw_signals: list[dict[str, Any]] = []

    for path in sorted(base.glob("*.json")):
        if path.name not in SUPPORTED_FILENAMES:
            continue

        payload = _read_json(path)
        context = path.name

        if "signal_id" in payload:
            _validate_mw_signal(payload, context)
            mw_signals.append(payload)
        else:
            _validate_trade_close(payload, context)
            trade_closes.append(payload)

    return MoltbookBundle(trade_closes=trade_closes, mw_signals=mw_signals)


def summarize_moltbook(directory: Path | None = None) -> dict[str, Any]:
    bundle = load_moltbook_bundle(directory)
    return {
        "trade_close_count": len(bundle.trade_closes),
        "mw_signal_count": len(bundle.mw_signals),
        "tickers": sorted({item["ticker"] for item in bundle.trade_closes}),
        "classifications": sorted({item["classification"] for item in bundle.trade_closes}),
        "mw_signal_ids": sorted(item["signal_id"] for item in bundle.mw_signals),
    }


def format_moltbook_summary(summary: dict[str, Any]) -> str:
    tickers = ", ".join(summary["tickers"]) or "none"
    classifications = ", ".join(summary["classifications"]) or "none"
    mw_signal_ids = ", ".join(summary["mw_signal_ids"]) or "none"
    return "\n".join(
        [
            "Moltbook Summary",
            f"trade_close_count={summary['trade_close_count']}",
            f"mw_signal_count={summary['mw_signal_count']}",
            f"tickers={tickers}",
            f"classifications={classifications}",
            f"mw_signal_ids={mw_signal_ids}",
        ]
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load and validate curated Moltbook runtime files.")
    parser.add_argument(
        "--directory",
        type=Path,
        default=MOLTBOOK_DIR,
        help="Override the Moltbook directory path.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    summary = summarize_moltbook(args.directory)
    if args.summary:
        print(format_moltbook_summary(summary))
    else:
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
