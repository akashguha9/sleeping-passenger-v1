"""Operational truth surface — one honest status object for the whole MVP.

Close-the-Loop sprint (2026-07-04), "Truth Surface Unification".  The
forensic audit found the system's health claims fragmented and flattering:
installation health displayed as operational health ("HEALTHY 10/10" from a
scheduler that had never run), zero-persistence sources classified healthy,
artifact-served cockpit panels with no staleness checks, and no single place
where N (real matured outcomes), holdings freshness, and stop coverage were
visible together.

This module computes ONE object that answers, with evidence, the questions
an operator (or investor) must ask before trusting any advisory output.

Hard rules (each encoded in ``compute_truth_surface`` and pinned by tests):

* ``calibration_status`` can never say calibrated while the repo's own gate
  (N >= 200, Brier <= 0.25, ECE <= 0.10) fails; below N=50 it is
  UNCALIBRATED_INSUFFICIENT_N; at N=0 it is NO_REAL_OUTCOME_EVIDENCE.
* Any active holding missing a stop -> overall state is at best BLOCKED.
* Stale/missing holdings truth -> DEGRADED / BROKEN, never HEALTHY.
* A BROKEN scheduler record -> BROKEN.
* Stale operator artifacts (cards/cockpit/scheduler record) -> DEGRADED.
* Key sources with zero persisted rows beyond tolerance -> DEGRADED.
* HEALTHY requires every axis clean AND N > 0: install success alone can
  never render HEALTHY ("install healthy, operational evidence incomplete").

Advisory-only, read-only: this module never writes anything unless asked to
via --write, and then only its own report artifact.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

try:  # package layout
    from scripts import persistence
    from scripts.advisory_contract import advisory_safety_stamps
    from scripts.holdings_truth_gate import load_holdings_truth_gate
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    import persistence  # type: ignore[no-redef]
    from advisory_contract import advisory_safety_stamps  # type: ignore[no-redef]
    from holdings_truth_gate import load_holdings_truth_gate  # type: ignore[no-redef]
    from runtime_common import REPO_ROOT  # type: ignore[no-redef]

STATE_HEALTHY = "HEALTHY"
STATE_DEGRADED = "DEGRADED"
STATE_BLOCKED = "BLOCKED"
STATE_BROKEN = "BROKEN"
_STATE_RANK = {STATE_HEALTHY: 0, STATE_DEGRADED: 1, STATE_BLOCKED: 2, STATE_BROKEN: 3}

CAL_NO_EVIDENCE = "NO_REAL_OUTCOME_EVIDENCE"
CAL_INSUFFICIENT = "UNCALIBRATED_INSUFFICIENT_N"
CAL_MEASURED_NOT_CALIBRATED = "MEASURED_NOT_CALIBRATED"
CAL_CALIBRATED = "CALIBRATED"

DISPLAY_MIN_N = 50       # below this the UI must say "uncalibrated"
GATE_MIN_N = 200         # repo calibration gate
GATE_MAX_BRIER = 0.25
GATE_MAX_ECE = 0.10

DEFAULT_ARTIFACT_MAX_AGE_HOURS = 26.0   # daily cadence + slack
DEFAULT_SOURCE_MAX_SILENT_DAYS = 7.0    # zero-persisted tolerance
KEY_SOURCES = ("market_data", "kalshi", "polymarket")

RISK_ENGINE_SOURCE = "verified_current_holdings (scripts/holdings_truth_gate)"

REPORT_PATH = REPO_ROOT / "runtime" / "truth_surface.json"


def _now(now_utc: datetime | None) -> datetime:
    return now_utc or datetime.now(timezone.utc)


def _parse_iso(ts: Any) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_minutes(ts: Any, now: datetime) -> float | None:
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return round((now - dt).total_seconds() / 60.0, 1)


def _worst(a: str, b: str) -> str:
    return a if _STATE_RANK[a] >= _STATE_RANK[b] else b


def _outcome_counts(db_path: Any, now: datetime) -> dict[str, Any]:
    out = {
        "n_real_forward": 0, "brier": None, "ece": None, "query_ok": False,
        "locked_last_7d": 0, "matured_last_7d": 0, "pending_horizon": 0,
        "due_unmatured": 0,
    }
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return out
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE is_real_outcome = 1 AND outcome_label IN (0, 1) "
            "AND outcome_kind = 'real_forward' "
            "AND (excluded_from_calibration IS NULL OR excluded_from_calibration = 0)"
        ).fetchone()
        out["n_real_forward"] = int(row[0])
        out["query_ok"] = True
        if out["n_real_forward"]:
            pairs = conn.execute(
                "SELECT model_probability, outcome_label FROM "
                "decision_probability_snapshots WHERE is_real_outcome = 1 "
                "AND outcome_label IN (0,1) AND outcome_kind = 'real_forward'"
            ).fetchall()
            out["brier"] = round(
                sum((float(p) - float(y)) ** 2 for p, y in pairs) / len(pairs), 6
            )
        # Feed-the-Loop sprint: evidence-compounding velocities.
        from datetime import timedelta as _td

        cutoff = (now - _td(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        out["locked_last_7d"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND timestamp_utc >= ?",
            (cutoff,),
        ).fetchone()[0])
        out["matured_last_7d"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE is_real_outcome = 1 AND outcome_timestamp_utc >= ?",
            (cutoff,),
        ).fetchone()[0])
        out["pending_horizon"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND outcome_label IS NULL "
            "AND horizon_close_utc > ?",
            (now_iso,),
        ).fetchone()[0])
        out["due_unmatured"] = int(conn.execute(
            "SELECT COUNT(*) FROM decision_probability_snapshots "
            "WHERE forward_outcome_eligible = 1 AND outcome_label IS NULL "
            "AND horizon_close_utc <= ?",
            (now_iso,),
        ).fetchone()[0])
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    return out


def _discovery_axis(now: datetime, snapshot_path: Any = None) -> dict[str, Any]:
    """Fresh-discovery status from the live snapshot payload + its canary.

    Honors DISCOVERY_SNAPSHOT_PATH (test isolation — conftest redirects it so
    hermetic tests never read the operator's real payload).
    """
    snap_path = Path(
        snapshot_path
        if snapshot_path is not None
        else os.environ.get("DISCOVERY_SNAPSHOT_PATH")
        or REPO_ROOT / "data" / "daily_payload" / "today_market_snapshot.json"
    )
    axis: dict[str, Any] = {
        "status": "BLOCKED", "artifact_age_minutes": None,
        "canary_status": None, "is_live": None, "path": str(snap_path),
    }
    try:
        payload = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        axis["status"] = "BLOCKED"
        axis["reason"] = "SNAPSHOT_MISSING_OR_UNREADABLE"
        return axis
    created = payload.get("artifact_created_at") or payload.get("generated_at_utc")
    age_min = _age_minutes(created, now)
    axis["artifact_age_minutes"] = age_min
    axis["is_live"] = bool(payload.get("is_live"))
    canary = payload.get("provider_canary") or {}
    axis["canary_status"] = canary.get("status")
    if age_min is None or age_min > 50 * 60:
        axis["status"] = "BLOCKED"
        axis["reason"] = "ARTIFACT_STALE_OVER_50H"
    elif age_min > 26 * 60:
        axis["status"] = "DEGRADED"
        axis["reason"] = "ARTIFACT_STALE_OVER_26H"
    elif canary.get("status") != "PASS":
        axis["status"] = "DEGRADED"
        axis["reason"] = f"CANARY_{canary.get('status') or 'ABSENT'}"
    elif not payload.get("is_live"):
        axis["status"] = "DEGRADED"
        axis["reason"] = "PAYLOAD_NOT_LIVE"
    else:
        axis["status"] = "OK"
        axis["reason"] = None
    return axis


def _calibration_status(n: int, brier: float | None, ece: float | None) -> str:
    if n <= 0:
        return CAL_NO_EVIDENCE
    if n < DISPLAY_MIN_N:
        return CAL_INSUFFICIENT
    gate_ok = (
        n >= GATE_MIN_N
        and brier is not None
        and brier <= GATE_MAX_BRIER
        and (ece is None or ece <= GATE_MAX_ECE)
    )
    return CAL_CALIBRATED if gate_ok else CAL_MEASURED_NOT_CALIBRATED


def _rows_persisted_status(
    db_path: Any, now: datetime, max_silent_days: float
) -> dict[str, Any]:
    axis: dict[str, Any] = {"sources": {}, "status": "OK", "query_ok": False}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        axis["status"] = "DB_UNAVAILABLE"
        return axis
    try:
        for src in KEY_SOURCES:
            row = conn.execute(
                "SELECT MAX(fetched_at) FROM signal_events WHERE source_name = ?",
                (src,),
            ).fetchone()
            last = row[0]
            age_days = None
            dt = _parse_iso(last)
            if dt is not None:
                age_days = round((now - dt).total_seconds() / 86400.0, 2)
            silent = age_days is None or age_days > max_silent_days
            axis["sources"][src] = {
                "last_persisted_at": last,
                "age_days": age_days,
                "status": "DEGRADED_ZERO_PERSISTED" if silent else "OK",
            }
        axis["query_ok"] = True
    except sqlite3.Error:
        axis["status"] = "DB_UNAVAILABLE"
        return axis
    finally:
        conn.close()
    if any(s["status"] != "OK" for s in axis["sources"].values()):
        axis["status"] = "DEGRADED"
    return axis


def _artifact_age(path: Path, now: datetime, ts_keys: Sequence[str]) -> dict[str, Any]:
    info: dict[str, Any] = {"path": str(path), "exists": path.exists(),
                            "generated_at": None, "age_minutes": None}
    if not path.exists():
        return info
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ts_keys:
            if payload.get(key):
                info["generated_at"] = payload[key]
                break
    except (OSError, ValueError):
        pass
    if info["generated_at"] is None:
        info["generated_at"] = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    info["age_minutes"] = _age_minutes(info["generated_at"], now)
    return info


def compute_truth_surface(
    *,
    db_path: Any = None,
    holdings_path: Any = None,
    cards_json_path: Any = None,
    scheduler_last_run_path: Any = None,
    discovery_snapshot_path: Any = None,
    now_utc: datetime | None = None,
    artifact_max_age_hours: float = DEFAULT_ARTIFACT_MAX_AGE_HOURS,
    source_max_silent_days: float = DEFAULT_SOURCE_MAX_SILENT_DAYS,
) -> dict[str, Any]:
    now = _now(now_utc)
    db = db_path if db_path is not None else persistence.DB_PATH

    # --- holdings / risk axis -------------------------------------------
    gate = load_holdings_truth_gate(
        path=holdings_path, db_path=db, now_utc=now
    )
    # --- outcome / calibration axis -------------------------------------
    oc = _outcome_counts(db, now)
    calibration_status = _calibration_status(oc["n_real_forward"], oc["brier"], oc["ece"])
    # --- discovery axis ---------------------------------------------------
    discovery = _discovery_axis(now, snapshot_path=discovery_snapshot_path)
    # Producer is "scheduled" when the daily loop's source carries the step
    # (the branch-stranding guard pins this; here we read the last run record
    # for the honest runtime view).
    producer_scheduled = False
    try:
        sched_probe = json.loads(Path(
            os.environ.get("NBI_ARTIFACT_DIR", str(REPO_ROOT / "runtime"))
        ).joinpath("nbi_scheduler_last_run.json").read_text(encoding="utf-8"))
        producer_scheduled = "producer_status" in sched_probe
    except (OSError, ValueError):
        producer_scheduled = False
    # --- rows-persisted axis ---------------------------------------------
    rows_axis = _rows_persisted_status(db, now, source_max_silent_days)
    # --- artifact freshness axis -----------------------------------------
    cards_path = Path(
        cards_json_path
        if cards_json_path is not None
        else (
            Path(os.environ["NBI_ARTIFACT_DIR"]) / "nbi_operator_cards.json"
            if os.environ.get("NBI_ARTIFACT_DIR")
            else REPO_ROOT / "runtime" / "nbi_operator_cards.json"
        )
    )
    sched_path = Path(
        scheduler_last_run_path
        if scheduler_last_run_path is not None
        else (
            Path(os.environ["NBI_ARTIFACT_DIR"]) / "nbi_scheduler_last_run.json"
            if os.environ.get("NBI_ARTIFACT_DIR")
            else REPO_ROOT / "runtime" / "nbi_scheduler_last_run.json"
        )
    )
    cards_info = _artifact_age(cards_path, now, ("generated_at",))
    sched_info = _artifact_age(sched_path, now, ("timestamp",))
    sched_status = None
    if sched_info["exists"]:
        try:
            sched_status = json.loads(sched_path.read_text(encoding="utf-8")).get("status")
        except (OSError, ValueError):
            sched_status = None

    max_age_min = artifact_max_age_hours * 60.0
    artifacts_stale = [
        info["path"]
        for info in (cards_info, sched_info)
        if not info["exists"]
        or (info["age_minutes"] is not None and info["age_minutes"] > max_age_min)
    ]

    # --- overall state ----------------------------------------------------
    state = STATE_HEALTHY
    reasons: list[str] = []

    if sched_status in ("BROKEN", "BROKEN_UNSAFE", "FAILED"):
        state = _worst(state, STATE_BROKEN)
        reasons.append(f"scheduler last run status is {sched_status}")
    elif sched_status is None:
        state = _worst(state, STATE_DEGRADED)
        reasons.append("no scheduler run record found (never ran, or record unreadable)")

    if gate["status"] == "HOLDINGS_TRUTH_MISSING":
        state = _worst(state, STATE_BROKEN)
        reasons.append("canonical holdings truth file is missing")
    elif gate["status"] in ("HOLDINGS_TRUTH_STALE", "HOLDINGS_TRUTH_INVALID"):
        state = _worst(state, STATE_DEGRADED)
        reasons.append(f"holdings truth is {gate['status']} (age {gate['age_days']} days)")
    elif gate.get("freshness_state") == "DEGRADED":
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            f"holdings freshness DEGRADED (age {gate['age_days']} days; "
            "re-verify within 1 day for FRESH)"
        )

    if gate["canonical_holding_count"] > 0 and gate["missing_stop_count"] > 0:
        state = _worst(state, STATE_BLOCKED)
        reasons.append(
            f"{gate['missing_stop_count']}/{gate['canonical_holding_count']} "
            "active holdings have no stop recorded (no stop -> no healthy)"
        )
    if gate.get("unconfirmed_stop_count"):
        state = _worst(state, STATE_BLOCKED)
        reasons.append(
            f"{gate['unconfirmed_stop_count']} stop(s) present but not "
            "operator-confirmed — a number alone is not truth"
        )
    if gate["leveraged_without_stop_count"] > 0:
        state = _worst(state, STATE_BLOCKED)
        reasons.append(
            f"CRITICAL: {gate['leveraged_without_stop_count']} leveraged "
            "position(s) without usable stops"
        )
    if producer_scheduled and oc["locked_last_7d"] == 0:
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            "evidence velocity is ZERO: no new locked predictions in 7 days "
            "despite the scheduled producer — the compounding loop stalled"
        )
    if oc["due_unmatured"] > 0:
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            f"{oc['due_unmatured']} horizon-elapsed prediction(s) awaiting "
            "maturation — run scripts/run_daily_outcome_maturation.py --write"
        )
    if discovery["status"] == "BLOCKED":
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            f"fresh discovery BLOCKED ({discovery.get('reason')})"
        )
    elif discovery["status"] == "DEGRADED":
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            f"fresh discovery DEGRADED ({discovery.get('reason')})"
        )

    if rows_axis["status"] != "OK":
        state = _worst(state, STATE_DEGRADED)
        silent = [k for k, v in rows_axis.get("sources", {}).items()
                  if v.get("status") != "OK"]
        reasons.append(
            "key sources with no persisted rows within tolerance: "
            + (", ".join(silent) if silent else rows_axis["status"])
        )

    if artifacts_stale:
        state = _worst(state, STATE_DEGRADED)
        reasons.append(f"stale/missing operator artifacts: {len(artifacts_stale)}")

    if oc["n_real_forward"] == 0:
        state = _worst(state, STATE_DEGRADED)
        reasons.append(
            "N=0 real matured outcomes — operational evidence incomplete; "
            "install success alone is not operational health"
        )

    # The one thing the operator should do next, by priority.
    if gate["missing_stop_count"] or gate.get("unconfirmed_stop_count"):
        next_action = (
            "Confirm stops: python scripts/holdings_truth_gate.py "
            "--write-template, edit/confirm each entry, then "
            "--apply-confirmed --write"
        )
    elif gate["status"] != "OK":
        next_action = (
            "Re-verify holdings truth (set holdings_confirmed_current in the "
            "stop template and run --apply-confirmed --write)"
        )
    elif oc["due_unmatured"] > 0:
        next_action = (
            "Mature due predictions: python "
            "scripts/run_daily_outcome_maturation.py --write"
        )
    elif discovery["status"] != "OK":
        next_action = (
            "Refresh discovery: python "
            "scripts/refresh_fresh_discovery_live.py --write"
        )
    elif state != STATE_HEALTHY:
        next_action = "Review state_reasons — no single operator action mapped"
    else:
        next_action = "None — monitor; the loop is compounding"

    try:
        from scripts.operator_alert_bridge import latest_alerts as _latest_alerts

        recent_alerts = _latest_alerts(limit=8)
    except Exception:  # noqa: BLE001 - alerts are advisory to the surface
        recent_alerts = []

    return {
        "report": "operational_truth_surface",
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_operational_state": state,
        "state_reasons": reasons,
        "canonical_holding_count": gate["canonical_holding_count"],
        "active_holding_count": gate["canonical_holding_count"],
        "monitorable_position_count": gate["monitorable_position_count"],
        "unconfirmed_stop_count": gate.get("unconfirmed_stop_count", 0),
        "portfolio_stop_exposure": gate.get("portfolio_stop_exposure"),
        "portfolio_stop_exposure_fraction": gate.get(
            "portfolio_stop_exposure_fraction"
        ),
        "evidence_velocity_7d": round(oc["locked_last_7d"] / 7.0, 3),
        "maturation_velocity_7d": round(oc["matured_last_7d"] / 7.0, 3),
        "locked_predictions_last_7d": oc["locked_last_7d"],
        "matured_outcomes_last_7d": oc["matured_last_7d"],
        "pending_horizon_count": oc["pending_horizon"],
        "due_unmatured_count": oc["due_unmatured"],
        "producer_scheduled": producer_scheduled,
        "fresh_discovery_status": discovery["status"],
        "fresh_discovery": discovery,
        "provider_canary_status": discovery.get("canary_status"),
        "latest_alerts": recent_alerts,
        "next_required_operator_action": next_action,
        "holdings_truth_status": gate["status"],
        "holdings_freshness_age_minutes": (
            round(gate["age_days"] * 1440.0, 1)
            if isinstance(gate["age_days"], (int, float))
            else None
        ),
        "missing_stop_count": gate["missing_stop_count"],
        "leveraged_position_count": gate["leveraged_position_count"],
        "leveraged_without_stop_count": gate["leveraged_without_stop_count"],
        "latest_artifact_age_minutes": cards_info["age_minutes"],
        "artifacts": {"nbi_cards": cards_info, "scheduler_last_run": sched_info},
        "rows_persisted_status": rows_axis,
        "matured_real_outcome_count": oc["n_real_forward"],
        "brier_real_forward": oc["brier"],
        "calibration_status": calibration_status,
        "calibration_display_note": (
            "uncalibrated model score — do not read model probabilities as "
            "calibrated frequencies"
            if calibration_status != CAL_CALIBRATED
            else "calibrated within the repo gate"
        ),
        "risk_engine_source": RISK_ENGINE_SOURCE,
        "scheduler_status": sched_status or "NO_RUN_RECORD",
        **advisory_safety_stamps(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)
    surface = compute_truth_surface(db_path=args.db)
    if args.write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(surface, indent=2, default=str), encoding="utf-8"
        )
        surface["report_path"] = str(REPORT_PATH)
    print(json.dumps(surface, indent=2, default=str))
    return 0 if surface["overall_operational_state"] != STATE_BROKEN else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
