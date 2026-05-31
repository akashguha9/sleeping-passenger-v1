"""Evidence router — read-only, advisory-only cockpit evidence surface.

First Real Rows + Kanté Score Push sprint, Phase 2.

Exposes a family of strictly read-only ``GET /evidence/*`` routes so the cockpit
``RealEvidenceCards`` can consume *real backend evidence* instead of a permanent
DEGRADED fallback:

    GET /evidence/source-truth        canonical source activation truth
    GET /evidence/calibration         honest Brier/ECE corpus status
    GET /evidence/bundle              the real-evidence bundle (no real-money)
    GET /evidence/live-decision-path  the most recent advisory decision snapshot
    GET /evidence/capacity-risk       capacity / correlation risk (UNKNOWN==risk)
    GET /evidence/summary             a compact aggregate of the above

Hard safety contract (enforced here, mirrors the rest of the API surface):

* No file/DB mutation, no network, no broker calls — every builder is a pure
  read over the canonical SQLite DB and the persisted release artifacts.
* Secrets are stripped defensively before serialisation (``_strip_secrets``).
* Every response carries the advisory-only safety stamps: ``execution_gate`` is
  ``LOCKED``, ``broker_api_called`` is ``False``, ``ai_execution_count`` is ``0``.
* ``predictive_claim_allowed`` is surfaced verbatim from the calibration gate and
  can only ever be ``True`` when N>=200 real-forward pairs clear Brier/ECE — this
  router never sets it.
* When a source/artifact is missing the builder returns an honest DEGRADED /
  UNKNOWN envelope; it never invents LIVE / green state.
* Capacity that cannot be evaluated is reported as ``CAPACITY_UNKNOWN`` and
  treated as risk (``capacity_ok = False``) — missing context is never "safe".

The router works with or without FastAPI installed (a tiny shim mirrors the
``external_evidence_router`` pattern), so the default offline test suite can
import and exercise the pure builders with no web framework present.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised in shim mode
    _FASTAPI_AVAILABLE = False

    class APIRouter:  # type: ignore[no-redef]
        def __init__(self, *_a: Any, **_kw: Any) -> None:
            pass

        def get(self, *_a: Any, **_kw: Any):
            def decorator(fn):
                return fn

            return decorator


# Honest status vocabulary owned by this router.
STATUS_OK = "OK"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNKNOWN = "UNKNOWN"
PREDICTIVE_CLAIM_LOCKED = "PREDICTIVE_CLAIM_LOCKED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

# Defensive secret-key denylist (substring match, case-insensitive).
_SECRET_KEY_MARKERS = (
    "api_key",
    "apikey",
    "secret",
    "authorization",
    "private_key",
    "access_key",
    "access-signature",
    "bearer",
    "password",
    "token",
)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _release_dir() -> Path:
    return _repo_root() / "runtime" / "release"


def _safety_stamps() -> dict[str, Any]:
    """Advisory-only safety stamps shared by every response shape."""
    try:
        from scripts.advisory_contract import advisory_safety_stamps
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from advisory_contract import advisory_safety_stamps  # type: ignore
    out = dict(advisory_safety_stamps())
    out["advisory_only"] = True
    out["human_execution_required"] = True
    out["execution_gate"] = "LOCKED"
    out["broker_api_called"] = False
    out["ai_execution_count"] = 0
    out["real_money_ready"] = False
    return out


def _strip_secrets(value: Any) -> Any:
    """Recursively drop any key whose name looks secret-bearing."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            if any(marker in str(k).lower() for marker in _SECRET_KEY_MARKERS):
                continue
            cleaned[k] = _strip_secrets(v)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(v) for v in value]
    return value


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _db_path() -> Any:
    try:
        from scripts import persistence
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        import persistence  # type: ignore
    return persistence.DB_PATH


# --------------------------------------------------------------------------- #
# GET /evidence/source-truth
# --------------------------------------------------------------------------- #
def build_source_truth_payload(
    *,
    canary_path: Path | None = None,
    db_path: Any = None,
) -> dict[str, Any]:
    """Canonical source-activation truth (read-only).

    Prefers the persisted canary report (``real_evidence_canary.json``); each
    per-source row is reduced to the honest cockpit shape.  A source with
    ``rows_added == 0`` is never reported as live — that label comes straight
    from the canary's ``is_live_canonical`` field.
    """
    safety = _safety_stamps()
    path = canary_path or (_release_dir() / "real_evidence_canary.json")
    report = _load_json(path)

    sources: list[dict[str, Any]] = []
    real_count = 0
    fixture_count = 0
    if report is not None:
        for s in report.get("per_source", []) or []:
            if not isinstance(s, dict):
                continue
            activated = bool(s.get("activated"))
            canary_real = bool(s.get("canary_real"))
            if activated and canary_real:
                real_count += 1
            elif activated and not canary_real:
                fixture_count += 1
            sources.append({
                "source_name": s.get("source_name"),
                "api_health_status": s.get("api_health_status"),
                "canonical_signal_status": s.get("canonical_signal_status"),
                "rows_added": int(s.get("rows_added") or 0),
                "latest_canonical_signal_timestamp": s.get(
                    "latest_canonical_signal_timestamp"
                ),
                "canonical_age_hours": s.get("canonical_age_hours"),
                "is_live_canonical": bool(s.get("is_live_canonical")),
                "mock_flag": bool(s.get("mock_flag")),
                "backfill_flag": bool(s.get("backfill_flag")),
                "canary_real": canary_real,
                "source_truth_score": s.get("source_truth_score"),
            })

    status = STATUS_OK if report is not None else STATUS_DEGRADED
    payload: dict[str, Any] = {
        "status": status,
        "advisory_only": True,
        "execution_gate": "LOCKED",
        "real_source_activation_count": (
            int(report.get("real_source_activation_count", real_count))
            if report is not None
            else 0
        ),
        "fixture_source_activation_count": (
            int(report.get("fixture_source_activation_count", fixture_count))
            if report is not None
            else 0
        ),
        "live_canonical_count": (
            int(report.get("live_canonical_count", 0)) if report is not None else 0
        ),
        "C_global": report.get("C_global", 0.0) if report is not None else 0.0,
        "source_activation_target_met": (
            bool(report.get("source_activation_target_met", False))
            if report is not None
            else False
        ),
        "generated_at_utc": report.get("generated_at_utc") if report else None,
        "artifact_present": report is not None,
        "sources": sources,
    }
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/calibration
# --------------------------------------------------------------------------- #
def build_calibration_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Honest calibration-corpus status (read-only).

    ``predictive_claim_allowed`` is surfaced verbatim from the real-forward
    gate and stays ``False`` until N>=200 with Brier<=0.25 and ECE<=0.10.
    """
    safety = _safety_stamps()
    target = db_path if db_path is not None else _db_path()
    try:
        try:
            from scripts.real_calibration_evidence import build_calibration_evidence
            from scripts.decision_probability_snapshot import count_valid_p
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from real_calibration_evidence import build_calibration_evidence  # type: ignore
            from decision_probability_snapshot import count_valid_p  # type: ignore
        ev = build_calibration_evidence(target)
        n_valid_p = count_valid_p(target)
        status = STATUS_OK
    except Exception as exc:  # noqa: BLE001 - never crash the route
        payload = {
            "status": STATUS_DEGRADED,
            "reason": f"{type(exc).__name__}",
            "n_valid_p": 0,
            "n_real_forward": 0,
            "n_historical_proxy": 0,
            "brier_real_forward": None,
            "ece_real_forward": None,
            "logloss_real_forward": None,
            "calibration_status": INSUFFICIENT_EVIDENCE,
            "predictive_claim_allowed": False,
            "predictive_claim_label": PREDICTIVE_CLAIM_LOCKED,
        }
        payload.update(safety)
        return payload

    predictive = bool(ev.get("predictive_claim_allowed"))
    payload = {
        "status": status,
        "n_valid_p": int(n_valid_p),
        "n_real_forward": int(ev.get("n_real_forward", 0)),
        "n_historical_proxy": int(ev.get("n_historical_proxy", 0)),
        "brier_real_forward": ev.get("brier_real_forward"),
        "ece_real_forward": ev.get("ece_real_forward"),
        "logloss_real_forward": ev.get("logloss_real_forward"),
        "n_min": ev.get("n_min"),
        "brier_threshold": ev.get("brier_threshold"),
        "ece_threshold": ev.get("ece_threshold"),
        "calibration_status": ev.get("calibration_status", INSUFFICIENT_EVIDENCE),
        "predictive_claim_allowed": predictive,
        "predictive_claim_label": (
            STATUS_OK if predictive else PREDICTIVE_CLAIM_LOCKED
        ),
    }
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/outcomes
# --------------------------------------------------------------------------- #
N_OUTCOME_GATE = 200


def _count_pending_horizon(db_path: Any) -> int:
    """Snapshots without an outcome whose prediction horizon has NOT elapsed."""
    import sqlite3
    from datetime import datetime, timezone

    try:
        from scripts.decision_probability_snapshot import TABLE, ensure_schema
        from scripts.attach_due_outcomes import horizon_elapsed
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore
        from attach_due_outcomes import horizon_elapsed  # type: ignore

    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        rows = conn.execute(
            f"SELECT timestamp_utc, prediction_horizon_days, outcome_label FROM {TABLE}"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return 0
    finally:
        conn.close()

    pending = 0
    for r in rows:
        if r["outcome_label"] is not None:
            continue
        if not horizon_elapsed(
            decision_ts=r["timestamp_utc"],
            horizon_days=r["prediction_horizon_days"],
            now_utc=now,
        ):
            pending += 1
    return pending


def _count_forward_eligibility(db_path: Any) -> dict[str, Any]:
    """Tally forward-outcome eligibility across snapshots (read-only).

    Returns ``n_forward_outcome_eligible`` / ``n_forward_ineligible`` /
    ``forward_unavailable_reasons`` / ``n_due_forward`` (eligible AND horizon
    elapsed AND not yet labelled).  Tolerates a pre-migration DB by treating a
    missing ``forward_outcome_eligible`` column as zero eligible.
    """
    import sqlite3
    from datetime import datetime, timezone

    try:
        from scripts.decision_probability_snapshot import TABLE, ensure_schema
        from scripts.attach_due_outcomes import horizon_elapsed
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore
        from attach_due_outcomes import horizon_elapsed  # type: ignore

    out = {
        "n_forward_outcome_eligible": 0,
        "n_forward_ineligible": 0,
        "forward_unavailable_reasons": {},
        "n_due_forward": 0,
        "entry_price_present_count": 0,
    }
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
        if "forward_outcome_eligible" not in cols:
            return out
        rows = conn.execute(
            f"SELECT forward_outcome_eligible, forward_outcome_unavailable_reason,"
            f" entry_price, timestamp_utc, prediction_horizon_days, outcome_label"
            f" FROM {TABLE}"
        ).fetchall()
    except Exception:  # noqa: BLE001 - never crash the route
        return out
    finally:
        conn.close()

    reasons: dict[str, int] = {}
    for r in rows:
        if r["entry_price"] is not None:
            out["entry_price_present_count"] += 1
        if int(r["forward_outcome_eligible"] or 0) == 1:
            out["n_forward_outcome_eligible"] += 1
            if r["outcome_label"] is None and horizon_elapsed(
                decision_ts=r["timestamp_utc"],
                horizon_days=r["prediction_horizon_days"],
                now_utc=now,
            ):
                out["n_due_forward"] += 1
        else:
            out["n_forward_ineligible"] += 1
            key = r["forward_outcome_unavailable_reason"] or "UNSPECIFIED"
            reasons[key] = reasons.get(key, 0) + 1
    out["forward_unavailable_reasons"] = reasons
    return out


def build_forward_throughput(db_path: Any) -> dict[str, Any]:
    """Forward-eligible throughput visibility (read-only, advisory-only).

    Surfaces the before/after eligibility picture for the operator card.  The
    ``*_after`` figures + top-missing lists are computed live from the scored
    decision-candidate universe; the ``*_before`` baseline is read from the
    optional persisted artifact ``forward_throughput_baseline.json`` when present
    (written by the sprint run / refresh), else mirrored to the live value so the
    delta is honestly 0 rather than invented.
    """
    base = {
        "forward_eligible_before": 0,
        "forward_eligible_after": 0,
        "eligibility_rate_before": 0.0,
        "eligibility_rate_after": 0.0,
        "missing_ticker_before": 0,
        "missing_ticker_after": 0,
        "missing_entry_price_before": 0,
        "missing_entry_price_after": 0,
        "missing_probability_before": 0,
        "missing_probability_after": 0,
        "top_missing_entry_price_tickers": [],
        "top_missing_ticker_sources": [],
        "predictive_claim_allowed": False,
        "calibration_status": INSUFFICIENT_EVIDENCE,
    }
    try:
        try:
            from scripts.forward_eligibility_diagnostics import forward_eligibility_diagnostics
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from forward_eligibility_diagnostics import forward_eligibility_diagnostics  # type: ignore
        diag = forward_eligibility_diagnostics(db_path=db_path)
    except Exception:  # noqa: BLE001 - never crash the route
        return base

    # ``*_after`` reflects the production-persisted forward-eligible snapshots
    # (comparable to the probe baseline).  The scored-universe diagnostic supplies
    # the per-reason after-counts and the top-missing lists (its rate is a
    # *coverage* metric over scored candidates, surfaced separately and labelled).
    forward = _count_forward_eligibility(db_path)
    eligible_after = int(forward.get("n_forward_outcome_eligible", 0))
    ineligible_after = int(forward.get("n_forward_ineligible", 0))
    snap_total = eligible_after + ineligible_after
    reasons_after = dict(forward.get("forward_unavailable_reasons", {}))
    base.update({
        "forward_eligible_after": eligible_after,
        "eligibility_rate_after": round(eligible_after / max(1, snap_total), 6),
        "missing_ticker_after": int(reasons_after.get("MISSING_TICKER", 0)),
        "missing_entry_price_after": int(reasons_after.get("MISSING_ENTRY_PRICE", 0)),
        "missing_probability_after": int(reasons_after.get("MISSING_PROBABILITY", 0)),
        "top_missing_entry_price_tickers": diag.get("top_missing_entry_price_tickers", []),
        "top_missing_ticker_sources": diag.get("top_missing_ticker_sources", []),
        # Coverage over the scored decision-candidate universe (eligible / scored).
        "scored_candidate_coverage": float(diag.get("eligibility_rate", 0.0)),
        "scored_candidates_total": int(diag.get("total_decisions", 0)),
        "scored_candidates_eligible": int(diag.get("forward_eligible", 0)),
    })

    artifact = _load_json(_release_dir() / "forward_throughput_baseline.json")
    if isinstance(artifact, dict):
        for k in (
            "forward_eligible_before", "eligibility_rate_before",
            "missing_ticker_before", "missing_entry_price_before",
            "missing_probability_before",
        ):
            if k in artifact:
                base[k] = artifact[k]
    return base


def build_outcomes_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Honest forward-outcome corpus status (read-only).

    Surfaces the real-forward (p, y) corpus that closes the calibration loop:
    how many pairs exist, how many are still pending their horizon, how many were
    excluded (and why), the Brier/ECE/LogLoss on the real-forward corpus, and how
    many more pairs are needed to reach the N=200 gate.  ``predictive_claim_allowed``
    is surfaced verbatim and stays ``False`` until N>=200 with Brier<=0.25,
    ECE<=0.10.
    """
    safety = _safety_stamps()
    target = db_path if db_path is not None else _db_path()
    try:
        try:
            from scripts.real_calibration_evidence import build_calibration_evidence
            from scripts.outcome_labeling_flow import build_outcome_corpus_summary
            from scripts.decision_probability_snapshot import count_valid_p
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from real_calibration_evidence import build_calibration_evidence  # type: ignore
            from outcome_labeling_flow import build_outcome_corpus_summary  # type: ignore
            from decision_probability_snapshot import count_valid_p  # type: ignore

        ev = build_calibration_evidence(target)
        summary = build_outcome_corpus_summary(target)
        n_valid_p = int(count_valid_p(target))
        n_pending = _count_pending_horizon(target)
        forward = _count_forward_eligibility(target)
    except Exception as exc:  # noqa: BLE001 - never crash the route
        payload = {
            "status": STATUS_DEGRADED,
            "reason": f"{type(exc).__name__}",
            "n_valid_p": 0,
            "n_real_forward_pairs": 0,
            "n_forward_outcome_eligible": 0,
            "n_forward_ineligible": 0,
            "forward_unavailable_reasons": {},
            "n_due_forward": 0,
            "n_pending_horizon": 0,
            "n_excluded": 0,
            "exclusion_reasons": {},
            "brier_real_forward": None,
            "ece_real_forward": None,
            "logloss_real_forward": None,
            "calibration_status": INSUFFICIENT_EVIDENCE,
            "predictive_claim_allowed": False,
            "predictive_claim_label": PREDICTIVE_CLAIM_LOCKED,
            "needed_for_gate": N_OUTCOME_GATE,
            "n_needed_to_200": N_OUTCOME_GATE,
            "n_outcome_gate": N_OUTCOME_GATE,
            "generated_at_utc": None,
        }
        payload.update(safety)
        return payload

    n_real_forward = int(ev.get("n_real_forward", 0))
    predictive = bool(ev.get("predictive_claim_allowed"))
    payload = {
        "status": STATUS_OK,
        "n_valid_p": n_valid_p,
        "n_real_forward_pairs": n_real_forward,
        "n_historical_proxy_pairs": int(ev.get("n_historical_proxy", 0)),
        # Forward-snapshot-contract surface (this sprint): how many live
        # snapshots are structurally outcome-eligible, how many are due, and why
        # the rest are ineligible.
        "n_forward_outcome_eligible": int(forward["n_forward_outcome_eligible"]),
        "n_forward_ineligible": int(forward["n_forward_ineligible"]),
        "forward_unavailable_reasons": dict(forward["forward_unavailable_reasons"]),
        "n_due_forward": int(forward["n_due_forward"]),
        "entry_price_present_count": int(forward["entry_price_present_count"]),
        "n_pending_horizon": int(n_pending),
        "n_excluded": int(summary.get("n_excluded", 0)),
        "exclusion_reasons": dict(summary.get("exclusion_reasons") or {}),
        "brier_real_forward": ev.get("brier_real_forward"),
        "ece_real_forward": ev.get("ece_real_forward"),
        "logloss_real_forward": ev.get("logloss_real_forward"),
        "n_min": ev.get("n_min", N_OUTCOME_GATE),
        "brier_threshold": ev.get("brier_threshold"),
        "ece_threshold": ev.get("ece_threshold"),
        "calibration_status": ev.get("calibration_status", INSUFFICIENT_EVIDENCE),
        "predictive_claim_allowed": predictive,
        "predictive_claim_label": (
            STATUS_OK if predictive else PREDICTIVE_CLAIM_LOCKED
        ),
        "needed_for_gate": max(0, N_OUTCOME_GATE - n_real_forward),
        "n_needed_to_200": max(0, N_OUTCOME_GATE - n_real_forward),
        "n_outcome_gate": N_OUTCOME_GATE,
        "generated_at_utc": ev.get("generated_at_utc"),
        "edge_claimed": False,
        "real_money_ready": False,
    }
    # Forward-eligible throughput visibility (this sprint).
    try:
        payload["forward_throughput"] = build_forward_throughput(target)
    except Exception:  # noqa: BLE001 - never crash the route
        payload["forward_throughput"] = {}
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/scoring
# --------------------------------------------------------------------------- #
def build_scoring_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Real-row scoring coverage + valid-probability count (read-only).

    Reuses the Phase 4 read-only aggregator
    (``scoring_coverage_summary``) and the decision-snapshot
    ``count_valid_p`` — no scoring math is duplicated here and nothing is
    mutated.  ``predictive_claim_allowed`` is surfaced verbatim from the
    real-forward calibration gate and stays ``False`` until N>=200 with
    Brier<=0.25 and ECE<=0.10.

    ``mode`` is:
      * ``EMPTY``    — no real canonical rows have been scored yet;
      * ``DEGRADED`` — the scoring side table / snapshot store is unreadable;
      * ``LIVE``     — real scored rows exist.
    """
    safety = _safety_stamps()
    target = db_path if db_path is not None else _db_path()
    try:
        try:
            from scripts.score_real_signal_events import scoring_coverage_summary
            from scripts.decision_probability_snapshot import count_valid_p
            from scripts.real_signal_score_vector import MODEL_VERSION
            from scripts.real_calibration_evidence import build_calibration_evidence
        except ModuleNotFoundError:  # pragma: no cover - script-style env
            from score_real_signal_events import scoring_coverage_summary  # type: ignore
            from decision_probability_snapshot import count_valid_p  # type: ignore
            from real_signal_score_vector import MODEL_VERSION  # type: ignore
            from real_calibration_evidence import build_calibration_evidence  # type: ignore

        coverage = scoring_coverage_summary(target)
        n_valid_p = int(count_valid_p(target))
        try:
            cal = build_calibration_evidence(target)
            calibration_status = cal.get("calibration_status", INSUFFICIENT_EVIDENCE)
            predictive = bool(cal.get("predictive_claim_allowed"))
        except Exception:  # noqa: BLE001 - calibration is best-effort here
            calibration_status = INSUFFICIENT_EVIDENCE
            predictive = False
    except Exception as exc:  # noqa: BLE001 - never crash the route
        payload = {
            "status": STATUS_DEGRADED,
            "mode": "DEGRADED",
            "reason": f"{type(exc).__name__}",
            "n_real_canonical_rows": 0,
            "n_scored_real_rows": 0,
            "scoring_coverage": 0.0,
            "n_complete_score_vectors": 0,
            "score_quality_coverage": 0.0,
            "sources_scored": [],
            "score_unavailable_reasons": {},
            "scoring_version": "real-row-score-v1",
            "model_version": "advisory-logistic-v1",
            "n_valid_p": 0,
            "calibration_status": INSUFFICIENT_EVIDENCE,
            "predictive_claim_allowed": False,
            "predictive_claim_label": PREDICTIVE_CLAIM_LOCKED,
            "edge_claimed": False,
            "real_money_ready": False,
        }
        payload.update(safety)
        return payload

    n_real = int(coverage["n_real_canonical_rows"])
    n_complete = int(coverage["n_complete_score_vectors"])

    # Roll-up decision-time label so the cockpit can warn on incomplete vectors:
    # real canonical rows that exist but are NOT a CompleteScore vector.
    reasons = dict(coverage.get("score_unavailable_reasons") or {})
    n_incomplete = max(0, n_real - n_complete)
    if n_incomplete > 0:
        reasons.setdefault("SCORE_VECTOR_INCOMPLETE", n_incomplete)

    mode = "LIVE" if (n_real > 0 or n_valid_p > 0) else "EMPTY"
    payload = {
        "status": STATUS_OK,
        "mode": mode,
        "n_real_canonical_rows": n_real,
        "n_scored_real_rows": int(coverage["n_scored_real_rows"]),
        "scoring_coverage": float(coverage["scoring_coverage"]),
        "n_complete_score_vectors": n_complete,
        "score_quality_coverage": float(coverage["score_quality_coverage"]),
        "sources_scored": list(coverage.get("sources_scored") or []),
        "score_unavailable_reasons": reasons,
        "scoring_version": coverage.get("scoring_version", "real-row-score-v1"),
        "model_version": MODEL_VERSION,
        "n_valid_p": n_valid_p,
        "calibration_status": calibration_status,
        "predictive_claim_allowed": predictive,
        "predictive_claim_label": (
            STATUS_OK if predictive else PREDICTIVE_CLAIM_LOCKED
        ),
        "edge_claimed": False,
        "real_money_ready": False,
    }
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/bundle
# --------------------------------------------------------------------------- #
def build_bundle_payload(*, bundle_path: Path | None = None) -> dict[str, Any]:
    """Surface the persisted real-evidence bundle (read-only)."""
    safety = _safety_stamps()
    jpath = bundle_path or (_release_dir() / "real_evidence_bundle.json")
    mpath = _repo_root() / "docs" / "REAL_EVIDENCE_BUNDLE.md"
    bundle = _load_json(jpath)

    if bundle is None:
        payload = {
            "status": STATUS_DEGRADED,
            "artifact_present": False,
            "generated_at_utc": None,
            "repo_commit": None,
            "evidence_score": None,
            "real_money_ready": False,
            "edge_claimed": False,
            "bundle_json_path": str(jpath),
            "bundle_markdown_path": str(mpath) if mpath.exists() else None,
        }
        payload.update(safety)
        return payload

    s_evidence = bundle.get("s_evidence") or {}
    payload = {
        "status": STATUS_OK,
        "artifact_present": True,
        "generated_at_utc": bundle.get("generated_at_utc"),
        "repo_commit": bundle.get("repo_commit"),
        "evidence_score": s_evidence.get("score") if isinstance(s_evidence, dict) else None,
        "real_money_ready": bool(bundle.get("real_money_ready", False)),
        "edge_claimed": bool(bundle.get("edge_claimed", False)),
        "predictive_claim_allowed": bool(bundle.get("predictive_claim_allowed", False)),
        "bundle_json_path": str(jpath),
        "bundle_markdown_path": str(mpath) if mpath.exists() else None,
        "limitations": bundle.get("limitations") or [],
    }
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/live-decision-path
# --------------------------------------------------------------------------- #
def _latest_decision_snapshot(db_path: Any) -> dict[str, Any] | None:
    """Return the most recent decision_probability_snapshots row, or None."""
    import sqlite3

    try:
        from scripts.decision_probability_snapshot import TABLE, ensure_schema
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from decision_probability_snapshot import TABLE, ensure_schema  # type: ignore

    conn = sqlite3.connect(str(db_path))
    try:
        conn.row_factory = sqlite3.Row
        ensure_schema(conn)
        row = conn.execute(
            f"SELECT * FROM {TABLE} ORDER BY timestamp_utc DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


def build_live_decision_path_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Surface the most recent advisory decision snapshot (read-only).

    The advisory stamps are always re-asserted here — a decision can never be
    rendered without ``execution_gate = LOCKED``.
    """
    safety = _safety_stamps()
    target = db_path if db_path is not None else _db_path()
    snap = _latest_decision_snapshot(target)

    if snap is None:
        payload = {
            "status": STATUS_DEGRADED,
            "last_decision_id": None,
            "final_advisory_class": None,
            "p_base": None,
            "p_after_moltbook": None,
            "model_probability": None,
            "gate_result": None,
            "capacity_result": None,
            "source_truth_status": STATUS_UNKNOWN,
            "reason": "NO_DECISION_SNAPSHOTS",
        }
        payload.update(safety)
        return payload

    payload = {
        "status": STATUS_OK,
        "last_decision_id": snap.get("snapshot_id"),
        "signal_id": snap.get("signal_id"),
        "ticker": snap.get("ticker"),
        "country": snap.get("country"),
        # The snapshot stores the model_probability at decision time; p_base /
        # p_after_moltbook are not persisted on the snapshot row, so we surface
        # the model_probability and report the others as not-persisted (null),
        # never fabricated.
        "final_advisory_class": snap.get("signal_class"),
        "p_base": None,
        "p_after_moltbook": None,
        "model_probability": snap.get("model_probability"),
        "model_probability_reason": snap.get("model_probability_reason"),
        "prediction_horizon_days": snap.get("prediction_horizon_days"),
        "target_event_definition": snap.get("target_event_definition"),
        "timestamp_utc": snap.get("timestamp_utc"),
        "gate_result": {
            "advisory_status": snap.get("advisory_status") or "ADVISORY_ONLY",
            "execution_gate": snap.get("execution_gate") or "LOCKED",
        },
        "capacity_result": None,
        "source_truth_status": STATUS_UNKNOWN,
        "outcome_label": snap.get("outcome_label"),
    }
    payload.update(safety)
    return _strip_secrets(payload)


# --------------------------------------------------------------------------- #
# GET /evidence/capacity-risk
# --------------------------------------------------------------------------- #
def build_capacity_risk_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Capacity / correlation risk view (read-only).

    There is no persisted per-decision capacity snapshot, so this surface is
    honest about that: capacity that cannot be evaluated is ``CAPACITY_UNKNOWN``
    and treated as risk (``capacity_ok = False``).  Missing data is never green.
    """
    safety = _safety_stamps()
    payload = {
        "status": STATUS_UNKNOWN,
        "capacity_ok": False,
        "capacity_status": "CAPACITY_UNKNOWN",
        "correlation_status": "NOT_EVALUATED",
        "max_pairwise_correlation": None,
        "portfolio_variance_after": None,
        "country_exposure_after": None,
        "sector_exposure_after": None,
        "single_name_exposure_after": None,
        "block_reason": "no_persisted_capacity_context",
        "note": (
            "Capacity / correlation is evaluated live inside run_live_decision_path "
            "and is not persisted per-decision; missing context is reported as "
            "risk, never as safe."
        ),
    }
    payload.update(safety)
    return payload


# --------------------------------------------------------------------------- #
# GET /evidence/summary
# --------------------------------------------------------------------------- #
def build_summary_payload(*, db_path: Any = None) -> dict[str, Any]:
    """Compact aggregate of the evidence surface (read-only)."""
    safety = _safety_stamps()
    source_truth = build_source_truth_payload(db_path=db_path)
    calibration = build_calibration_payload(db_path=db_path)
    scoring = build_scoring_payload(db_path=db_path)
    outcomes = build_outcomes_payload(db_path=db_path)
    bundle = build_bundle_payload()
    decision = build_live_decision_path_payload(db_path=db_path)

    payload = {
        "status": STATUS_OK,
        "real_source_activation_count": source_truth.get("real_source_activation_count", 0),
        "fixture_source_activation_count": source_truth.get(
            "fixture_source_activation_count", 0
        ),
        "n_scored_real_rows": scoring.get("n_scored_real_rows", 0),
        "scoring_coverage": scoring.get("scoring_coverage", 0.0),
        "n_valid_p": calibration.get("n_valid_p", 0),
        "n_real_forward": calibration.get("n_real_forward", 0),
        "n_real_forward_pairs": outcomes.get("n_real_forward_pairs", 0),
        "n_pending_horizon": outcomes.get("n_pending_horizon", 0),
        "n_excluded_outcomes": outcomes.get("n_excluded", 0),
        "needed_for_gate": outcomes.get("needed_for_gate", N_OUTCOME_GATE),
        "calibration_status": calibration.get("calibration_status", INSUFFICIENT_EVIDENCE),
        "predictive_claim_allowed": bool(calibration.get("predictive_claim_allowed", False)),
        "evidence_score": bundle.get("evidence_score"),
        "real_money_ready": False,
        "edge_claimed": bool(bundle.get("edge_claimed", False)),
        "last_decision_id": decision.get("last_decision_id"),
        "bundle_present": bundle.get("artifact_present", False),
    }
    payload.update(safety)
    return payload


# --------------------------------------------------------------------------- #
# Route handlers — resolve builders via scripts.api_server at request time so
# test patches on those symbols apply (mirrors the rest of the API surface).
# --------------------------------------------------------------------------- #
def _resolve(name: str, default):
    import scripts.api_server as _srv

    return getattr(_srv, name, default)


def get_evidence_source_truth() -> dict[str, Any]:
    return _resolve("_build_evidence_source_truth_payload", build_source_truth_payload)()


def get_evidence_calibration() -> dict[str, Any]:
    return _resolve("_build_evidence_calibration_payload", build_calibration_payload)()


def get_evidence_scoring() -> dict[str, Any]:
    return _resolve("_build_evidence_scoring_payload", build_scoring_payload)()


def get_evidence_outcomes() -> dict[str, Any]:
    return _resolve("_build_evidence_outcomes_payload", build_outcomes_payload)()


def get_evidence_bundle() -> dict[str, Any]:
    return _resolve("_build_evidence_bundle_payload", build_bundle_payload)()


def get_evidence_live_decision_path() -> dict[str, Any]:
    return _resolve(
        "_build_evidence_live_decision_path_payload", build_live_decision_path_payload
    )()


def get_evidence_capacity_risk() -> dict[str, Any]:
    return _resolve("_build_evidence_capacity_risk_payload", build_capacity_risk_payload)()


def get_evidence_summary() -> dict[str, Any]:
    return _resolve("_build_evidence_summary_payload", build_summary_payload)()


def build_router():
    router = APIRouter()
    router.get("/evidence/source-truth")(get_evidence_source_truth)
    router.get("/evidence/calibration")(get_evidence_calibration)
    router.get("/evidence/scoring")(get_evidence_scoring)
    router.get("/evidence/outcomes")(get_evidence_outcomes)
    router.get("/evidence/bundle")(get_evidence_bundle)
    router.get("/evidence/live-decision-path")(get_evidence_live_decision_path)
    router.get("/evidence/capacity-risk")(get_evidence_capacity_risk)
    router.get("/evidence/summary")(get_evidence_summary)
    return router


__all__ = [
    "STATUS_OK",
    "STATUS_DEGRADED",
    "STATUS_UNKNOWN",
    "PREDICTIVE_CLAIM_LOCKED",
    "INSUFFICIENT_EVIDENCE",
    "build_source_truth_payload",
    "build_calibration_payload",
    "build_scoring_payload",
    "build_outcomes_payload",
    "build_bundle_payload",
    "build_live_decision_path_payload",
    "build_capacity_risk_payload",
    "build_summary_payload",
    "build_router",
]
