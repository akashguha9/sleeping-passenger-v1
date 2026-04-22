from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    from scripts.action_engine import build_action_report
    from scripts.runtime_common import (
        OPEN_POSITIONS_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        append_jsonl,
        build_deployment_permissions,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
    from scripts.signal_conversion_monitor import build_signal_conversion_report
except ModuleNotFoundError:
    from action_engine import build_action_report
    from runtime_common import (
        OPEN_POSITIONS_PATH,
        PAPER_CLOSE_LEDGER_PATH,
        PAPER_DECISION_LEDGER_PATH,
        PAPER_FILL_LEDGER_PATH,
        PAPER_ORDER_LEDGER_PATH,
        PAPER_POSITIONS_PATH,
        append_jsonl,
        build_deployment_permissions,
        build_runtime_state_from_scm_report_payload,
        get_run_id,
        load_current_pipeline_state,
        load_json_file,
        load_open_positions,
        repo_relative,
        stamp_payload,
        utc_timestamp,
        write_json_atomic,
    )
    from signal_conversion_monitor import build_signal_conversion_report


OPEN_ENTRY_ACTIONS = {"REVIEW_FOR_ENTRY"}
CLOSE_ACTIONS = {"EXIT_NOW"}
DEFAULT_ORDER_QTY = 1.0
DEFAULT_FILL_PRICE = 100.0


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"|")
    return f"{prefix}_{digest.hexdigest()[:12]}"


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _load_existing_ids(path: Path, key_name: str) -> set[str]:
    ids: set[str] = set()
    for row in _load_jsonl_rows(path):
        value = str(row.get(key_name) or "").strip()
        if value:
            ids.add(value)
    return ids


def _load_paper_positions(path: Path | None = None) -> list[dict[str, Any]]:
    payload = load_json_file(path or PAPER_POSITIONS_PATH, default={}) or {}
    if isinstance(payload, dict):
        rows = payload.get("positions", [])
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


def _write_paper_positions(
    positions: list[dict[str, Any]],
    runtime_state: dict[str, Any],
    path: Path | None = None,
) -> None:
    payload = stamp_payload(
        {
            "artifact_kind": "paper_positions_ledger",
            "positions": positions,
            "open_position_count": sum(
                1 for row in positions if str(row.get("status") or "").upper() == "OPEN"
            ),
            "note": (
                "Open paper positions only. Closed paper lineage is stored in the "
                "paper closes ledger."
            ),
        },
        runtime_state=runtime_state,
    )
    write_json_atomic(path or PAPER_POSITIONS_PATH, payload, stamp=False)


def _ensure_non_live_only(runtime_state: dict[str, Any]) -> None:
    deployment = build_deployment_permissions(runtime_state)
    if deployment["live_execution_enabled"] or deployment["can_emit_live_actions"]:
        raise ValueError("paper execution path refuses to run while live execution is enabled")


def _paper_enabled(runtime_state: dict[str, Any]) -> bool:
    deployment = build_deployment_permissions(runtime_state)
    return bool(deployment["paper_execution_enabled"])


def _build_runtime_state(
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict[str, Any]:
    if any([simulate_gsce_clear, simulate_realm_bis_clear, simulate_all_clear]):
        return build_runtime_state_from_scm_report_payload(
            build_signal_conversion_report(
                simulate_gsce_clear=simulate_gsce_clear,
                simulate_realm_bis_clear=simulate_realm_bis_clear,
                simulate_all_clear=simulate_all_clear,
            )
        )
    return load_current_pipeline_state()


def _signal_lookup(runtime_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in runtime_state.get("per_signal_attribution", []):
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker:
            mapping[ticker] = row
    return mapping


def _signal_refinery_lookup(runtime_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    rows = runtime_state.get("signal_refinery", {}).get("validation_engine", {}).get("signals", [])
    if not isinstance(rows, list):
        return mapping
    for row in rows:
        if not isinstance(row, dict):
            continue
        signal_id = str(row.get("signal_id") or "").strip()
        ticker = str(row.get("ticker") or "").upper()
        if signal_id:
            mapping[signal_id] = row
        if ticker and ticker not in mapping:
            mapping[ticker] = row
    return mapping


def _position_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        status = str(row.get("status") or "").upper()
        if ticker and status == "OPEN":
            mapping[ticker] = row
    return mapping


def _side_for_action(action_type: str) -> str | None:
    action = str(action_type or "").upper()
    if action in OPEN_ENTRY_ACTIONS:
        return "BUY"
    if action in CLOSE_ACTIONS:
        return "SELL"
    return None


def _resolve_fill_price(
    ticker: str,
    fill_price_overrides: dict[str, float],
    seeded_open_positions: dict[str, dict[str, Any]],
) -> tuple[float, str]:
    normalized_ticker = str(ticker or "").upper()
    if normalized_ticker in fill_price_overrides:
        return float(fill_price_overrides[normalized_ticker]), "manual_cli"
    seeded_row = seeded_open_positions.get(normalized_ticker)
    if seeded_row is not None and seeded_row.get("current_price") is not None:
        return float(seeded_row["current_price"]), "seed_open_positions_current_price"
    return DEFAULT_FILL_PRICE, "deterministic_seeded_default"


def _append_once(path: Path, row: dict[str, Any], key_name: str, existing_ids: set[str]) -> bool:
    row_id = str(row.get(key_name) or "").strip()
    if not row_id or row_id in existing_ids:
        return False
    append_jsonl(path, row, stamp=False)
    existing_ids.add(row_id)
    return True


def _build_decision_row(
    action_row: dict[str, Any],
    signal_row: dict[str, Any] | None,
    signal_context_row: dict[str, Any] | None,
    runtime_state: dict[str, Any],
    decision_type: str | None = None,
    approval_state: str = "PENDING_HUMAN_APPROVAL",
) -> dict[str, Any]:
    action_type = decision_type or str(action_row.get("action") or "UNKNOWN").upper()
    signal_id = str((signal_row or {}).get("signal_id") or action_row.get("signal_id") or "")
    ticker = str(action_row.get("ticker") or (signal_row or {}).get("ticker") or "").upper()
    context_row = signal_context_row if isinstance(signal_context_row, dict) else {}
    governance = (
        action_row.get("execution_governance", {})
        if isinstance(action_row.get("execution_governance"), dict)
        else {}
    )
    fpeg = governance.get("fpeg", {}) if isinstance(governance.get("fpeg"), dict) else {}
    cvg = governance.get("cvg", {}) if isinstance(governance.get("cvg"), dict) else {}
    slg = governance.get("slg", {}) if isinstance(governance.get("slg"), dict) else {}
    decision_id = _stable_id(
        "paper_decision",
        get_run_id(),
        signal_id or ticker,
        action_type,
    )
    priority = float(action_row.get("priority_score", 0.0) or 0.0)
    return stamp_payload(
        {
            "artifact_kind": "paper_decision",
            "decision_id": decision_id,
            "signal_id": signal_id,
            "ticker": ticker,
            "action_type": action_type,
            "conviction_score": round(priority, 3),
            "confidence_score": round(priority, 3),
            "decision_reasons": list(action_row.get("reasons", [])),
            "decision_source": "action_engine",
            "approval_state": approval_state,
            "suggestion_only": bool(governance.get("suggestion_only", True)),
            "human_execution_required": bool(
                governance.get("human_execution_required", True)
            ),
            "delegation_permitted": bool(governance.get("delegation_permitted", False)),
            "governance_state": str(fpeg.get("fpeg_state") or "unassessed"),
            "first_principles_gate_state": str(fpeg.get("fpeg_state") or "unassessed"),
            "first_principles_gate_score": fpeg.get("fpeg_score"),
            "competence_validation_state": str(cvg.get("cvg_state") or "unassessed"),
            "structured_learning_gate_state": str(slg.get("slg_state") or "unassessed"),
            "entry_light_score": context_row.get("light_score"),
            "entry_shadow_score": context_row.get("shadow_score"),
            "entry_moon_phase": context_row.get("moon_phase"),
            "entry_temporal_position": context_row.get("temporal_position"),
            "entry_light_velocity": context_row.get("light_velocity"),
            "entry_shadow_velocity": context_row.get("shadow_velocity"),
            "entry_crowding_score": context_row.get("crowding_score"),
            "entry_full_moon_trap_flag": context_row.get("full_moon_trap_flag"),
            "entry_edge_context_score": context_row.get("edge_context_score"),
            "entry_visibility_timing_method": context_row.get("visibility_timing_method"),
            "decided_at": utc_timestamp(),
        },
        runtime_state=runtime_state,
    )


def _build_order_row(
    decision_row: dict[str, Any],
    side: str,
    requested_qty: float,
    position_id: str | None,
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    paper_order_id = _stable_id(
        "paper_order",
        decision_row["decision_id"],
        decision_row["ticker"],
        side,
        requested_qty,
    )
    return stamp_payload(
        {
            "artifact_kind": "paper_order",
            "paper_order_id": paper_order_id,
            "decision_id": decision_row["decision_id"],
            "signal_id": decision_row["signal_id"],
            "position_id": position_id,
            "ticker": decision_row["ticker"],
            "side": side,
            "requested_qty": float(requested_qty),
            "order_status": "FILLED",
            "created_at": utc_timestamp(),
            "order_type": "MARKET_SIM",
        },
        runtime_state=runtime_state,
    )


def _build_fill_row(
    order_row: dict[str, Any],
    fill_price: float,
    fill_source: str,
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    fill_qty = float(order_row["requested_qty"])
    paper_fill_id = _stable_id(
        "paper_fill",
        order_row["paper_order_id"],
        order_row["ticker"],
        fill_qty,
        fill_price,
        fill_source,
    )
    return stamp_payload(
        {
            "artifact_kind": "paper_fill",
            "paper_fill_id": paper_fill_id,
            "paper_order_id": order_row["paper_order_id"],
            "decision_id": order_row["decision_id"],
            "signal_id": order_row["signal_id"],
            "position_id": order_row.get("position_id"),
            "ticker": order_row["ticker"],
            "side": order_row["side"],
            "fill_price": round(float(fill_price), 4),
            "fill_qty": fill_qty,
            "filled_at": utc_timestamp(),
            "fill_source": fill_source,
            "slippage_bps": 0.0,
        },
        runtime_state=runtime_state,
    )


def _build_open_position_row(
    decision_row: dict[str, Any],
    order_row: dict[str, Any],
    fill_row: dict[str, Any],
) -> dict[str, Any]:
    position_id = _stable_id(
        "paper_position",
        decision_row["decision_id"],
        order_row["paper_order_id"],
        fill_row["paper_fill_id"],
    )
    fill_price = float(fill_row["fill_price"])
    fill_qty = float(fill_row["fill_qty"])
    return {
        "position_id": position_id,
        "decision_id": decision_row["decision_id"],
        "paper_order_id": order_row["paper_order_id"],
        "paper_fill_id": fill_row["paper_fill_id"],
        "signal_id": decision_row["signal_id"],
        "ticker": decision_row["ticker"],
        "side": order_row["side"],
        "avg_entry_price": round(fill_price, 4),
        "qty": fill_qty,
        "opened_at": fill_row["filled_at"],
        "latest_mark": round(fill_price, 4),
        "unrealized_pnl": 0.0,
        "status": "OPEN",
    }


def _realized_pnl(side: str, avg_entry_price: float, exit_price: float, qty: float) -> float:
    normalized_side = str(side or "").upper()
    if normalized_side == "SELL":
        return round((avg_entry_price - exit_price) * qty, 4)
    return round((exit_price - avg_entry_price) * qty, 4)


def _build_close_decision_row(
    position_row: dict[str, Any],
    close_reason: str,
    runtime_state: dict[str, Any],
    decision_source: str = "paper_close_cli",
) -> dict[str, Any]:
    decision_id = _stable_id(
        "paper_decision",
        get_run_id(),
        position_row["position_id"],
        close_reason,
        "CLOSE_POSITION",
    )
    return stamp_payload(
        {
            "artifact_kind": "paper_decision",
            "decision_id": decision_id,
            "signal_id": position_row.get("signal_id", ""),
            "ticker": position_row["ticker"],
            "action_type": "CLOSE_POSITION",
            "conviction_score": 1.0,
            "confidence_score": 1.0,
            "decision_reasons": [close_reason],
            "decision_source": decision_source,
            "decided_at": utc_timestamp(),
        },
        runtime_state=runtime_state,
    )


def _build_close_row(
    position_row: dict[str, Any],
    decision_row: dict[str, Any],
    order_row: dict[str, Any],
    fill_row: dict[str, Any],
    close_reason: str,
    close_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    realized_pnl = _realized_pnl(
        side=position_row["side"],
        avg_entry_price=float(position_row["avg_entry_price"]),
        exit_price=float(fill_row["fill_price"]),
        qty=float(fill_row["fill_qty"]),
    )
    close_id = _stable_id(
        "paper_close",
        position_row["position_id"],
        order_row["paper_order_id"],
        fill_row["paper_fill_id"],
        close_reason,
    )
    row = {
        "artifact_kind": "paper_close",
        "close_id": close_id,
        "position_id": position_row["position_id"],
        "ticker": position_row["ticker"],
        "decision_id": decision_row["decision_id"],
        "paper_order_id": order_row["paper_order_id"],
        "paper_fill_id": fill_row["paper_fill_id"],
        "opening_decision_id": position_row.get("decision_id"),
        "opening_paper_order_id": position_row.get("paper_order_id"),
        "opening_paper_fill_id": position_row.get("paper_fill_id"),
        "signal_id": position_row.get("signal_id", ""),
        "exit_price": round(float(fill_row["fill_price"]), 4),
        "realized_pnl": realized_pnl,
        "closed_at": fill_row["filled_at"],
        "close_reason": close_reason,
    }
    if isinstance(close_context, dict):
        row.update(close_context)
    return row


def sync_paper_execution(
    runtime_state: dict[str, Any] | None = None,
    action_report: dict[str, Any] | None = None,
    decision_ledger_path: Path | None = None,
    order_ledger_path: Path | None = None,
    fill_ledger_path: Path | None = None,
    paper_positions_path: Path | None = None,
    fill_price_overrides: dict[str, float] | None = None,
    requested_qty: float = DEFAULT_ORDER_QTY,
    allow_entry_execution: bool = False,
    simulate_gsce_clear: bool = False,
    simulate_realm_bis_clear: bool = False,
    simulate_all_clear: bool = False,
) -> dict[str, Any]:
    state = runtime_state or _build_runtime_state(
        simulate_gsce_clear=simulate_gsce_clear,
        simulate_realm_bis_clear=simulate_realm_bis_clear,
        simulate_all_clear=simulate_all_clear,
    )
    _ensure_non_live_only(state)
    report = action_report or build_action_report(
        runtime_state=state,
        write_runtime=False,
    )

    decisions_path = decision_ledger_path or PAPER_DECISION_LEDGER_PATH
    orders_path = order_ledger_path or PAPER_ORDER_LEDGER_PATH
    fills_path = fill_ledger_path or PAPER_FILL_LEDGER_PATH
    positions_path = paper_positions_path or PAPER_POSITIONS_PATH
    overrides = {str(key).upper(): float(value) for key, value in (fill_price_overrides or {}).items()}
    paper_enabled = _paper_enabled(state)
    seeded_open_positions, _ = load_open_positions(OPEN_POSITIONS_PATH)
    seeded_open_map = _position_lookup(
        [
            {
                "ticker": row.get("ticker"),
                "status": row.get("state"),
                "current_price": row.get("current_price"),
            }
            for row in seeded_open_positions
        ]
    )
    signal_refinery_state = state.get("signal_refinery")
    if not isinstance(signal_refinery_state, dict) or not isinstance(
        signal_refinery_state.get("validation_engine"),
        dict,
    ):
        try:
            from scripts.signal_refinery import build_signal_refinery_report
            from scripts.trend_engine import build_trend_report
        except ModuleNotFoundError:
            from signal_refinery import build_signal_refinery_report
            from trend_engine import build_trend_report
        state["signal_refinery"] = build_signal_refinery_report(
            runtime_state=state,
            trend_report=build_trend_report(write_runtime=False),
            write_runtime=False,
        )
    paper_positions = _load_paper_positions(positions_path)
    paper_position_map = _position_lookup(paper_positions)
    signal_lookup = _signal_lookup(state)
    signal_refinery_lookup = _signal_refinery_lookup(state)

    existing_decision_ids = _load_existing_ids(decisions_path, "decision_id")
    existing_order_ids = _load_existing_ids(orders_path, "paper_order_id")
    existing_fill_ids = _load_existing_ids(fills_path, "paper_fill_id")

    decisions_recorded = 0
    orders_created = 0
    fills_recorded = 0
    positions_opened = 0
    governance_blocked_entries = 0

    for action_row in report.get("actions", []):
        ticker = str(action_row.get("ticker") or "").upper()
        signal_row = signal_lookup.get(ticker)
        signal_context_row = signal_refinery_lookup.get(
            str((signal_row or {}).get("signal_id") or "").strip()
        ) or signal_refinery_lookup.get(ticker)
        governance = (
            action_row.get("execution_governance", {})
            if isinstance(action_row.get("execution_governance"), dict)
            else {}
        )
        fpeg_state = str(
            (
                governance.get("fpeg", {})
                if isinstance(governance.get("fpeg"), dict)
                else {}
            ).get("fpeg_state")
            or "unassessed"
        )
        approval_state = (
            "APPROVED_BY_HUMAN_FOR_PAPER"
            if allow_entry_execution and fpeg_state != "insufficient_reasoning"
            else "PENDING_HUMAN_APPROVAL"
        )
        decision_row = _build_decision_row(
            action_row,
            signal_row,
            signal_context_row,
            state,
            approval_state=approval_state,
        )
        if _append_once(decisions_path, decision_row, "decision_id", existing_decision_ids):
            decisions_recorded += 1

        if not paper_enabled:
            continue

        side = _side_for_action(decision_row["action_type"])
        if side != "BUY":
            continue
        if not allow_entry_execution:
            governance_blocked_entries += 1
            continue
        if fpeg_state == "insufficient_reasoning":
            governance_blocked_entries += 1
            continue
        if ticker in paper_position_map:
            continue

        order_row = _build_order_row(
            decision_row=decision_row,
            side=side,
            requested_qty=requested_qty,
            position_id=None,
            runtime_state=state,
        )
        fill_price, fill_source = _resolve_fill_price(
            ticker=ticker,
            fill_price_overrides=overrides,
            seeded_open_positions=seeded_open_map,
        )
        fill_row = _build_fill_row(
            order_row=order_row,
            fill_price=fill_price,
            fill_source=fill_source,
            runtime_state=state,
        )
        position_row = _build_open_position_row(
            decision_row=decision_row,
            order_row=order_row,
            fill_row=fill_row,
        )
        order_row["position_id"] = position_row["position_id"]
        fill_row["position_id"] = position_row["position_id"]

        if _append_once(orders_path, order_row, "paper_order_id", existing_order_ids):
            orders_created += 1
        if _append_once(fills_path, fill_row, "paper_fill_id", existing_fill_ids):
            fills_recorded += 1
        if ticker not in paper_position_map:
            paper_positions.append(position_row)
            paper_position_map[ticker] = position_row
            positions_opened += 1

    _write_paper_positions(paper_positions, runtime_state=state, path=positions_path)

    return {
        "paper_execution_enabled": paper_enabled,
        "entry_execution_approved": allow_entry_execution,
        "operating_mode": stamp_payload({}, runtime_state=state)["operating_mode"],
        "truth_origin": stamp_payload({}, runtime_state=state)["truth_origin"],
        "decisions_recorded": decisions_recorded,
        "orders_created": orders_created,
        "fills_recorded": fills_recorded,
        "positions_opened": positions_opened,
        "governance_blocked_entries": governance_blocked_entries,
        "open_position_count": sum(
            1 for row in paper_positions if str(row.get("status") or "").upper() == "OPEN"
        ),
        "decision_ledger_path": repo_relative(decisions_path),
        "order_ledger_path": repo_relative(orders_path),
        "fill_ledger_path": repo_relative(fills_path),
        "paper_positions_path": repo_relative(positions_path),
    }


def close_paper_position(
    position_id: str,
    exit_price: float,
    close_reason: str,
    runtime_state: dict[str, Any] | None = None,
    decision_ledger_path: Path | None = None,
    order_ledger_path: Path | None = None,
    fill_ledger_path: Path | None = None,
    close_ledger_path: Path | None = None,
    paper_positions_path: Path | None = None,
    fill_source: str = "manual_close",
    decision_source: str = "paper_close_cli",
    close_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = runtime_state or load_current_pipeline_state()
    _ensure_non_live_only(state)
    if not _paper_enabled(state):
        raise ValueError("paper execution is disabled; enable PIPELINE_ENABLE_PAPER_EXECUTION first")

    decisions_path = decision_ledger_path or PAPER_DECISION_LEDGER_PATH
    orders_path = order_ledger_path or PAPER_ORDER_LEDGER_PATH
    fills_path = fill_ledger_path or PAPER_FILL_LEDGER_PATH
    closes_path = close_ledger_path or PAPER_CLOSE_LEDGER_PATH
    positions_path = paper_positions_path or PAPER_POSITIONS_PATH

    paper_positions = _load_paper_positions(positions_path)
    target = None
    remaining_positions: list[dict[str, Any]] = []
    for row in paper_positions:
        if str(row.get("position_id") or "") == position_id:
            target = dict(row)
        else:
            remaining_positions.append(dict(row))
    if target is None:
        raise ValueError(f"paper position not found: {position_id}")
    if str(target.get("status") or "").upper() != "OPEN":
        raise ValueError(f"paper position is not open: {position_id}")

    existing_decision_ids = _load_existing_ids(decisions_path, "decision_id")
    existing_order_ids = _load_existing_ids(orders_path, "paper_order_id")
    existing_fill_ids = _load_existing_ids(fills_path, "paper_fill_id")
    existing_close_ids = _load_existing_ids(closes_path, "close_id")

    decision_row = _build_close_decision_row(
        target,
        close_reason=close_reason,
        runtime_state=state,
        decision_source=decision_source,
    )
    order_row = _build_order_row(
        decision_row=decision_row,
        side="SELL",
        requested_qty=float(target["qty"]),
        position_id=target["position_id"],
        runtime_state=state,
    )
    fill_row = _build_fill_row(
        order_row=order_row,
        fill_price=float(exit_price),
        fill_source=fill_source,
        runtime_state=state,
    )
    fill_row["position_id"] = target["position_id"]
    close_row = stamp_payload(
        _build_close_row(
            position_row=target,
            decision_row=decision_row,
            order_row=order_row,
            fill_row=fill_row,
            close_reason=close_reason,
            close_context=close_context,
        ),
        runtime_state=state,
    )

    _append_once(decisions_path, decision_row, "decision_id", existing_decision_ids)
    _append_once(orders_path, order_row, "paper_order_id", existing_order_ids)
    _append_once(fills_path, fill_row, "paper_fill_id", existing_fill_ids)
    _append_once(closes_path, close_row, "close_id", existing_close_ids)
    _write_paper_positions(remaining_positions, runtime_state=state, path=positions_path)

    return {
        "position_closed": True,
        "position_id": target["position_id"],
        "signal_id": target.get("signal_id", ""),
        "ticker": target["ticker"],
        "close_id": close_row["close_id"],
        "decision_id": decision_row["decision_id"],
        "paper_order_id": order_row["paper_order_id"],
        "paper_fill_id": fill_row["paper_fill_id"],
        "exit_price": close_row["exit_price"],
        "realized_pnl": close_row["realized_pnl"],
        "close_reason": close_row["close_reason"],
        "closed_at": close_row["closed_at"],
        "close_ledger_path": repo_relative(closes_path),
        "paper_positions_path": repo_relative(positions_path),
    }


def format_sync_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Paper Execution Sync",
            f"paper_execution_enabled={str(report['paper_execution_enabled']).lower()}",
            f"entry_execution_approved={str(report['entry_execution_approved']).lower()}",
            f"operating_mode={report['operating_mode']}",
            f"truth_origin={report['truth_origin']}",
            f"decisions_recorded={report['decisions_recorded']}",
            f"orders_created={report['orders_created']}",
            f"fills_recorded={report['fills_recorded']}",
            f"positions_opened={report['positions_opened']}",
            f"governance_blocked_entries={report['governance_blocked_entries']}",
            f"open_position_count={report['open_position_count']}",
        ]
    )


def format_close_summary(report: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Paper Position Close",
            f"position_closed={str(report['position_closed']).lower()}",
            f"position_id={report['position_id']}",
            f"ticker={report['ticker']}",
            f"close_id={report['close_id']}",
            f"realized_pnl={report['realized_pnl']}",
        ]
    )


def _parse_fill_price_overrides(values: list[str]) -> dict[str, float]:
    overrides: dict[str, float] = {}
    for raw in values:
        ticker, sep, price_text = str(raw).partition("=")
        if not sep or not ticker.strip():
            raise ValueError(
                f"invalid --fill-price value {raw!r}; expected TICKER=PRICE"
            )
        overrides[ticker.strip().upper()] = float(price_text)
    return overrides


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Persist paper decisions, orders, fills, open positions, and closes with explicit non-live lineage."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Record decision candidates and emit eligible paper orders/fills when paper execution is enabled.",
    )
    sync_parser.add_argument(
        "--requested-qty",
        type=float,
        default=DEFAULT_ORDER_QTY,
        help="Requested quantity for new paper entry orders (default: 1.0).",
    )
    sync_parser.add_argument(
        "--fill-price",
        action="append",
        default=[],
        help="Override deterministic fill price for a ticker, e.g. RTX=102.5. May be repeated.",
    )
    sync_parser.add_argument(
        "--approve-review-for-entry",
        action="store_true",
        help=(
            "Explicit human approval required to convert REVIEW_FOR_ENTRY suggestions "
            "into paper orders/fills. Without this flag, sync stays suggestion-only."
        ),
    )
    simulation = sync_parser.add_mutually_exclusive_group()
    simulation.add_argument(
        "--simulate-gsce-clear",
        action="store_true",
        help="Use the GSCE-clear scenario instead of the current live seeded state.",
    )
    simulation.add_argument(
        "--simulate-realm-bis-clear",
        action="store_true",
        help="Use the REALM_BIS-clear scenario instead of the current live seeded state.",
    )
    simulation.add_argument(
        "--simulate-all-clear",
        action="store_true",
        help="Use the fully cleared scenario instead of the current live seeded state.",
    )
    sync_mode = sync_parser.add_mutually_exclusive_group()
    sync_mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    sync_mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")

    close_parser = subparsers.add_parser(
        "close",
        help="Close one open paper position and persist close lineage.",
    )
    close_parser.add_argument("--position-id", required=True, help="Open paper position id to close.")
    close_parser.add_argument("--exit-price", required=True, type=float, help="Deterministic paper exit price.")
    close_parser.add_argument("--close-reason", required=True, help="Short close reason label.")
    close_mode = close_parser.add_mutually_exclusive_group()
    close_mode.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    close_mode.add_argument("--summary", action="store_true", help="Emit a compact human-readable summary.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "sync":
            report = sync_paper_execution(
                requested_qty=float(args.requested_qty),
                fill_price_overrides=_parse_fill_price_overrides(args.fill_price),
                allow_entry_execution=bool(args.approve_review_for_entry),
                simulate_gsce_clear=args.simulate_gsce_clear,
                simulate_realm_bis_clear=args.simulate_realm_bis_clear,
                simulate_all_clear=args.simulate_all_clear,
            )
            if args.summary:
                print(format_sync_summary(report))
            else:
                print(json.dumps(report, indent=2))
            return 0

        if args.command == "close":
            report = close_paper_position(
                position_id=args.position_id,
                exit_price=float(args.exit_price),
                close_reason=args.close_reason,
            )
            if args.summary:
                print(format_close_summary(report))
            else:
                print(json.dumps(report, indent=2))
            return 0
    except ValueError as exc:
        parser.exit(2, f"error: {exc}\n")

    parser.exit(2, "error: unsupported command\n")


if __name__ == "__main__":
    raise SystemExit(main())
