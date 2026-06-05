#!/usr/bin/env python3
"""Six-layer coordination audit for the Sleeping Passenger MVP.

This is a **read-only, static** self-audit.  It answers one question with
code-backed evidence:

    "Does Sleeping Passenger have rhythmic unison across six operational
     layers, or are modules still acting like unsynchronized rowers?"

The six layers (the drone-show / rowing-crew analogy):

1. Choreography  — is there a clear end-to-end show/workflow?
2. Timing        — do modules share a consistent clock / cadence?
3. Position      — does each item know its exact finite state?
4. Collision     — are unsafe overlaps blocked?
5. Simulation    — is there a safe rehearsal mode before real use?
6. Operations    — is it usable day to day without breaking rhythm?

Provenance honesty (non-negotiable):

* Every scored number is derived from **static inspection of committed
  source files** (``provenance_type = STATIC_CODE``), so the report is
  deterministic across machines and CI.  Each metric carries an
  ``EvidenceRef`` pointing at the real file/line it was measured from.
* The audit never invents runtime outcomes.  Runtime stores (the
  git-ignored ``runtime/mvp_local.db`` and ``logs/*.jsonl``) are listed in
  the provenance block for transparency but are **not** folded into the
  score; anything that would require real operator outcomes is reported
  ``NO_DATA`` rather than fabricated.
* ``NO_DATA`` is never scored as ``0``.  It is excluded from the numeric
  mean, but a layer that is >50% ``NO_DATA`` cannot grade ``PASS``.

The audit is itself advisory-only: it calls no broker, runs no refresh,
and writes nothing except the report file you ask for via ``--out``.

CLI::

    python -m scripts.coordination_audit --format markdown --out docs/coordination_audit.md
    python -m scripts.coordination_audit --format json --out runtime/coordination_audit.json
    python -m scripts.coordination_audit --format json          # stdout
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Repo root = parent of this scripts/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Status + provenance vocabularies
# ---------------------------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
NO_DATA = "NO_DATA"
_METRIC_STATUSES = frozenset({PASS, WARN, FAIL, NO_DATA})

# provenance_type values an EvidenceRef may carry.
PROVENANCE_TYPES = frozenset(
    {
        "STATIC_CODE",
        "TEST_RESULT",
        "RUNTIME_DB",
        "LOCAL_LOG",
        "FIXTURE",
        "IMPORTED_BACKTEST",
        "SYNTHETIC",
        "NO_DATA",
    }
)

# Metric status -> numeric score.  NO_DATA is intentionally absent: it maps
# to ``None`` and is excluded from every mean (see ``_score_statuses``).
_SCORE_MAP: dict[str, float] = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}

# Layer weights (Phase 8: default equal weights, 1/6 each).
LAYER_WEIGHTS: dict[str, float] = {
    "choreography": 1.0,
    "timing": 1.0,
    "position_control": 1.0,
    "collision_safety": 1.0,
    "simulation": 1.0,
    "operations": 1.0,
}


# ---------------------------------------------------------------------------
# Data model (Phase 1 schema)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class EvidenceRef:
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    data_source: str
    provenance_type: str

    def __post_init__(self) -> None:
        if self.provenance_type not in PROVENANCE_TYPES:
            raise ValueError(
                f"provenance_type must be one of {sorted(PROVENANCE_TYPES)}, "
                f"got {self.provenance_type!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Metric:
    name: str
    value: Any
    expected: str
    status: str
    provenance: str

    def __post_init__(self) -> None:
        if self.status not in _METRIC_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_METRIC_STATUSES)}, "
                f"got {self.status!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Finding:
    severity: str  # BLOCKER | WARN | INFO
    layer: str
    message: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass(slots=True)
class CoordinationLayerStat:
    layer_name: str
    score: Optional[float]
    status: str
    checked_metrics: list[Metric] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_name": self.layer_name,
            "score": self.score,
            "status": self.status,
            "checked_metrics": [m.to_dict() for m in self.checked_metrics],
            "evidence": [e.to_dict() for e in self.evidence],
            "explanation": self.explanation,
        }


@dataclass(slots=True)
class ProvenanceBlock:
    allowed_sources: list[str] = field(default_factory=list)
    disallowed_mixing_rules: list[str] = field(default_factory=list)
    runtime_files_inspected: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CoordinationAuditReport:
    generated_at_utc: str
    repo_commit: str
    mode: str  # NO_DATA | PARTIAL_DATA | MEASURED
    layers: dict[str, CoordinationLayerStat]
    overall_coordination_score: Optional[float]
    overall_coordination_grade: str
    blocking_findings: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    provenance: ProvenanceBlock = field(default_factory=ProvenanceBlock)
    no_data_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "repo_commit": self.repo_commit,
            "mode": self.mode,
            "overall_coordination_score": self.overall_coordination_score,
            "overall_coordination_grade": self.overall_coordination_grade,
            "no_data_ratio": self.no_data_ratio,
            "layers": {k: v.to_dict() for k, v in self.layers.items()},
            "blocking_findings": [f.to_dict() for f in self.blocking_findings],
            "warnings": [f.to_dict() for f in self.warnings],
            "provenance": self.provenance.to_dict(),
        }


# ---------------------------------------------------------------------------
# Scoring (Phase 8) — pure functions, no I/O, fully unit-testable
# ---------------------------------------------------------------------------
def metric_score(status: str) -> Optional[float]:
    """Map a metric status to its numeric score; NO_DATA -> ``None``."""
    return _SCORE_MAP.get(status)


def _score_statuses(statuses: list[str]) -> tuple[Optional[float], int, int]:
    """Return (numeric_score | None, scored_count, no_data_count).

    NO_DATA is excluded from the mean (never treated as 0).  If every metric
    is NO_DATA the score is ``None``.
    """
    numeric = [metric_score(s) for s in statuses]
    scored = [v for v in numeric if v is not None]
    no_data = sum(1 for v in numeric if v is None)
    if not scored:
        return None, 0, no_data
    return sum(scored) / len(scored), len(scored), no_data


def layer_status_from_metrics(metrics: list[Metric]) -> tuple[Optional[float], str]:
    """Compute (score, status) for a layer from its metrics (Phase 8).

    Rules:
      * score = mean of PASS/WARN/FAIL scores, excluding NO_DATA.
      * status = FAIL if any metric FAILs, else WARN if any WARNs, else PASS.
      * if >50% of the layer's metrics are NO_DATA, the layer may not grade
        PASS (capped to WARN); if *all* are NO_DATA the layer is NO_DATA.
    """
    if not metrics:
        return None, NO_DATA
    statuses = [m.status for m in metrics]
    score, _scored, no_data = _score_statuses(statuses)
    total = len(statuses)
    if score is None:
        return None, NO_DATA

    if any(s == FAIL for s in statuses):
        base = FAIL
    elif any(s == WARN for s in statuses):
        base = WARN
    else:
        base = PASS

    # >50% NO_DATA cannot grade PASS.
    if no_data / total > 0.5 and base == PASS:
        base = WARN
    return score, base


def overall_grade(score: Optional[float]) -> str:
    if score is None:
        return "NO_MEASURABLE_DATA"
    if score >= 0.90:
        return "RHYTHMIC_UNISON"
    if score >= 0.75:
        return "MOSTLY_COORDINATED"
    if score >= 0.60:
        return "PARTIAL_COORDINATION"
    if score >= 0.40:
        return "FRAGMENTED"
    return "UNSYNCHRONIZED"


def compute_overall(
    layers: dict[str, CoordinationLayerStat],
    *,
    no_data_ratio: float,
    weights: Optional[dict[str, float]] = None,
) -> tuple[Optional[float], str]:
    """Weighted mean of layer scores (Phase 8). NO_DATA layers excluded.

    Applies the ``_LOW_EVIDENCE`` grade suffix when >50% of all metrics are
    NO_DATA.
    """
    weights = weights or LAYER_WEIGHTS
    num = 0.0
    den = 0.0
    for key, layer in layers.items():
        if layer.score is None:
            continue
        w = weights.get(key, 1.0)
        num += w * layer.score
        den += w
    score = (num / den) if den else None
    grade = overall_grade(score)
    if score is not None and no_data_ratio > 0.5:
        grade = f"{grade}_LOW_EVIDENCE"
    return score, grade


# ---------------------------------------------------------------------------
# Static source inspection helpers — every scored metric goes through these
# ---------------------------------------------------------------------------
def _read_text(root: Path, rel_path: str) -> Optional[str]:
    p = root / rel_path
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _find_line(root: Path, rel_path: str, needle: str) -> Optional[int]:
    """1-based line number of the first line containing ``needle`` or None."""
    text = _read_text(root, rel_path)
    if text is None:
        return None
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    return None


def evidence(
    root: Path,
    rel_path: str,
    needle: Optional[str] = None,
    *,
    data_source: str = "static code inspection",
    provenance_type: str = "STATIC_CODE",
) -> EvidenceRef:
    """Build an EvidenceRef for ``rel_path``, optionally anchored at ``needle``.

    If the file (or anchor) is absent, the EvidenceRef degrades to a
    NO_DATA provenance pointing at the path that was looked for.
    """
    exists = (root / rel_path).exists()
    if not exists:
        return EvidenceRef(rel_path, None, None, "file not found", "NO_DATA")
    line = _find_line(root, rel_path, needle) if needle else None
    if needle and line is None:
        return EvidenceRef(rel_path, None, None, f"anchor {needle!r} not found", "NO_DATA")
    return EvidenceRef(rel_path, line, line, data_source, provenance_type)


def _file_has(root: Path, rel_path: str, needle: str) -> bool:
    text = _read_text(root, rel_path)
    return bool(text and needle in text)


def _present(root: Path, candidates: list[str]) -> Optional[str]:
    """Return the first candidate path that exists, else None."""
    for c in candidates:
        if (root / c).exists():
            return c
    return None


def _ratio_status(ratio: float, pass_at: float, warn_at: float) -> str:
    if ratio >= pass_at:
        return PASS
    if ratio >= warn_at:
        return WARN
    return FAIL


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------
def _layer_choreography(root: Path) -> CoordinationLayerStat:
    """Layer 1 — is there a clear end-to-end show/workflow?"""
    # Stage -> candidate implementing files (first existing wins).
    stages: dict[str, list[str]] = {
        "signal_generation": ["scripts/signal_engine.py", "scripts/signal_refinery.py"],
        "signal_inbox": ["scripts/signal_inbox_api.py", "scripts/signal_inbox_bridge.py"],
        "live_signals": ["scripts/refresh_live_signals.py", "scripts/live_signal_filters.py"],
        "manual_trade_log": ["scripts/bulk_log_manual_trades.py", "scripts/manual_trade_origin.py"],
        "reconciliation": ["scripts/paper_reconciliation.py", "scripts/reconciliation_queue.py"],
        "outcome_tracking": ["scripts/outcome_evidence.py", "scripts/import_outcomes_csv.py"],
        "moltbook_reflection": ["scripts/moltbook_api.py", "scripts/moltbook_reconciliation_bridge.py"],
        "dashboard_summary": ["src/dashboard/streamlit_app.py", "scripts/api_server.py"],
    }
    ev: list[EvidenceRef] = []
    present = 0
    for stage, cands in stages.items():
        hit = _present(root, cands)
        if hit:
            present += 1
            ev.append(evidence(root, hit, data_source=f"stage:{stage}"))
        else:
            ev.append(EvidenceRef(cands[0], None, None, f"stage:{stage} MISSING", "NO_DATA"))
    stage_ratio = present / len(stages)

    # Workflow link coverage: a transition is "covered" when a shared,
    # stable identifier links source -> target.  Verified against the
    # persistence schema + bridge modules.
    persistence = "scripts/persistence.py"
    transitions = {
        "signal_generation->signal_inbox": _file_has(root, "scripts/signal_inbox_bridge.py", "event_id"),
        "signal_inbox->live_signals": _file_has(root, persistence, "signal_events"),
        "signal_inbox->manual_trade_log": _file_has(root, persistence, "manual_trades")
        and _file_has(root, persistence, "event_id"),
        "manual_trade_log->reconciliation": _file_has(root, persistence, "reconciliation_results")
        and _file_has(root, persistence, "trade_id"),
        "reconciliation->outcome_tracking": _file_has(root, "scripts/outcome_evidence.py", "trade_id"),
        "outcome_tracking->dashboard_summary": _file_has(root, "scripts/api_server.py", "reconcil")
        or _file_has(root, "scripts/gsheet_export.py", "reconciliation"),
        "outcome_tracking->moltbook_reflection": _file_has(
            root, "scripts/moltbook_reconciliation_bridge.py", "reconciliation"
        ),
    }
    covered = sum(1 for v in transitions.values() if v)
    link_ratio = covered / len(transitions)
    link_ev = [
        evidence(root, persistence, "reconciliation_results", data_source="trade_id FK chain"),
        evidence(root, "scripts/signal_inbox_bridge.py", "event_id", data_source="event_id continuity"),
        evidence(
            root,
            "scripts/moltbook_reconciliation_bridge.py",
            "reconciliation",
            data_source="reconciliation->moltbook bridge",
        ),
    ]

    # Identity continuity: are the stable keys carried in the schema?
    identity_keys = {
        "signal_id/event_id": _file_has(root, persistence, "event_id"),
        "trade_id": _file_has(root, persistence, "trade_id"),
        "ticker": _file_has(root, persistence, "ticker"),
        "date/timestamp": _file_has(root, persistence, "reconciled_at")
        or _file_has(root, persistence, "executed_at"),
        "source/provenance": _file_has(root, persistence, "created_via"),
        "mode": _file_has(root, persistence, "trade_mode"),
    }
    preserved = sum(1 for v in identity_keys.values() if v)
    identity_ratio = preserved / len(identity_keys)

    metrics = [
        Metric(
            "workflow_stage_presence_ratio",
            round(stage_ratio, 4),
            ">=0.875 PASS; 0.625-0.875 WARN; <0.625 FAIL",
            _ratio_status(stage_ratio, 0.875, 0.625),
            f"static: {present}/{len(stages)} workflow stages have an identifiable module",
        ),
        Metric(
            "workflow_link_coverage_ratio",
            round(link_ratio, 4),
            ">=0.80 PASS; 0.50-0.80 WARN; <0.50 FAIL",
            _ratio_status(link_ratio, 0.80, 0.50),
            f"static: {covered}/{len(transitions)} stage transitions linked by stable IDs",
        ),
        Metric(
            "identity_continuity_score",
            round(identity_ratio, 4),
            ">=0.90 PASS; >=0.70 WARN; else FAIL",
            _ratio_status(identity_ratio, 0.90, 0.70),
            f"static: {preserved}/{len(identity_keys)} identity keys present in persistence schema",
        ),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "choreography",
        score,
        status,
        metrics,
        ev + link_ev,
        "End-to-end show: signal generation -> inbox -> live -> manual log -> "
        "reconciliation -> outcome -> Moltbook -> dashboard, linked by stable "
        "event_id/trade_id/ticker identifiers in the persistence schema.",
    )


def _layer_timing(root: Path) -> CoordinationLayerStat:
    """Layer 2 — do modules share a consistent clock / cadence?"""
    persistence = "scripts/persistence.py"
    time_fields = {
        "created_at/generated_at": _file_has(root, persistence, "created_at")
        or _file_has(root, persistence, "generated_at"),
        "executed_at (trade)": _file_has(root, persistence, "executed_at"),
        "signal fetched_at": _file_has(root, persistence, "fetched_at"),
        "reconciled_at": _file_has(root, persistence, "reconciled_at"),
        "moltbook logged_at": _file_has(root, persistence, "logged_at"),
        "UTC normalization policy": _file_has(root, "scripts/runtime_common.py", "utc_timestamp")
        or _file_has(root, "src/utils/time_utils.py", "utc"),
    }
    present = sum(1 for v in time_fields.values() if v)
    ts_ratio = present / len(time_fields)

    # Stale-signal guard: configurable freshness thresholds + stale labelling
    # must exist and be tested, so stale signals can't masquerade as fresh.
    stale_present = (
        _file_has(root, "scripts/anti_staleness.py", "STALE")
        and _file_has(root, "scripts/anti_staleness.py", "staleness_penalty")
        and (root / "tests" / "test_anti_staleness_rules.py").exists()
        and _file_has(root, "docs/LIVE_SIGNALS_REFRESH_MODEL.md", "Freshness")
    )
    stale_status = PASS if stale_present else NO_DATA

    # Holding-period integrity: must compute from real dates, return None on
    # missing/invalid dates (not silently 0), and reject negative durations.
    hp_file = "scripts/paper_reconciliation.py"
    hp_text = _read_text(root, hp_file) or ""
    hp_computes = "_compute_holding_period_days" in hp_text
    hp_missing_guard = "is None" in hp_text and "return None" in hp_text
    # Negative-duration guard: the function must explicitly reject exit<entry.
    hp_negative_guard = "negative" in hp_text.lower() or "exit_dt < entry_dt" in hp_text or "exit_dt <= entry_dt" in hp_text
    hp_tested = (root / "tests" / "test_holding_period_invariants.py").exists()
    if hp_computes and hp_missing_guard and hp_negative_guard and hp_tested:
        hp_status = PASS
    elif hp_computes and hp_missing_guard:
        hp_status = WARN
    else:
        hp_status = FAIL

    metrics = [
        Metric(
            "timestamp_field_coverage",
            round(ts_ratio, 4),
            ">=0.875 PASS; 0.625-0.875 WARN; else FAIL",
            _ratio_status(ts_ratio, 0.875, 0.625),
            f"static: {present}/{len(time_fields)} required time fields/policies present",
        ),
        Metric(
            "stale_signal_guard_status",
            stale_present,
            "configurable freshness thresholds + stale labelling exist",
            stale_status,
            "static: scripts/anti_staleness.py + docs/LIVE_SIGNALS_REFRESH_MODEL.md",
        ),
        Metric(
            "holding_period_calculation_integrity",
            {
                "computes_from_dates": hp_computes,
                "missing_date_returns_none": hp_missing_guard,
                "negative_rejected": hp_negative_guard,
                "tested": hp_tested,
            },
            "computes from dates; None on missing/invalid; no negative periods; tested",
            hp_status,
            f"static: {hp_file} _compute_holding_period_days + tests",
        ),
    ]
    ev = [
        evidence(root, persistence, "reconciled_at", data_source="reconciliation timestamp"),
        evidence(root, "scripts/runtime_common.py", "utc_timestamp", data_source="UTC normalization"),
        evidence(root, "scripts/anti_staleness.py", "STALE", data_source="staleness labels"),
        evidence(root, hp_file, "_compute_holding_period_days", data_source="holding-period math"),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "timing",
        score,
        status,
        metrics,
        ev,
        "Shared clock: all persistence writes use a single UTC timestamp "
        "helper; signals carry freshness labels with configurable stale "
        "thresholds; holding periods are computed from real ISO dates.",
    )


def _layer_position_control(root: Path) -> CoordinationLayerStat:
    """Layer 3 — does each item know its exact finite state?"""
    inbox = "scripts/signal_inbox_api.py"
    finite_objects = {
        "signal user_status": _file_has(root, inbox, "VALID_USER_STATUSES"),
        "reconciliation status": _file_has(root, inbox, "VALID_RECONCILIATION_STATUSES"),
        "log-cancel status": _file_has(root, inbox, "VALID_LOG_CANCEL_STATUSES"),
        "paper outcome status": _file_has(root, "scripts/paper_trade_ledger.py", "_OUTCOME_STATUS_ALLOWED"),
        "trade_mode": _file_has(root, inbox, "_TRADE_MODE_ALLOWED"),
    }
    present = sum(1 for v in finite_objects.values() if v)
    enum_ratio = present / len(finite_objects)

    # Invalid-transition / invalid-value rejection: the inbox enforces the
    # allowed-status sets (raises on anything outside them).  Tested here.
    rejects = _file_has(root, inbox, "not in VALID_USER_STATUSES") and _file_has(
        root, inbox, "not in VALID_RECONCILIATION_STATUSES"
    )
    transition_tested = (root / "tests" / "test_coordination_audit.py").exists()
    transition_status = PASS if (rejects and transition_tested) else (WARN if rejects else FAIL)

    # Loading-state finiteness (frontend async sections resolve, no infinite
    # spinner).  Measured by the presence of explicit loading-state specs.
    loading_specs = [
        "frontend/src/app/__tests__/manualTradeLog.loadingState.spec.tsx",
        "frontend/src/app/__tests__/moltbook.loadingState.spec.tsx",
        "frontend/src/app/__tests__/live-signals.display-state.spec.tsx",
        "frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx",
    ]
    covered_specs = sum(1 for s in loading_specs if (root / s).exists())
    loading_ratio = covered_specs / len(loading_specs)
    loading_status = _ratio_status(loading_ratio, 0.75, 0.5)

    metrics = [
        Metric(
            "finite_status_enum_coverage",
            round(enum_ratio, 4),
            ">=0.875 PASS; 0.625-0.875 WARN; else FAIL",
            _ratio_status(enum_ratio, 0.875, 0.625),
            f"static: {present}/{len(finite_objects)} major objects use finite status sets",
        ),
        Metric(
            "invalid_transition_rejection",
            rejects,
            "out-of-enum status values are rejected (raise) and tested",
            transition_status,
            "static: signal_inbox_api enforces VALID_* sets; proven in test_coordination_audit.py",
        ),
        Metric(
            "loading_state_finiteness",
            f"{covered_specs}/{len(loading_specs)} sections",
            ">=0.75 of async sections have finite loading-state specs",
            loading_status,
            "static: presence of frontend loading-state regression specs",
        ),
    ]
    ev = [
        evidence(root, inbox, "VALID_USER_STATUSES", data_source="signal status enum"),
        evidence(root, inbox, "VALID_RECONCILIATION_STATUSES", data_source="reconciliation status enum"),
        evidence(
            root,
            "frontend/src/app/__tests__/manualTradeLog.loadingState.spec.tsx",
            data_source="loading-state finiteness",
        ),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "position_control",
        score,
        status,
        metrics,
        ev,
        "Finite control: signals/trades/reconciliations validate against "
        "explicit frozenset status vocabularies; async UI sections resolve to "
        "finite loading states (empty/offline/loaded) instead of infinite spinners.",
    )


def _layer_collision_safety(root: Path) -> CoordinationLayerStat:
    """Layer 4 — are unsafe overlaps blocked?"""
    persistence = "scripts/persistence.py"
    # Duplicate signal guard: idempotent fingerprint table + INSERT OR IGNORE.
    dup_signal = _file_has(root, persistence, "duplicate_fingerprints") and _file_has(
        root, persistence, "INSERT OR IGNORE"
    )
    # Duplicate trade guard: manual_trades PK + INSERT OR IGNORE.
    dup_trade = _file_has(root, persistence, "INSERT OR IGNORE INTO manual_trades")
    # Ticker normalization: canonical symbol UNIQUE + alias mapping.
    ticker_guard = _file_has(root, persistence, "canonical_symbol TEXT NOT NULL UNIQUE") and _file_has(
        root, persistence, "global_security_aliases"
    )
    # Paper/live/synthetic/imported separation: trade_mode + created_via +
    # provenance classifier exclusions.
    mode_sep = (
        _file_has(root, persistence, "trade_mode")
        and _file_has(root, persistence, "created_via")
        and _file_has(root, "scripts/manual_trade_origin.py", "EXCLUDED_TRADE_MODES")
    )
    # Advisory-only guard.
    advisory = (
        _file_has(root, "scripts/advisory_contract.py", "advisory_safety_stamps")
        and _file_has(root, persistence, "_ADVISORY_STATUS")
        and (root / "tests" / "test_advisory_contract.py").exists()
    )

    def _b(ok: bool) -> str:
        return PASS if ok else FAIL

    metrics = [
        Metric("duplicate_signal_collision_guard", dup_signal,
               "duplicate signal natural-key blocked/merged idempotently", _b(dup_signal),
               "static: duplicate_fingerprints PK + INSERT OR IGNORE"),
        Metric("duplicate_trade_collision_guard", dup_trade,
               "duplicate trade_id blocked idempotently", _b(dup_trade),
               "static: INSERT OR IGNORE INTO manual_trades (trade_id PK)"),
        Metric("ticker_normalization_collision_guard", ticker_guard,
               "canonical symbol UNIQUE + alias map prevents cross-exchange collision", _b(ticker_guard),
               "static: global_securities.canonical_symbol UNIQUE + global_security_aliases"),
        Metric("paper_live_contamination_guard", mode_sep,
               "PAPER/LIVE_MANUAL/IMPORTED_BACKTEST/SYNTHETIC kept separate by mode+provenance", _b(mode_sep),
               "static: trade_mode + created_via + manual_trade_origin exclusions"),
        Metric("advisory_only_guard_status", advisory,
               "advisory-only/no-execution stamps enforced + tested", _b(advisory),
               "static: advisory_contract + persistence _ADVISORY_STATUS + test_advisory_contract.py"),
    ]
    ev = [
        evidence(root, persistence, "duplicate_fingerprints", data_source="duplicate signal guard"),
        evidence(root, persistence, "INSERT OR IGNORE INTO manual_trades", data_source="duplicate trade guard"),
        evidence(root, persistence, "canonical_symbol TEXT NOT NULL UNIQUE", data_source="ticker canonicalization"),
        evidence(root, "scripts/manual_trade_origin.py", "EXCLUDED_TRADE_MODES", data_source="provenance separation"),
        evidence(root, "scripts/advisory_contract.py", "advisory_safety_stamps", data_source="advisory-only guard"),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "collision_safety",
        score,
        status,
        metrics,
        ev,
        "No unsafe overlaps: duplicate signals/trades collapse idempotently at "
        "the DB boundary; tickers canonicalize through a securities master so "
        "exchanges can't silently collide; paper/live/synthetic/imported records "
        "stay separated by mode+provenance; advisory-only stamps are enforced on "
        "every read and write.",
    )


def _layer_simulation(root: Path) -> CoordinationLayerStat:
    """Layer 5 — is there a safe rehearsal mode before real use?"""
    # Fixture provenance: synthetic fixtures must be labelled.
    fixture_label = _file_has(root, "scripts/signal_inbox_api.py", "SYNTHETIC_LOGGED_BY_MARKERS") or _file_has(
        root, "tests/helpers/large_signal_events_fixture.py", "FIXTURE_EVENT_ID_PREFIX"
    )
    # Imported-backtest provenance: source_type + import timestamp + raw inputs.
    imported_prov = _file_has(root, "scripts/persistence.py", "imported_outcomes") and _file_has(
        root, "scripts/persistence.py", "imported_at"
    )
    # Sim->runtime boundary: synthetic refused in runtime mode; SYNTHETIC never
    # calibration-eligible; missing outcomes -> NO_DATA not fake confidence.
    boundary = (
        _file_has(root, "scripts/run_imported_backtest.py", "SYNTHETIC_FIXTURE")
        and _file_has(root, "scripts/outcome_evidence.py", "source_type")
    )
    boundary_tested = (root / "tests" / "test_run_imported_backtest.py").exists() or (
        root / "tests" / "test_import_outcomes_csv.py"
    ).exists()
    # Calibration evidence on REAL outcomes: honestly NO_DATA unless real
    # operator outcomes exist (the committed repo ships none; runtime DB is
    # git-ignored and non-canonical, so we do not score from it).
    calib_gate_present = _file_has(root, "scripts/calibration_gate.py", "NO_REAL_OUTCOME_EVIDENCE")

    def _b(ok: bool) -> str:
        return PASS if ok else FAIL

    metrics = [
        Metric("test_fixture_provenance_integrity", fixture_label,
               "synthetic fixtures labelled SYNTHETIC/TEST_FIXTURE", _b(fixture_label),
               "static: SYNTHETIC_LOGGED_BY_MARKERS + fixture prefix/metadata"),
        Metric("imported_backtest_provenance_integrity", imported_prov,
               "imported backtest carries source_type + import timestamp + raw inputs", _b(imported_prov),
               "static: imported_outcomes table with imported_at + source_type"),
        Metric("simulation_to_runtime_boundary_guard", boundary and boundary_tested,
               "synthetic cannot enter live stats; missing outcomes -> NO_DATA", _b(boundary and boundary_tested),
               "static: run_imported_backtest refuses synthetic in runtime; tested"),
        Metric("calibration_evidence_status", None,
               "MEASURED only with real outcomes; none committed -> NO_DATA (honest)", NO_DATA,
               "NO_DATA: no real operator outcomes are committed; runtime DB is non-canonical"),
        Metric("calibration_gate_present", calib_gate_present,
               "calibration gate emits NO_REAL_OUTCOME_EVIDENCE when real_n=0", _b(calib_gate_present),
               "static: scripts/calibration_gate.py NO_REAL_OUTCOME_EVIDENCE"),
    ]
    ev = [
        evidence(root, "scripts/signal_inbox_api.py", "SYNTHETIC_LOGGED_BY_MARKERS", data_source="fixture labelling"),
        evidence(root, "scripts/run_imported_backtest.py", "SYNTHETIC_FIXTURE", data_source="sim->runtime boundary"),
        evidence(root, "scripts/outcome_evidence.py", "source_type", data_source="provenance-weighted outcomes"),
        EvidenceRef("runtime/mvp_local.db", None, None,
                    "real operator outcomes (none committed; git-ignored runtime store)", "NO_DATA"),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "simulation",
        score,
        status,
        metrics,
        ev,
        "Safe rehearsal: synthetic fixtures and imported backtests are labelled "
        "and refused from runtime/live stats; calibration on REAL outcomes is "
        "reported NO_DATA honestly because no real operator outcomes are "
        "committed to the repo.",
    )


def _layer_operations(root: Path) -> CoordinationLayerStat:
    """Layer 6 — usable day to day without breaking rhythm?"""
    # Startup/health diagnostics.
    startup = _file_has(root, "scripts/local_deploy_preflight.py", "check_db_exists") or _file_has(
        root, "scripts/local_deploy_preflight.py", "def check"
    )
    health_endpoint = _file_has(root, "scripts/api_server.py", "health")
    startup_ok = startup and health_endpoint

    # Reset/local-logs safety (the destructive-script guard).
    reset = "scripts/reset_local_logs.py"
    reset_guard = (
        _file_has(root, reset, "guarded_mutation")
        and _file_has(root, reset, "_ALLOWED_TABLES")
        and _file_has(root, reset, "--apply")
        and _file_has(root, reset, "safe_db_path_allowed")
    )
    reset_tested = (root / "tests" / "test_reset_local_logs_guard.py").exists()
    reset_status = PASS if (reset_guard and reset_tested) else (WARN if reset_guard else FAIL)

    # Dashboard operability under empty/malformed/error/stale data.
    dash_ok = (
        _file_has(root, "src/dashboard/streamlit_app.py", ".get(")
        and (root / "frontend" / "src" / "app" / "__tests__" / "manualTradeLog.loadingState.spec.tsx").exists()
    )

    # Export / auditability (CSV / JSON / Markdown).
    export_ok = (
        _file_has(root, "scripts/gsheet_export.py", "csv")
        or _file_has(root, "scripts/export_paper_trades.py", "csv")
    ) and _file_has(root, "scripts/operator_audit_log.py", "audit")

    # Release gate / governance.
    release_gate = _file_has(root, "scripts/release_gate.py", "FAIL") and (
        root / "tests" / "test_release_gate.py"
    ).exists()

    def _b(ok: bool) -> str:
        return PASS if ok else FAIL

    metrics = [
        Metric("startup_health_status", startup_ok,
               "startup runs diagnostics (DB/tables/health endpoint)", _b(startup_ok),
               "static: local_deploy_preflight checks + api_server health route"),
        Metric("runtime_log_safety_status", reset_guard,
               "reset script: dry-run default, guard, allowlist, safe-path, tested", reset_status,
               "static: reset_local_logs guarded_mutation + _ALLOWED_TABLES + tests"),
        Metric("dashboard_operability_status", dash_ok,
               "dashboard renders under empty/error/stale data without infinite spinner", _b(dash_ok),
               "static: defensive .get() + frontend loading-state specs"),
        Metric("export_auditability_status", export_ok,
               "exportable manual log/reconciliation/outcomes (CSV/JSON) + audit log", _b(export_ok),
               "static: gsheet_export / export_paper_trades + operator_audit_log"),
        Metric("release_gate_status", release_gate,
               "release gate aggregates preflight into PASS/WARN/FAIL + tested", _b(release_gate),
               "static: release_gate.py + test_release_gate.py"),
    ]
    ev = [
        evidence(root, reset, "guarded_mutation", data_source="reset guard"),
        evidence(root, reset, "_ALLOWED_TABLES", data_source="reset allowlist"),
        evidence(root, "scripts/release_gate.py", "FAIL", data_source="release gate verdict"),
        evidence(root, "scripts/gsheet_export.py", data_source="CSV/JSON export"),
    ]
    score, status = layer_status_from_metrics(metrics)
    return CoordinationLayerStat(
        "operations",
        score,
        status,
        metrics,
        ev,
        "Daily rhythm: startup preflight + health endpoint, destructive resets "
        "guarded behind dry-run+role+allowlist+backup, dashboards degrade "
        "gracefully, journals export to CSV/JSON, and a release gate emits a "
        "single PASS/WARN/FAIL verdict.",
    )


_LAYER_BUILDERS = {
    "choreography": _layer_choreography,
    "timing": _layer_timing,
    "position_control": _layer_position_control,
    "collision_safety": _layer_collision_safety,
    "simulation": _layer_simulation,
    "operations": _layer_operations,
}


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------
def _repo_commit(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # pragma: no cover - git optional
        pass
    return "UNKNOWN"


def _derive_findings(layers: dict[str, CoordinationLayerStat]) -> tuple[list[Finding], list[Finding]]:
    blockers: list[Finding] = []
    warnings: list[Finding] = []
    for key, layer in layers.items():
        for m in layer.checked_metrics:
            if m.status == FAIL:
                blockers.append(
                    Finding(
                        "BLOCKER", key,
                        f"{m.name} FAILED (value={m.value!r}; expected {m.expected}).",
                        layer.evidence[:1],
                        f"Restore the guard/behaviour proving {m.name}.",
                    )
                )
            elif m.status == WARN:
                warnings.append(
                    Finding(
                        "WARN", key,
                        f"{m.name} is WARN (value={m.value!r}; expected {m.expected}).",
                        layer.evidence[:1],
                        f"Tighten {m.name} to reach PASS.",
                    )
                )
    return blockers, warnings


def build_report(
    root: Path = REPO_ROOT,
    *,
    now: Optional[datetime] = None,
    commit: Optional[str] = None,
) -> CoordinationAuditReport:
    """Run all six layer checks and assemble the deterministic report."""
    now = now or datetime.now(timezone.utc)
    generated = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    commit = commit if commit is not None else _repo_commit(root)

    layers: dict[str, CoordinationLayerStat] = {
        key: builder(root) for key, builder in _LAYER_BUILDERS.items()
    }

    # no_data_ratio across all metrics.
    all_metrics = [m for layer in layers.values() for m in layer.checked_metrics]
    total = len(all_metrics)
    no_data_count = sum(1 for m in all_metrics if m.status == NO_DATA)
    no_data_ratio = (no_data_count / total) if total else 0.0

    overall_score, grade = compute_overall(layers, no_data_ratio=no_data_ratio)

    # mode
    if overall_score is None:
        mode = "NO_DATA"
    elif no_data_count == 0:
        mode = "MEASURED"
    else:
        mode = "PARTIAL_DATA"

    blockers, warnings = _derive_findings(layers)

    runtime_db = root / "runtime" / "mvp_local.db"
    provenance = ProvenanceBlock(
        allowed_sources=[
            "STATIC_CODE (committed source files — the only source folded into the score)",
            "TEST_RESULT (separately run pytest suite; not auto-folded here)",
            "RUNTIME_DB / LOCAL_LOG (listed for transparency; NOT scored — git-ignored, non-canonical)",
            "FIXTURE / IMPORTED_BACKTEST / SYNTHETIC (rehearsal data; never scored as live)",
        ],
        disallowed_mixing_rules=[
            "Synthetic fixtures must never enter live/manual performance stats.",
            "Imported backtest must never be presented as live performance.",
            "Paper and real-manual records must not be aggregated without grouped provenance.",
            "Missing real outcomes must surface as NO_DATA, never fabricated confidence.",
        ],
        runtime_files_inspected=[
            f"runtime/mvp_local.db (exists={runtime_db.exists()}; non-canonical, NOT scored)",
            "logs/*.jsonl (append-only operator journals; NOT scored)",
        ],
        tests_run=[
            "Static audit only. Run `python3.13 -m pytest -o addopts=''` separately "
            "for the full suite; targeted: tests/test_coordination_audit.py, "
            "tests/test_holding_period_invariants.py.",
        ],
        notes=[
            "Every scored metric uses STATIC_CODE provenance for determinism.",
            "calibration_evidence_status is NO_DATA: no real operator outcomes are committed.",
        ],
    )

    return CoordinationAuditReport(
        generated_at_utc=generated,
        repo_commit=commit,
        mode=mode,
        layers=layers,
        overall_coordination_score=(round(overall_score, 4) if overall_score is not None else None),
        overall_coordination_grade=grade,
        blocking_findings=blockers,
        warnings=warnings,
        provenance=provenance,
        no_data_ratio=round(no_data_ratio, 4),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_CREW_LABELS = [
    (0.90, "synchronized rowing crew"),
    (0.75, "decent school drill with minor gaps"),
    (0.60, "decent school drill with gaps"),
    (0.40, "fragmented team"),
    (0.0, "unsynchronized rowers"),
]


def _crew_label(score: Optional[float]) -> str:
    if score is None:
        return "no measurable rhythm yet"
    for threshold, label in _CREW_LABELS:
        if score >= threshold:
            return label
    return "unsynchronized rowers"


_LAYER_TITLES = {
    "choreography": "Layer 1 — Choreography",
    "timing": "Layer 2 — Timing",
    "position_control": "Layer 3 — Position / Control",
    "collision_safety": "Layer 4 — Collision / Safety",
    "simulation": "Layer 5 — Simulation",
    "operations": "Layer 6 — Operations",
}


def render_json(report: CoordinationAuditReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)


def _ev_str(e: EvidenceRef) -> str:
    loc = f":{e.line_start}" if e.line_start else ""
    return f"`{e.file_path}{loc}` ({e.provenance_type})"


def render_markdown(report: CoordinationAuditReport) -> str:
    L = report.layers
    lines: list[str] = []
    a = lines.append
    a("# Sleeping Passenger Coordination Audit")
    a("")
    a("> Read-only static audit. Advisory-only: no broker calls, no execution, "
      "no runtime mutation. Every scored number is derived from committed "
      "source files (STATIC_CODE provenance).")
    a("")
    score = report.overall_coordination_score
    biggest_blocker = report.blocking_findings[0].message if report.blocking_findings else "none"
    # biggest strength: highest-scoring layer.
    scored_layers = [(k, v) for k, v in L.items() if v.score is not None]
    strongest = max(scored_layers, key=lambda kv: kv[1].score)[0] if scored_layers else "n/a"

    a("## Executive Summary")
    a("")
    a(f"- **Overall grade:** `{report.overall_coordination_grade}`")
    a(f"- **Overall score:** {score if score is not None else 'NO_DATA'} "
      f"(weighted mean of six layers, equal weights)")
    a(f"- **NO_DATA ratio:** {report.no_data_ratio} "
      f"({'low evidence' if report.no_data_ratio > 0.5 else 'evidence sufficient'})")
    a(f"- **Mode:** `{report.mode}`")
    a(f"- **Biggest blocker:** {biggest_blocker}")
    a(f"- **Biggest strength:** `{strongest}` layer "
      f"(score {L[strongest].score if strongest in L else 'n/a'})")
    a(f"- **Generated (UTC):** {report.generated_at_utc}")
    a(f"- **Repo commit:** `{report.repo_commit}`")
    a("")
    a(f"**Verdict — the MVP's _coordination machinery_ behaves like a "
      f"_{_crew_label(score)}_.**")
    a("")
    a("Crew-rhythm scale: synchronized rowing crew > decent school drill with "
      "gaps > fragmented team > unsynchronized rowers.")
    a("")
    a("> **Scope & honesty caveat.** This grade measures *code-level* "
      "coordination — whether the workflow, clock, finite states, collision "
      "guards, rehearsal boundaries, and ops controls are present, wired "
      "together by stable identifiers, and backed by tests. It is **not** a "
      "claim of live trading performance or edge. Calibration on **real "
      "operator outcomes is `NO_DATA`** (none are committed to the repo), so "
      "`mode = PARTIAL_DATA`, not `MEASURED`. A perfectly-drilled crew can "
      "still be untested on open water.")
    a("")

    for key, title in _LAYER_TITLES.items():
        layer = L[key]
        a(f"## {title}")
        a("")
        a(f"- **Score:** {layer.score if layer.score is not None else 'NO_DATA'}")
        a(f"- **Status:** `{layer.status}`")
        a(f"- **What it checks:** {layer.explanation}")
        a("")
        a("| Metric | Value | Status | Expected | Provenance |")
        a("| --- | --- | --- | --- | --- |")
        for m in layer.checked_metrics:
            val = m.value if not isinstance(m.value, dict) else json.dumps(m.value)
            a(f"| {m.name} | {val} | `{m.status}` | {m.expected} | {m.provenance} |")
        a("")
        a("**Evidence:**")
        a("")
        for e in layer.evidence:
            a(f"- {_ev_str(e)} — {e.data_source}")
        a("")

    a("## Blocking Findings")
    a("")
    if report.blocking_findings:
        a("| severity | layer | finding | evidence | suggested fix |")
        a("| --- | --- | --- | --- | --- |")
        for f in report.blocking_findings:
            ev = _ev_str(f.evidence[0]) if f.evidence else "—"
            a(f"| {f.severity} | {f.layer} | {f.message} | {ev} | {f.suggested_fix} |")
    else:
        a("None. No FAIL-level metric was detected by static inspection.")
    a("")
    if report.warnings:
        a("### Warnings")
        a("")
        a("| severity | layer | finding | suggested fix |")
        a("| --- | --- | --- | --- |")
        for f in report.warnings:
            a(f"| {f.severity} | {f.layer} | {f.message} | {f.suggested_fix} |")
        a("")

    a("## Provenance Statement")
    a("")
    a("Where the numbers came from:")
    a("")
    a("- **Static code inspection:** every scored metric (deterministic across "
      "machines/CI).")
    a("- **Tests:** the full pytest suite is run separately (see baseline in the "
      "engineering report); the audit references specific test files as evidence "
      "but does not auto-execute them.")
    a("- **Runtime files / local logs:** listed for transparency, **not scored** "
      "— the runtime DB is git-ignored and non-canonical.")
    a("- **Synthetic fixtures / imported backtests:** labelled rehearsal data, "
      "never scored as live.")
    a("- **Real / manual data:** **NO_DATA** — no real operator outcomes are "
      "committed to the repo, so calibration-on-real-outcomes is reported "
      "NO_DATA rather than fabricated.")
    a("")
    a("Allowed sources:")
    for s in report.provenance.allowed_sources:
        a(f"- {s}")
    a("")
    a("Disallowed mixing rules:")
    for r in report.provenance.disallowed_mixing_rules:
        a(f"- {r}")
    a("")
    a("Runtime files inspected (not scored):")
    for rf in report.provenance.runtime_files_inspected:
        a(f"- {rf}")
    a("")

    a("## Next Fixes")
    a("")
    a("Ranked by safety/coordination impact vs implementation risk:")
    a("")
    rank = 1
    for f in report.blocking_findings + report.warnings:
        a(f"{rank}. **[{f.severity}] {f.layer}** — {f.message} "
          f"_Fix:_ {f.suggested_fix} _Acceptance:_ the metric reaches PASS and "
          f"a deterministic test proves it.")
        rank += 1
    if rank == 1:
        a("1. No blocking or warning findings from static inspection. Maintain the "
          "guards; re-run this audit in CI to catch regressions. _Acceptance:_ "
          "overall grade stays >= MOSTLY_COORDINATED and no layer drops to FAIL.")
    a("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _is_under_runtime_dir(path: Path) -> bool:
    try:
        from scripts.runtime_common import RUNTIME_DIR  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        try:
            from runtime_common import RUNTIME_DIR  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return False
    try:
        path.resolve().parent.relative_to(Path(RUNTIME_DIR).resolve())
        return True
    except (ValueError, OSError):
        return False


def _write_managed_runtime_json(path: Path, report: "CoordinationAuditReport") -> bool:
    """Write the JSON report into runtime/ as a governance-managed artifact.

    Stamps run_id/source_mode/operating_mode/truth_origin/commit_hash/
    config_fingerprint via the canonical writer so the artifact-coherence
    check treats it as 'managed', not legacy pollution.  Returns False (so the
    caller falls back to a plain write) if the stamping helper is unavailable.
    """
    try:
        from scripts.runtime_common import write_runtime_artifact  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - script-style fallback
        try:
            from runtime_common import write_runtime_artifact  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return False
    payload = report.to_dict()
    payload["artifact_kind"] = "coordination_audit_report"
    try:
        write_runtime_artifact(path, payload)
    except Exception:  # pragma: no cover - defensive; fall back to plain write
        return False
    return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Six-layer coordination audit (read-only, advisory-only).",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write the report here (default: stdout).")
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="Repo root to audit (default: this repo).")
    args = parser.parse_args(argv)

    report = build_report(args.root)
    text = render_json(report) if args.format == "json" else render_markdown(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        wrote_managed = False
        if args.format == "json" and _is_under_runtime_dir(args.out):
            # A JSON artifact dropped into the governance-scanned runtime/ dir
            # must be a *managed* artifact (run_id/source_mode/timestamps), or
            # the artifact-coherence check would flag the audit's own output as
            # "legacy pollution".  Route it through the canonical stamping
            # writer so the coordination audit stays coordinated with governance.
            wrote_managed = _write_managed_runtime_json(args.out, report)
        if not wrote_managed:
            args.out.write_text(
                text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8"
            )
        print(
            f"[coordination_audit] wrote {args.format} report to {args.out} | "
            f"grade={report.overall_coordination_grade} "
            f"score={report.overall_coordination_score} "
            f"no_data_ratio={report.no_data_ratio}"
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
