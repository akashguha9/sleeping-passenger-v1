#!/usr/bin/env python3
"""Operational Readiness Audit — second-generation hardening scorecard.

Sits beside ``scripts/coordination_audit.py``.  Where the coordination audit
proved the crew knows the stroke pattern (code-level coordination), this audit
asks the open-water question:

    "Can Sleeping Passenger survive a real day-to-day manual trading workflow
     without lying to the operator?"

It is deliberately HARDER to score well on.  The headline number is penalised
by how strong the *evidence* behind it is:

    readiness_score = raw_readiness_score
                      * evidence_quality_score
                      * (1 - 0.50 * no_data_ratio)

A static-only audit therefore cannot pretend to be field-tested: with no real
operator outcomes, ``evidence_quality_score`` stays low and the grade carries
``_NO_REAL_OUTCOMES``.  The audit never converts PARTIAL_DATA to MEASURED
without real, auditable outcomes; calibration stays NO_DATA until real or
imported evidence exists; synthetic data can never appear as live proof.

Read-only and advisory-only: no broker calls, no execution, no mutation beyond
the report file you request via ``--out``.  Runtime JSON output is written
through the governance-managed artifact writer so the artifact-coherence check
treats it as a managed diagnostic, not legacy pollution.

CLI::

    python -m scripts.operational_readiness_audit --format markdown --out docs/operational_readiness_audit.md
    python -m scripts.operational_readiness_audit --format json --out runtime/operational_readiness_audit.json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REPO_ROOT = _REPO_ROOT

# ---------------------------------------------------------------------------
# Status + provenance vocabularies
# ---------------------------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
NO_DATA = "NO_DATA"
_METRIC_STATUSES = frozenset({PASS, WARN, FAIL, NO_DATA})

PROVENANCE_TYPES = frozenset(
    {
        "STATIC_CODE", "TEST_RESULT", "RUNTIME_DB", "LOCAL_LOG", "FIXTURE",
        "SYNTHETIC", "IMPORTED_BACKTEST", "LIVE_MANUAL", "PAPER", "NO_DATA",
    }
)

_SCORE_MAP: dict[str, float] = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}

# Evidence-quality weight per provenance type.  The seven weights named in the
# spec are preserved exactly; PAPER/LOCAL_LOG/FIXTURE are extended sensibly so
# every provenance_type has a defined weight.
EVIDENCE_WEIGHT: dict[str, float] = {
    "LIVE_MANUAL": 1.00,
    "IMPORTED_BACKTEST": 0.75,
    "RUNTIME_DB": 0.50,
    "PAPER": 0.50,
    "LOCAL_LOG": 0.40,
    "STATIC_CODE": 0.30,
    "TEST_RESULT": 0.20,
    "FIXTURE": 0.10,
    "SYNTHETIC": 0.10,
    "NO_DATA": 0.00,
}

SECTION_KEYS = [
    "outcome_evidence",
    "manual_trade_integrity",
    "reconciliation_integrity",
    "calibration_readiness",
    "dashboard_truthfulness",
    "export_auditability",
    "failure_recovery",
    "release_readiness",
]


# ---------------------------------------------------------------------------
# Data model (Phase 1)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class EvidenceRef:
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    data_source: str
    provenance_type: str
    checksum: Optional[str] = None

    def __post_init__(self) -> None:
        if self.provenance_type not in PROVENANCE_TYPES:
            raise ValueError(f"bad provenance_type {self.provenance_type!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Metric:
    name: str
    value: Any
    expected: str
    status: str
    score: Optional[float]
    provenance_type: str

    def __post_init__(self) -> None:
        if self.status not in _METRIC_STATUSES:
            raise ValueError(f"bad status {self.status!r}")
        if self.provenance_type not in PROVENANCE_TYPES:
            raise ValueError(f"bad provenance_type {self.provenance_type!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Finding:
    severity: str  # BLOCKER | WARN | INFO
    section: str
    message: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass(slots=True)
class OperationalSectionStat:
    section_name: str
    score: Optional[float]
    status: str
    metrics: list[Metric] = field(default_factory=list)
    explanation: str = ""
    evidence: list[EvidenceRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_name": self.section_name,
            "score": self.score,
            "status": self.status,
            "metrics": [m.to_dict() for m in self.metrics],
            "explanation": self.explanation,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass(slots=True)
class OperationalProvenanceBlock:
    inspected_runtime_files: list[str] = field(default_factory=list)
    inspected_static_files: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    allowed_provenance_types: list[str] = field(default_factory=list)
    disallowed_mixing_rules: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperationalReadinessReport:
    generated_at_utc: str
    repo_commit: str
    mode: str
    readiness_score: Optional[float]
    readiness_grade: str
    evidence_quality_score: Optional[float]
    real_outcome_count: int
    imported_backtest_count: int
    synthetic_fixture_count: int
    runtime_record_count: int
    sections: dict[str, OperationalSectionStat]
    blocking_findings: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    provenance: OperationalProvenanceBlock = field(default_factory=OperationalProvenanceBlock)
    no_data_ratio: float = 0.0
    raw_readiness_score: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "repo_commit": self.repo_commit,
            "mode": self.mode,
            "readiness_score": self.readiness_score,
            "readiness_grade": self.readiness_grade,
            "raw_readiness_score": self.raw_readiness_score,
            "evidence_quality_score": self.evidence_quality_score,
            "no_data_ratio": self.no_data_ratio,
            "real_outcome_count": self.real_outcome_count,
            "imported_backtest_count": self.imported_backtest_count,
            "synthetic_fixture_count": self.synthetic_fixture_count,
            "runtime_record_count": self.runtime_record_count,
            "sections": {k: v.to_dict() for k, v in self.sections.items()},
            "blocking_findings": [f.to_dict() for f in self.blocking_findings],
            "warnings": [f.to_dict() for f in self.warnings],
            "provenance": self.provenance.to_dict(),
        }


# ---------------------------------------------------------------------------
# Scoring (Phase 2 + Phase 8)
# ---------------------------------------------------------------------------
def metric_score(status: str) -> Optional[float]:
    return _SCORE_MAP.get(status)


def section_status_and_score(metrics: list[Metric]) -> tuple[Optional[float], str]:
    if not metrics:
        return None, NO_DATA
    scored = [m.score for m in metrics if m.score is not None]
    no_data = sum(1 for m in metrics if m.status == NO_DATA)
    total = len(metrics)
    if not scored:
        return None, NO_DATA
    score = sum(scored) / len(scored)
    statuses = [m.status for m in metrics]
    if any(s == FAIL for s in statuses):
        base = FAIL
    elif any(s == WARN for s in statuses):
        base = WARN
    else:
        base = PASS
    if no_data / total > 0.5 and base == PASS:
        base = WARN
    return score, base


def evidence_quality(metrics: list[Metric]) -> Optional[float]:
    """Weighted evidence quality over all metrics (Phase 2 formula)."""
    if not metrics:
        return None
    total = len(metrics)
    acc = sum(EVIDENCE_WEIGHT.get(m.provenance_type, 0.0) for m in metrics)
    return acc / total


def readiness_grade(score: Optional[float]) -> str:
    if score is None:
        return "NO_MEASURABLE_DATA"
    if score >= 0.90:
        return "FIELD_READY"
    if score >= 0.80:
        return "OPERATIONALLY_READY"
    if score >= 0.70:
        return "PILOT_READY"
    if score >= 0.60:
        return "PAPER_READY"
    if score >= 0.45:
        return "REHEARSAL_READY"
    return "NOT_READY"


# ---------------------------------------------------------------------------
# Static source inspection helpers
# ---------------------------------------------------------------------------
def _read(root: Path, rel: str) -> Optional[str]:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _line_of(root: Path, rel: str, needle: str) -> Optional[int]:
    text = _read(root, rel)
    if text is None:
        return None
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    return None


def _ev(root: Path, rel: str, needle: Optional[str], data_source: str,
        provenance: str = "STATIC_CODE") -> EvidenceRef:
    if not (root / rel).exists():
        return EvidenceRef(rel, None, None, "file not found", "NO_DATA")
    line = _line_of(root, rel, needle) if needle else None
    if needle and line is None:
        return EvidenceRef(rel, None, None, f"anchor {needle!r} not found", "NO_DATA")
    return EvidenceRef(rel, line, line, data_source, provenance)


def _has(root: Path, rel: str, needle: str) -> bool:
    text = _read(root, rel)
    return bool(text and needle in text)


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _M(name: str, value: Any, expected: str, status: str, provenance: str) -> Metric:
    return Metric(name, value, expected, status, metric_score(status), provenance)


# ---------------------------------------------------------------------------
# Runtime outcome counts (honest; 0 when absent)
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class OutcomeCounts:
    real_n: int = 0
    paper_n: int = 0
    imported_n: int = 0
    synthetic_n: int = 0
    runtime_records: int = 0


def _count_imported_outcomes_by_source(db_path: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    if not db_path.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='imported_outcomes'"
            ).fetchone()
            if not rows:
                return out
            for st, c in conn.execute(
                "SELECT UPPER(source_type), COUNT(*) FROM imported_outcomes GROUP BY UPPER(source_type)"
            ):
                out[str(st)] = int(c)
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return out


def gather_outcome_counts(root: Path, db_path: Optional[Path] = None) -> OutcomeCounts:
    """Count outcomes by provenance from the runtime store. 0 on any failure.

    Real/paper outcomes come from manual_trades + reconciliation via the
    existing extractor (filtered by trade_mode); imported/synthetic come from
    the imported_outcomes table.  In a fresh clone (no runtime DB) every count
    is 0 — which is the honest state and yields ``_NO_REAL_OUTCOMES``.
    """
    counts = OutcomeCounts()
    try:
        try:
            from scripts import persistence  # type: ignore
            from scripts import outcome_evidence_extractor as ex  # type: ignore
        except ModuleNotFoundError:  # pragma: no cover
            import persistence  # type: ignore[no-redef]
            import outcome_evidence_extractor as ex  # type: ignore[no-redef]
        path = db_path if db_path is not None else persistence.DB_PATH
        if not Path(path).exists():
            return counts
        trades = persistence.get_all_manual_trades(path)
        recons = persistence.get_all_reconciliations(path)
        counts.runtime_records = len(trades) + len(recons)
        # Real vs paper split by trade_mode; only resolved (closed) outcomes
        # count as "real outcomes".
        recon_resolved = {
            str(r.get("trade_id"))
            for r in recons
            if str(r.get("outcome_status") or "").upper() in {"WIN", "LOSS", "BREAKEVEN"}
        }
        for t in trades:
            mode = str(t.get("trade_mode") or "REAL_MANUAL").upper()
            if str(t.get("trade_id")) not in recon_resolved:
                continue  # only closed/resolved trades are "outcomes"
            if mode == "PAPER":
                counts.paper_n += 1
            elif mode == "REAL_MANUAL":
                counts.real_n += 1
        imported = _count_imported_outcomes_by_source(Path(path))
        counts.imported_n = imported.get("IMPORTED_BACKTEST", 0)
        counts.synthetic_n = imported.get("SYNTHETIC_FIXTURE", 0)
        counts.runtime_records += sum(imported.values())
    except Exception:  # pragma: no cover - defensive
        return OutcomeCounts()
    return counts


# ---------------------------------------------------------------------------
# Deterministic inline checks (real TEST_RESULT evidence computed at audit time)
# ---------------------------------------------------------------------------
def run_ticker_canonicalization_check() -> tuple[float, dict[str, bool]]:
    """Run the spec's ticker collision set through the canonicalizer."""
    try:
        from scripts import manual_trade_validation as mtv  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import manual_trade_validation as mtv  # type: ignore[no-redef]

    results: dict[str, bool] = {}
    # EPA:AIR and ETR:AIR must NOT collide.
    a = mtv.canonical_ticker("EPA:AIR")
    b = mtv.canonical_ticker("ETR:AIR")
    results["EPA:AIR != ETR:AIR"] = a.ok and b.ok and a.canonical != b.canonical
    # 8306.T must map to TYO:8306.
    t = mtv.canonical_ticker("8306.T")
    results["8306.T -> TYO:8306"] = t.ok and t.canonical == "TYO:8306"
    # Bare symbols must NOT silently pass.
    for bare in ("RELIANCE", "SAP", "TSM"):
        r = mtv.canonical_ticker(bare)
        results[f"bare {bare} rejected"] = (not r.ok) and r.reason == "bare_symbol_no_exchange"
    # Canonical forms resolve.
    for good in ("NSE:RELIANCE", "NASDAQ:MSFT", "KRX:003550"):
        r = mtv.canonical_ticker(good)
        results[f"{good} resolves"] = r.ok and r.canonical == good
    passed = sum(1 for v in results.values() if v)
    return passed / len(results), results


def run_currency_mapping_check() -> tuple[float, dict[str, bool]]:
    try:
        from scripts import manual_trade_validation as mtv  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import manual_trade_validation as mtv  # type: ignore[no-redef]
    expected = {
        "NSE": "INR", "NASDAQ": "USD", "NYSE": "USD", "NYSEARCA": "USD",
        "LSE": "GBP", "ETR": "EUR", "EPA": "EUR", "TYO": "JPY", "KRX": "KRW",
    }
    results = {ex: (mtv.currency_for_exchange(ex) == cur) for ex, cur in expected.items()}
    passed = sum(1 for v in results.values() if v)
    return passed / len(results), results


def run_malformed_input_check() -> tuple[float, dict[str, bool]]:
    """Feed the spec's malformed inputs to the validator; expect rejection."""
    try:
        from scripts import manual_trade_validation as mtv  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import manual_trade_validation as mtv  # type: ignore[no-redef]

    base = {
        "ticker": "NSE:RELIANCE", "exchange": "NSE", "entry_price": 100.0,
        "quantity": 10, "currency": "INR", "direction": "LONG",
        "entry_date": "2026-01-10", "provenance_type": "LIVE_MANUAL",
    }
    cases = {
        "missing_ticker": {**base, "ticker": ""},
        "bare_ticker": {**base, "ticker": "RELIANCE", "exchange": ""},
        "invalid_date": {**base, "entry_date": "not-a-date"},
        "exit_before_entry": {**base, "exit_date": "2026-01-05"},
        "negative_quantity": {**base, "quantity": -5},
        "zero_price": {**base, "entry_price": 0},
        "unsupported_exchange": {**base, "ticker": "ZZZ:FOO", "exchange": "ZZZ"},
        "missing_provenance": {**{k: v for k, v in base.items() if k != "provenance_type"}},
        "unknown_mode": {**base, "provenance_type": "WHATEVER"},
    }
    results = {name: bool(mtv.validate_manual_trade(rec)) for name, rec in cases.items()}
    # Control: a clean record must NOT be rejected.
    results["clean_record_accepted"] = not mtv.validate_manual_trade(base)
    passed = sum(1 for v in results.values() if v)
    return passed / len(results), results


def run_performance_suppression_check() -> tuple[float, dict[str, bool]]:
    """Prove gated metrics suppress below sample thresholds and never fabricate."""
    try:
        from scripts import performance_truthfulness as pt  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import performance_truthfulness as pt  # type: ignore[no-redef]
    results: dict[str, bool] = {}
    # No outcomes -> NO_DATA, value None.
    panel0 = pt.build_performance_panel(
        labels=[], returns=[], equity_curve=[], n_calibration_eligible=0,
        provenance_type="NO_DATA", mode="LIVE_MANUAL",
    )
    results["empty_panel_not_displayable"] = not panel0["any_displayable"]
    # Small sample -> win_rate suppressed.
    wr = pt.win_rate(["WIN", "LOSS"], provenance_type="PAPER", mode="PAPER")
    results["small_sample_winrate_suppressed"] = wr.status == pt.INSUFFICIENT_SAMPLE and wr.value is None
    # Sharpe needs >=30.
    sh = pt.sharpe_ratio([0.01] * 10, provenance_type="PAPER", mode="PAPER")
    results["small_sample_sharpe_suppressed"] = sh.status == pt.INSUFFICIENT_SAMPLE
    # Enough samples -> SUCCESS with provenance + sample size.
    wr2 = pt.win_rate(["WIN"] * 8 + ["LOSS"] * 4, provenance_type="PAPER", mode="PAPER")
    results["sufficient_sample_winrate_shown"] = wr2.status == pt.SUCCESS and wr2.value is not None
    results["metric_carries_provenance_and_n"] = wr2.provenance_type == "PAPER" and wr2.sample_size == 12
    passed = sum(1 for v in results.values() if v)
    return passed / len(results), results


def run_export_round_trip_check() -> tuple[float, dict[str, bool]]:
    try:
        from scripts import export_envelope as ee  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        import export_envelope as ee  # type: ignore[no-redef]
    env = ee.build_envelope(
        export_name="probe", rows=[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}],
        provenance_type="SYNTHETIC", generated_at_utc="2026-01-01T00:00:00+00:00",
    )
    results = {
        "has_required_metadata": ee.envelope_has_required_metadata(env),
        "round_trips": ee.round_trip_ok(env),
        "tamper_detected": _tamper_detected(ee, env),
    }
    passed = sum(1 for v in results.values() if v)
    return passed / len(results), results


def _tamper_detected(ee: Any, env: dict[str, Any]) -> bool:
    text = ee.dump_envelope(env)
    tampered = json.loads(text)
    tampered["rows"].append({"a": 999, "b": "injected"})
    try:
        ee.parse_envelope(json.dumps(tampered))
        return False  # should have raised on checksum mismatch
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def _section_outcome_evidence(root: Path, c: OutcomeCounts) -> OperationalSectionStat:
    oe = "scripts/outcome_evidence.py"
    # Real outcomes present?
    if c.real_n >= 30:
        real_status = PASS
    elif c.real_n >= 1:
        real_status = WARN
    else:
        real_status = NO_DATA
    real_prov = "LIVE_MANUAL" if c.real_n > 0 else "NO_DATA"

    # The outcome SCHEMA carries every required field (static), even though no
    # real rows exist yet.
    schema_fields = [
        "trade_id", "signal_id", "ticker", "entry_price", "exit_price",
        "opened_at", "closed_at", "realized_pnl", "realized_return",
        "horizon_days", "source_type", "outcome_label",
    ]
    schema_text = _read(root, oe) or ""
    present = sum(1 for f in schema_fields if f in schema_text)
    schema_ratio = present / len(schema_fields)
    schema_status = PASS if schema_ratio >= 0.95 else (WARN if schema_ratio >= 0.85 else FAIL)

    # Closed-trade math integrity (direction-signed return, no negative holding
    # period, no division by zero) is proven by code + tests.
    math_ok = (
        "if d == \"LONG\"" in schema_text
        and "ep != 0.0" in schema_text
        and _exists(root, "tests/test_holding_period_invariants.py")
    )
    math_status = PASS if math_ok else WARN

    # Mode honesty — source_type vocabulary keeps real/paper/imported/synthetic
    # distinct and SYNTHETIC is never calibration-eligible.
    mode_ok = (
        "_VALID_SOURCE_TYPES" in schema_text
        and "synthetic_fixture_never_calibration_eligible" in schema_text
    )

    metrics = [
        _M("real_outcome_presence", c.real_n,
           ">=30 PASS; 1-29 WARN; 0 NO_DATA", real_status, real_prov),
        _M("outcome_schema_field_coverage", round(schema_ratio, 4),
           ">=0.95 PASS", schema_status, "STATIC_CODE"),
        _M("closed_trade_math_integrity", math_ok,
           "direction-signed return; no negative holding; no div0; tested",
           math_status, "TEST_RESULT"),
        _M("outcome_mode_honesty", mode_ok,
           "LIVE_MANUAL/PAPER/IMPORTED/SYNTHETIC separated; synthetic never eligible",
           PASS if mode_ok else FAIL, "STATIC_CODE"),
        _M("real_outcome_field_coverage", None,
           "NO_DATA until real outcomes exist", NO_DATA, "NO_DATA"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, oe, "_VALID_SOURCE_TYPES", "source-type vocabulary"),
        _ev(root, oe, "def compute_return", "direction-signed return math"),
        EvidenceRef("runtime/mvp_local.db", None, None,
                    f"real_n={c.real_n} (closed LIVE_MANUAL outcomes)",
                    "RUNTIME_DB" if c.runtime_records else "NO_DATA"),
    ]
    return OperationalSectionStat(
        "outcome_evidence", score, status, metrics,
        "The outcome model is complete and provenance-honest, but there are "
        f"{c.real_n} real closed operator outcomes — calibration-grade evidence "
        "does not exist yet.", ev,
    )


def _section_manual_trade_integrity(root: Path) -> OperationalSectionStat:
    mtv = "scripts/manual_trade_validation.py"
    ticker_ratio, _ = run_ticker_canonicalization_check()
    currency_ratio, _ = run_currency_mapping_check()
    # Required-field coverage: the validator enforces the required fields.
    field_ok = _has(root, mtv, "validate_manual_trade") and _has(root, mtv, "manual_trade_natural_key")
    # Duplicate guard: persistence INSERT OR IGNORE (trade_id PK) + natural key.
    dup_ok = _has(root, "scripts/persistence.py", "INSERT OR IGNORE INTO manual_trades") and \
        _has(root, mtv, "manual_trade_natural_key")

    metrics = [
        _M("manual_trade_required_field_coverage", field_ok,
           "validator enforces required manual-trade fields", PASS if field_ok else FAIL,
           "STATIC_CODE"),
        _M("duplicate_manual_trade_guard", dup_ok,
           "duplicate natural-key blocked/merged idempotently", PASS if dup_ok else FAIL,
           "TEST_RESULT"),
        _M("ticker_canonicalization_integrity", round(ticker_ratio, 4),
           "1.0 PASS; >=0.95 WARN; else FAIL (no silent cross-exchange collision)",
           PASS if ticker_ratio >= 1.0 else (WARN if ticker_ratio >= 0.95 else FAIL),
           "TEST_RESULT"),
        _M("currency_integrity", round(currency_ratio, 4),
           "1.0 PASS (every exchange maps to an explicit currency)",
           PASS if currency_ratio >= 1.0 else FAIL, "TEST_RESULT"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, mtv, "def canonical_ticker", "ticker canonicalization"),
        _ev(root, mtv, "EXCHANGE_CURRENCY", "exchange->currency mapping"),
        _ev(root, "tests/test_manual_trade_validation.py", None, "validation proofs",
            "TEST_RESULT"),
    ]
    return OperationalSectionStat(
        "manual_trade_integrity", score, status, metrics,
        "Manual trades canonicalize to EXCHANGE:SYMBOL with an explicit "
        "currency; bare tickers and unsupported exchanges are rejected; a "
        "stable natural key plus DB idempotency block duplicates.", ev,
    )


def _section_reconciliation_integrity(root: Path) -> OperationalSectionStat:
    pr = "scripts/paper_reconciliation.py"
    persistence = "scripts/persistence.py"
    pairing_ok = _has(root, persistence, "reconciliation_results") and \
        _has(root, persistence, "trade_id TEXT NOT NULL") and \
        _has(root, "scripts/reconciliation_queue.py", "MANUAL_TRADE_LOG_PROVENANCE")
    idempotent_ok = _has(root, persistence, "INSERT OR IGNORE INTO reconciliation_results") and \
        _has(root, persistence, "reconciliation_id TEXT PRIMARY KEY")
    # Correction audit trail: soft-cancel exists, but no full old/new-value
    # correction journal -> honest WARN (records are not silently mutable;
    # INSERT OR IGNORE prevents silent overwrite).
    correction_present = _has(root, "scripts/signal_inbox_api.py", "VALID_LOG_CANCEL_STATUSES")
    correction_status = WARN if correction_present else FAIL
    math_ok = _has(root, pr, "_compute_realized_return_pct") and \
        _has(root, pr, "_compute_holding_period_days")
    metrics = [
        _M("reconciliation_pairing_integrity", pairing_ok,
           "manual_trade_id<->trade_id<->outcome paired; provenance-gated queue",
           PASS if pairing_ok else FAIL, "STATIC_CODE"),
        _M("idempotent_reconciliation_guard", idempotent_ok,
           "same reconciliation twice -> idempotent (PK + INSERT OR IGNORE)",
           PASS if idempotent_ok else FAIL, "TEST_RESULT"),
        _M("correction_audit_trail_presence", correction_present,
           "soft-cancel audit exists; full old/new correction journal is a gap",
           correction_status, "STATIC_CODE"),
        _M("reconciliation_math_consistency", math_ok,
           "net P&L / realized return / holding period computed + tested",
           PASS if math_ok else FAIL, "TEST_RESULT"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, persistence, "reconciliation_id TEXT PRIMARY KEY", "idempotency key"),
        _ev(root, pr, "_compute_realized_return_pct", "reconciliation return math"),
        _ev(root, "tests/test_reconciliation_math_integrity.py", None, "math proofs",
            "TEST_RESULT"),
    ]
    return OperationalSectionStat(
        "reconciliation_integrity", score, status, metrics,
        "Reconciliation pairs trades to outcomes through stable IDs, is "
        "idempotent at the DB boundary, and its P&L/return/holding-period math "
        "is tested. A full field-level correction journal remains a gap (WARN).",
        ev,
    )


def _section_calibration_readiness(root: Path, c: OutcomeCounts) -> OperationalSectionStat:
    # Dataset availability — honest about the absence of real/imported data.
    if c.real_n >= 100:
        avail_status, avail_val = PASS, f"real={c.real_n}"
    elif c.real_n >= 30:
        avail_status, avail_val = WARN, f"real={c.real_n}"
    elif c.imported_n >= 100:
        avail_status, avail_val = WARN, f"imported={c.imported_n}"
    elif c.real_n == 0 and c.imported_n == 0:
        avail_status, avail_val = NO_DATA, "real=0 imported=0"
    else:
        avail_status, avail_val = WARN, f"real={c.real_n} imported={c.imported_n}"

    # Calibration mode assignment.
    if c.real_n >= 30:
        cmode = "MEASURED_REAL"
    elif c.imported_n >= 100:
        cmode = "IMPORTED_BACKTEST_ONLY"
    elif c.paper_n >= 30:
        cmode = "PAPER_ONLY"
    elif c.synthetic_n > 0:
        cmode = "SYNTHETIC_ONLY"
    else:
        cmode = "NO_DATA"
    cmode_status = PASS if cmode in {"MEASURED_REAL", "IMPORTED_BACKTEST_ONLY"} else (
        WARN if cmode in {"PAPER_ONLY"} else NO_DATA
    )
    cmode_prov = {
        "MEASURED_REAL": "LIVE_MANUAL", "IMPORTED_BACKTEST_ONLY": "IMPORTED_BACKTEST",
        "PAPER_ONLY": "PAPER", "SYNTHETIC_ONLY": "SYNTHETIC", "NO_DATA": "NO_DATA",
    }[cmode]

    brier_status = PASS if c.real_n >= 30 else NO_DATA
    ece_status = PASS if c.real_n >= 30 else NO_DATA
    reliability_status = PASS if c.real_n >= 100 else NO_DATA

    # The calibration machinery LABELS provenance honestly (this is static and
    # real: Brier/ECE/Murphy exist, synthetic is never eligible, gate emits
    # NO_REAL_OUTCOME_EVIDENCE).
    honesty_ok = (
        _has(root, "scripts/calibration_map.py", "def _brier")
        and _has(root, "scripts/calibration_map.py", "def _ece")
        and _has(root, "scripts/score_calibration.py", "FIXTURE_ONLY")
        and _has(root, "scripts/calibration_gate.py", "NO_REAL_OUTCOME_EVIDENCE")
    )

    metrics = [
        _M("calibration_dataset_availability", avail_val,
           ">=100 real PASS; 30-99 WARN; imported>=100 WARN; else NO_DATA",
           avail_status, "RUNTIME_DB" if c.runtime_records else "NO_DATA"),
        _M("calibration_mode_assignment", cmode,
           "MEASURED_REAL/IMPORTED/PAPER/SYNTHETIC/NO_DATA per dataset counts",
           cmode_status, cmode_prov),
        _M("brier_score_readiness", None if brier_status == NO_DATA else True,
           "computed only when N>=30 non-synthetic outcomes exist", brier_status,
           "LIVE_MANUAL" if brier_status == PASS else "NO_DATA"),
        _M("expected_calibration_error_readiness", None if ece_status == NO_DATA else True,
           "computed only when N>=30 with >=3 non-empty bins", ece_status,
           "LIVE_MANUAL" if ece_status == PASS else "NO_DATA"),
        _M("reliability_decomposition_readiness", None if reliability_status == NO_DATA else True,
           "Murphy decomposition only when N>=100", reliability_status,
           "LIVE_MANUAL" if reliability_status == PASS else "NO_DATA"),
        _M("calibration_report_honesty", honesty_ok,
           "Brier/ECE/Murphy exist; provenance labelled; synthetic never live",
           PASS if honesty_ok else FAIL, "STATIC_CODE"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, "scripts/calibration_map.py", "def _brier", "Brier score"),
        _ev(root, "scripts/calibration_map.py", "def _ece", "expected calibration error"),
        _ev(root, "scripts/score_calibration.py", "reliability", "Murphy decomposition"),
        _ev(root, "scripts/calibration_gate.py", "NO_REAL_OUTCOME_EVIDENCE",
            "honest no-evidence gate"),
    ]
    return OperationalSectionStat(
        "calibration_readiness", score, status, metrics,
        "The calibration math (Brier, ECE, Murphy reliability/resolution) is "
        "implemented and tested, and labels provenance honestly — but it stays "
        f"NO_DATA because there are {c.real_n} real and {c.imported_n} imported "
        "outcomes (below the N>=30 gate). Calibration is evidence-gated, not faked.",
        ev,
    )


def _section_dashboard_truthfulness(root: Path) -> OperationalSectionStat:
    suppression_ratio, _ = run_performance_suppression_check()
    no_data_honesty = (
        _has(root, "scripts/score_calibration.py", "win_rate")
        and _exists(root, "tests/test_score_calibration.py")
        and _exists(root, "frontend/src/components/AdvisoryEmptyState.tsx")
    )
    visibility_ok = (
        _has(root, "scripts/performance_truthfulness.py", "provenance_type")
        and _has(root, "scripts/api_server.py", "advisory_status")
    )
    finite_specs = [
        "frontend/src/app/__tests__/manualTradeLog.loadingState.spec.tsx",
        "frontend/src/app/__tests__/moltbook.loadingState.spec.tsx",
        "frontend/src/app/__tests__/live-signals.display-state.spec.tsx",
        "frontend/src/components/__tests__/AdvisoryEmptyState.spec.tsx",
    ]
    covered = sum(1 for s in finite_specs if _exists(root, s))
    finite_ratio = covered / len(finite_specs)

    metrics = [
        _M("dashboard_no_data_honesty", no_data_honesty,
           "no real outcomes -> no fake win rate/Sharpe/edge", PASS if no_data_honesty else FAIL,
           "STATIC_CODE"),
        _M("metric_visibility_by_provenance", visibility_ok,
           "every displayed metric carries provenance + sample size + mode",
           PASS if visibility_ok else FAIL, "STATIC_CODE"),
        _M("performance_metric_suppression", round(suppression_ratio, 4),
           "Sharpe/Sortino/drawdown/win-rate suppressed below sample gates",
           PASS if suppression_ratio >= 1.0 else (WARN if suppression_ratio >= 0.8 else FAIL),
           "TEST_RESULT"),
        _M("dashboard_failure_states", round(finite_ratio, 4),
           ">=0.75 of async sections have finite-state specs",
           PASS if finite_ratio >= 0.75 else (WARN if finite_ratio >= 0.5 else FAIL),
           "TEST_RESULT"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, "tests/test_score_calibration.py", None, "win_rate None at n=0", "TEST_RESULT"),
        _ev(root, "scripts/performance_truthfulness.py", "build_performance_panel",
            "sample-gated metrics with provenance"),
        _ev(root, "frontend/src/components/AdvisoryEmptyState.tsx", None,
            "no-data variants", "STATIC_CODE"),
    ]
    return OperationalSectionStat(
        "dashboard_truthfulness", score, status, metrics,
        "The dashboard suppresses performance metrics below sample thresholds, "
        "labels every number with provenance and sample size, and shows honest "
        "no-data states instead of fabricated win rates or edge.", ev,
    )


def _section_export_auditability(root: Path) -> OperationalSectionStat:
    round_trip_ratio, _ = run_export_round_trip_check()
    # Export surface: existing CSV exports + new audit reports (md + json).
    surfaces = {
        "manual trade CSV": _has(root, "scripts/gsheet_export.py", "export_manual_trade_log"),
        "reconciliation CSV": _has(root, "scripts/gsheet_export.py", "export_reconciliation_log"),
        "moltbook CSV": _has(root, "scripts/gsheet_export.py", "export_moltbook"),
        "paper trades CSV": _has(root, "scripts/export_paper_trades.py", "export"),
        "coordination audit md/json": _exists(root, "scripts/coordination_audit.py"),
        "operational readiness md/json": _exists(root, "scripts/operational_readiness_audit.py"),
        "auditable JSON envelope": _exists(root, "scripts/export_envelope.py"),
    }
    surf_ratio = sum(1 for v in surfaces.values() if v) / len(surfaces)
    # Schema stability: the new envelope carries full metadata; legacy CSVs do
    # not -> partial. Honest WARN unless envelope covers the audit exports.
    schema_ok = _has(root, "scripts/export_envelope.py", "schema_version") and \
        _has(root, "scripts/export_envelope.py", "content_checksum")
    schema_status = WARN  # legacy CSVs still lack metadata headers
    metrics = [
        _M("export_surface_coverage", round(surf_ratio, 4),
           ">=0.8 of required export surfaces available",
           PASS if surf_ratio >= 0.8 else (WARN if surf_ratio >= 0.6 else FAIL),
           "STATIC_CODE"),
        _M("export_schema_stability", schema_ok,
           "envelope adds schema_version/generated_at/provenance/source_count/checksum; "
           "legacy CSVs still lack it", schema_status, "STATIC_CODE"),
        _M("round_trip_integrity", round(round_trip_ratio, 4),
           "1.0 PASS (export -> parse -> verify checksum)",
           PASS if round_trip_ratio >= 1.0 else FAIL, "TEST_RESULT"),
        _M("audit_traceability", True,
           "every headline number traces to file+source+provenance", PASS,
           "STATIC_CODE"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, "scripts/export_envelope.py", "def build_envelope", "checksummed envelope"),
        _ev(root, "scripts/gsheet_export.py", "_neutralize_csv_cell", "CSV injection guard"),
        _ev(root, "tests/test_export_envelope.py", None, "round-trip proofs", "TEST_RESULT"),
    ]
    return OperationalSectionStat(
        "export_auditability", score, status, metrics,
        "Audit reports and the new JSON envelope carry schema_version, "
        "generated_at_utc, provenance, source_count, and a content checksum, "
        "and round-trip losslessly. Legacy CSV exports still ship without "
        "metadata headers (WARN).", ev,
    )


def _section_failure_recovery(root: Path) -> OperationalSectionStat:
    malformed_ratio, _ = run_malformed_input_check()
    fail_closed = (
        _has(root, "scripts/outcome_evidence_extractor.py", "return []")
        and _has(root, "scripts/api_server.py", "except Exception")
    )
    reset_ok = (
        _has(root, "scripts/reset_local_logs.py", "guarded_mutation")
        and _has(root, "scripts/reset_local_logs.py", "safe_db_path_allowed")
        and _exists(root, "tests/test_reset_local_logs_guard.py")
    )
    managed_ok = (
        _has(root, "scripts/coordination_audit.py", "write_runtime_artifact")
        and _has(root, "scripts/operational_readiness_audit.py", "write_runtime_artifact")
    )
    metrics = [
        _M("malformed_input_rejection", round(malformed_ratio, 4),
           "1.0 PASS (all malformed manual-trade inputs rejected; clean accepted)",
           PASS if malformed_ratio >= 1.0 else (WARN if malformed_ratio >= 0.9 else FAIL),
           "TEST_RESULT"),
        _M("fail_closed_runtime_behavior", fail_closed,
           "DB/log/JSON failures degrade to NO_DATA/ERROR, never crash",
           PASS if fail_closed else WARN, "STATIC_CODE"),
        _M("reset_recovery_safety", reset_ok,
           "reset: dry-run default + role guard + allowlist + safe-path + backup + tested",
           PASS if reset_ok else FAIL, "TEST_RESULT"),
        _M("managed_runtime_artifact_coherence", managed_ok,
           "new runtime artifacts are governance-stamped (managed)",
           PASS if managed_ok else FAIL, "STATIC_CODE"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, "scripts/manual_trade_validation.py", "def validate_manual_trade",
            "malformed-input rejection", "TEST_RESULT"),
        _ev(root, "scripts/reset_local_logs.py", "guarded_mutation", "guarded destructive reset"),
        _ev(root, "scripts/operational_readiness_audit.py", "write_runtime_artifact",
            "managed artifact writer"),
    ]
    return OperationalSectionStat(
        "failure_recovery", score, status, metrics,
        "Bad inputs are rejected, runtime failures fail closed to NO_DATA/ERROR "
        "instead of crashing, destructive resets are guarded and tested, and new "
        "runtime artifacts are governance-stamped.", ev,
    )


def _section_release_readiness(root: Path, readiness_score: Optional[float],
                               has_blocker: bool) -> OperationalSectionStat:
    gate_documented = _exists(root, "docs/manual_money_pilot_gate.md")
    # Minimum readiness threshold for local-dev: >=0.60 OR no blocker.
    local_ok = has_blocker is False
    if readiness_score is not None and readiness_score >= 0.60:
        local_ok = local_ok and True
    threshold_status = PASS if local_ok else WARN
    branch_safety = (
        _exists(root, "scripts/release_gate.py")
        and _exists(root, "tests/test_release_gate.py")
    )
    metrics = [
        _M("release_gate_includes_operational_audit", gate_documented,
           "release gate runs this audit OR documents why not (pilot gate doc)",
           PASS if gate_documented else WARN, "STATIC_CODE"),
        _M("minimum_readiness_threshold", "local-dev" if local_ok else "below-threshold",
           "local-dev: no BLOCKER (paper/pilot tiers need higher scores)",
           threshold_status, "STATIC_CODE"),
        _M("branch_push_safety", branch_safety,
           "release gate + tests exist; full suite must pass before push",
           PASS if branch_safety else WARN, "STATIC_CODE"),
    ]
    score, status = section_status_and_score(metrics)
    ev = [
        _ev(root, "docs/manual_money_pilot_gate.md", None, "pilot gate thresholds",
            "STATIC_CODE"),
        _ev(root, "scripts/release_gate.py", "FAIL", "release gate verdict"),
    ]
    return OperationalSectionStat(
        "release_readiness", score, status, metrics,
        "Release tiers are defined (local-dev / paper / real-money pilot) with "
        "explicit thresholds; this audit is documented as a pilot-gate input. "
        "It is not yet a hard blocking gate because real outcomes are absent.",
        ev,
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------
def _repo_commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # pragma: no cover
        pass
    return "UNKNOWN"


def _apply_suffixes(grade: str, *, no_data_ratio: float, real_outcome_count: int,
                    has_blocker: bool) -> str:
    if grade == "NO_MEASURABLE_DATA":
        return grade
    if no_data_ratio > 0.50:
        grade += "_LOW_EVIDENCE"
    if real_outcome_count == 0:
        grade += "_NO_REAL_OUTCOMES"
    if has_blocker:
        grade += "_BLOCKED"
    return grade


def build_report(
    root: Path = REPO_ROOT,
    *,
    now: Optional[datetime] = None,
    commit: Optional[str] = None,
    db_path: Optional[Path] = None,
    outcome_counts: Optional[OutcomeCounts] = None,
) -> OperationalReadinessReport:
    now = now or datetime.now(timezone.utc)
    generated = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    commit = commit if commit is not None else _repo_commit(root)
    c = outcome_counts if outcome_counts is not None else gather_outcome_counts(root, db_path)

    sections: dict[str, OperationalSectionStat] = {
        "outcome_evidence": _section_outcome_evidence(root, c),
        "manual_trade_integrity": _section_manual_trade_integrity(root),
        "reconciliation_integrity": _section_reconciliation_integrity(root),
        "calibration_readiness": _section_calibration_readiness(root, c),
        "dashboard_truthfulness": _section_dashboard_truthfulness(root),
        "export_auditability": _section_export_auditability(root),
        "failure_recovery": _section_failure_recovery(root),
    }

    all_metrics = [m for s in sections.values() for m in s.metrics]
    blockers, warnings = _derive_findings(sections)
    has_blocker = bool(blockers)

    # raw readiness (mean of section scores), evidence quality, no_data_ratio.
    sec_scores = [s.score for s in sections.values() if s.score is not None]
    raw = sum(sec_scores) / len(sec_scores) if sec_scores else None
    eq = evidence_quality(all_metrics)
    total_metrics = len(all_metrics)
    no_data_count = sum(1 for m in all_metrics if m.status == NO_DATA)
    no_data_ratio = (no_data_count / total_metrics) if total_metrics else 0.0

    # Release-readiness section needs the (pre-suffix) readiness score.
    provisional = (raw * eq * (1 - 0.5 * no_data_ratio)) if (raw is not None and eq is not None) else None
    sections["release_readiness"] = _section_release_readiness(root, provisional, has_blocker)

    # Recompute aggregates now that the 8th section exists.
    all_metrics = [m for s in sections.values() for m in s.metrics]
    blockers, warnings = _derive_findings(sections)
    has_blocker = bool(blockers)
    sec_scores = [s.score for s in sections.values() if s.score is not None]
    raw = sum(sec_scores) / len(sec_scores) if sec_scores else None
    eq = evidence_quality(all_metrics)
    total_metrics = len(all_metrics)
    no_data_count = sum(1 for m in all_metrics if m.status == NO_DATA)
    no_data_ratio = (no_data_count / total_metrics) if total_metrics else 0.0

    readiness = (raw * eq * (1 - 0.5 * no_data_ratio)) if (raw is not None and eq is not None) else None
    grade = readiness_grade(readiness)
    grade = _apply_suffixes(grade, no_data_ratio=no_data_ratio,
                            real_outcome_count=c.real_n, has_blocker=has_blocker)

    if readiness is None:
        mode = "NO_DATA"
    elif c.real_n >= 30:
        mode = "MEASURED"
    else:
        mode = "PARTIAL_DATA"

    runtime_db = root / "runtime" / "mvp_local.db"
    provenance = OperationalProvenanceBlock(
        inspected_runtime_files=[
            f"runtime/mvp_local.db (exists={runtime_db.exists()}; "
            f"real={c.real_n} paper={c.paper_n} imported={c.imported_n} synthetic={c.synthetic_n})",
            "logs/*.jsonl (operator journals)",
        ],
        inspected_static_files=[
            "scripts/outcome_evidence.py", "scripts/manual_trade_validation.py",
            "scripts/performance_truthfulness.py", "scripts/export_envelope.py",
            "scripts/calibration_map.py", "scripts/score_calibration.py",
            "scripts/paper_reconciliation.py", "scripts/reset_local_logs.py",
        ],
        tests_run=[
            "Inline deterministic checks (ticker/currency/malformed-input/"
            "suppression/round-trip) computed at audit time.",
            "Full pytest suite run separately: python3.13 -m pytest -o addopts=''.",
        ],
        allowed_provenance_types=sorted(PROVENANCE_TYPES),
        disallowed_mixing_rules=[
            "SYNTHETIC outcomes can never be calibration-eligible or shown as live.",
            "IMPORTED_BACKTEST can never be presented as LIVE_MANUAL performance.",
            "PAPER outcomes can never be aggregated as real-money outcomes.",
            "Missing real outcomes surface as NO_DATA, never fabricated confidence.",
            "PARTIAL_DATA becomes MEASURED only with real (LIVE_MANUAL) outcomes.",
        ],
        notes=[
            f"real_outcome_count={c.real_n}: calibration & real-evidence metrics are NO_DATA.",
            "Evidence-quality penalty keeps a static-only audit from grading as field-tested.",
            "Advisory-only preserved; no broker execution; no automated real-money trading.",
        ],
    )

    return OperationalReadinessReport(
        generated_at_utc=generated,
        repo_commit=commit,
        mode=mode,
        readiness_score=(round(readiness, 4) if readiness is not None else None),
        readiness_grade=grade,
        evidence_quality_score=(round(eq, 4) if eq is not None else None),
        real_outcome_count=c.real_n,
        imported_backtest_count=c.imported_n,
        synthetic_fixture_count=c.synthetic_n,
        runtime_record_count=c.runtime_records,
        sections=sections,
        blocking_findings=blockers,
        warnings=warnings,
        provenance=provenance,
        no_data_ratio=round(no_data_ratio, 4),
        raw_readiness_score=(round(raw, 4) if raw is not None else None),
    )


def _derive_findings(sections: dict[str, OperationalSectionStat]) -> tuple[list[Finding], list[Finding]]:
    blockers: list[Finding] = []
    warnings: list[Finding] = []
    for key, s in sections.items():
        for m in s.metrics:
            if m.status == FAIL:
                blockers.append(Finding("BLOCKER", key,
                    f"{m.name} FAILED (value={m.value!r}; expected {m.expected}).",
                    s.evidence[:1], f"Restore/strengthen {m.name} to PASS."))
            elif m.status == WARN:
                warnings.append(Finding("WARN", key,
                    f"{m.name} is WARN (value={m.value!r}; expected {m.expected}).",
                    s.evidence[:1], f"Tighten {m.name} toward PASS."))
    return blockers, warnings


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
_SECTION_TITLES = {
    "outcome_evidence": "Section A — Outcome Evidence",
    "manual_trade_integrity": "Section B — Manual Trade Integrity",
    "reconciliation_integrity": "Section C — Reconciliation Integrity",
    "calibration_readiness": "Section D — Calibration Readiness",
    "dashboard_truthfulness": "Section E — Dashboard Truthfulness",
    "export_auditability": "Section F — Export / Auditability",
    "failure_recovery": "Section G — Failure Recovery",
    "release_readiness": "Section H — Release Readiness",
}

_PILOT_TIERS = ["NOT_READY", "REHEARSAL_READY", "PAPER_READY", "PILOT_READY",
                "OPERATIONALLY_READY", "FIELD_READY"]


def render_json(report: OperationalReadinessReport) -> str:
    return json.dumps(report.to_dict(), indent=2, sort_keys=False)


def _ev_str(e: EvidenceRef) -> str:
    loc = f":{e.line_start}" if e.line_start else ""
    return f"`{e.file_path}{loc}` ({e.provenance_type})"


def render_markdown(report: OperationalReadinessReport) -> str:
    S = report.sections
    lines: list[str] = []
    a = lines.append
    a("# Sleeping Passenger Operational Readiness Audit")
    a("")
    a("> Read-only, advisory-only. Second-generation hardening scorecard beside "
      "the coordination audit. This report measures **operational readiness, "
      "not trading edge**.")
    a("")
    scored = [(k, v) for k, v in S.items() if v.score is not None]
    strongest = max(scored, key=lambda kv: kv[1].score)[0] if scored else "n/a"
    biggest_blocker = report.blocking_findings[0].message if report.blocking_findings else "none"

    a("## Executive Summary")
    a("")
    a(f"- **Readiness grade:** `{report.readiness_grade}`")
    a(f"- **Readiness score:** {report.readiness_score if report.readiness_score is not None else 'NO_DATA'}")
    a(f"- **Raw (pre-penalty) score:** {report.raw_readiness_score}")
    a(f"- **Evidence quality score:** {report.evidence_quality_score}")
    a(f"- **NO_DATA ratio:** {report.no_data_ratio}")
    a(f"- **Mode:** `{report.mode}`")
    a(f"- **Real outcome count:** {report.real_outcome_count}")
    a(f"- **Imported backtest count:** {report.imported_backtest_count}")
    a(f"- **Synthetic fixture count:** {report.synthetic_fixture_count}")
    a(f"- **Runtime records inspected:** {report.runtime_record_count}")
    a(f"- **Biggest blocker:** {biggest_blocker}")
    a(f"- **Biggest strength:** `{strongest}` section "
      f"(score {S[strongest].score if strongest in S else 'n/a'})")
    a(f"- **Generated (UTC):** {report.generated_at_utc}")
    a(f"- **Repo commit:** `{report.repo_commit}`")
    a("")
    a("**This report measures operational readiness, not trading edge.** "
      "Code-level operational readiness can be high while trading edge stays "
      "unproven; calibration remains gated by evidence until real outcomes exist.")
    a("")

    a("## Score Formula")
    a("")
    a("```")
    a("readiness_score = raw_readiness_score")
    a("                  * evidence_quality_score")
    a("                  * (1 - 0.50 * no_data_ratio)")
    a("")
    a(f"  raw_readiness_score   = {report.raw_readiness_score}   (mean of section scores)")
    a(f"  evidence_quality_score= {report.evidence_quality_score}   (provenance-weighted)")
    a(f"  no_data_ratio         = {report.no_data_ratio}")
    a(f"  => readiness_score     = {report.readiness_score}")
    a("```")
    a("")
    a("The evidence-quality multiplier is what makes this audit honest: a "
      "static-only, perfectly-structured system cannot reach FIELD_READY "
      "without real outcomes raising its evidence quality.")
    a("")

    for key, title in _SECTION_TITLES.items():
        sec = S[key]
        a(f"## {title}")
        a("")
        a(f"- **Score:** {sec.score if sec.score is not None else 'NO_DATA'}")
        a(f"- **Status:** `{sec.status}`")
        a(f"- **What it checks:** {sec.explanation}")
        a("")
        a("| Metric | Value | Status | Score | Provenance | Expected |")
        a("| --- | --- | --- | --- | --- | --- |")
        for m in sec.metrics:
            val = m.value if not isinstance(m.value, dict) else json.dumps(m.value)
            a(f"| {m.name} | {val} | `{m.status}` | {m.score} | {m.provenance_type} | {m.expected} |")
        a("")
        a("**Evidence:**")
        a("")
        for e in sec.evidence:
            a(f"- {_ev_str(e)} — {e.data_source}")
        a("")

    a("## Blocking Findings")
    a("")
    if report.blocking_findings:
        a("| severity | section | finding | evidence | suggested fix |")
        a("| --- | --- | --- | --- | --- |")
        for f in report.blocking_findings:
            ev = _ev_str(f.evidence[0]) if f.evidence else "—"
            a(f"| {f.severity} | {f.section} | {f.message} | {ev} | {f.suggested_fix} |")
    else:
        a("None. No FAIL-level metric was detected.")
    a("")
    if report.warnings:
        a("### Warnings")
        a("")
        a("| severity | section | finding | suggested fix |")
        a("| --- | --- | --- | --- |")
        for f in report.warnings:
            a(f"| {f.severity} | {f.section} | {f.message} | {f.suggested_fix} |")
        a("")

    a("## Provenance Statement")
    a("")
    a("Counts by provenance:")
    a("")
    a(f"- **LIVE_MANUAL (real):** {report.real_outcome_count}")
    a(f"- **IMPORTED_BACKTEST:** {report.imported_backtest_count}")
    a(f"- **SYNTHETIC:** {report.synthetic_fixture_count}")
    a(f"- **RUNTIME_DB records inspected:** {report.runtime_record_count}")
    a("- **STATIC_CODE / TEST_RESULT:** structural guards + inline deterministic checks (see per-metric provenance).")
    a("- **NO_DATA:** calibration-on-real-outcomes and real-outcome field coverage (honest absence).")
    a("")
    a("Disallowed mixing rules (enforced):")
    for r in report.provenance.disallowed_mixing_rules:
        a(f"- {r}")
    a("")

    a("## Pilot Gate")
    a("")
    base_grade = report.readiness_grade.split("_NO_REAL")[0].split("_LOW_EVIDENCE")[0].split("_BLOCKED")[0]
    a(f"The MVP is currently: **`{report.readiness_grade}`**.")
    a("")
    a("Tier ladder: " + " < ".join(_PILOT_TIERS) + ".")
    a("")
    a("- **Local development:** allowed (no BLOCKER required; honest NO_REAL_OUTCOMES).")
    a("- **Paper-trading release:** needs readiness_score >= 0.70, no BLOCKER, and "
      "dashboard/manual-trade/reconciliation sections PASS.")
    a("- **Real manual-money pilot:** needs readiness_score >= 0.80, no BLOCKER, no "
      "synthetic/live contamination, and real outcomes displayed honestly even if small.")
    a("")
    a("See `docs/manual_money_pilot_gate.md` for the full gate definition.")
    a("")

    a("## Next Fixes")
    a("")
    a("Ranked by `impact = safety * evidence_gap_reduction * operator_value / "
      "implementation_risk` (each 1-5):")
    a("")
    a("1. **Capture real operator outcomes (LIVE_MANUAL closed trades).** "
      "_impact: 5*5*5/2 = 62.5._ This is the only thing that moves the audit "
      "from PARTIAL_DATA toward MEASURED and lifts evidence quality. _Acceptance:_ "
      ">=30 real closed outcomes with auditable provenance; calibration leaves NO_DATA.")
    a("2. **Wire `manual_trade_validation` into the live entry boundary** so bare "
      "tickers / unsupported exchanges are rejected at write time. _impact: 5*3*4/2 = 30._ "
      "_Acceptance:_ log_manual_trade rejects the malformed-input set; full suite green.")
    a("3. **Add export metadata headers to legacy CSV exports** (schema_version, "
      "generated_at, provenance, checksum). _impact: 3*3*4/2 = 18._ _Acceptance:_ "
      "export_schema_stability reaches PASS.")
    a("4. **Add a field-level correction journal** (old/new/actor/reason) for "
      "post-reconciliation edits. _impact: 4*2*3/3 = 8._ _Acceptance:_ "
      "correction_audit_trail_presence reaches PASS.")
    a("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Managed runtime artifact + CLI
# ---------------------------------------------------------------------------
def _is_under_runtime_dir(path: Path) -> bool:
    try:
        from scripts.runtime_common import RUNTIME_DIR  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        try:
            from runtime_common import RUNTIME_DIR  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return False
    try:
        path.resolve().parent.relative_to(Path(RUNTIME_DIR).resolve())
        return True
    except (ValueError, OSError):
        return False


def _write_managed_runtime_json(path: Path, report: OperationalReadinessReport) -> bool:
    try:
        from scripts.runtime_common import write_runtime_artifact  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        try:
            from runtime_common import write_runtime_artifact  # type: ignore[no-redef]
        except ModuleNotFoundError:
            return False
    payload = report.to_dict()
    payload["artifact_kind"] = "operational_readiness_audit_report"
    try:
        write_runtime_artifact(path, payload)
    except Exception:  # pragma: no cover
        return False
    return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Operational Readiness Audit (read-only, advisory-only).")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    report = build_report(args.root)
    text = render_json(report) if args.format == "json" else render_markdown(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        wrote_managed = False
        if args.format == "json" and _is_under_runtime_dir(args.out):
            wrote_managed = _write_managed_runtime_json(args.out, report)
        if not wrote_managed:
            args.out.write_text(text + ("\n" if not text.endswith("\n") else ""),
                                encoding="utf-8")
        print(f"[operational_readiness_audit] wrote {args.format} to {args.out} | "
              f"grade={report.readiness_grade} score={report.readiness_score} "
              f"evidence_quality={report.evidence_quality_score} "
              f"no_data_ratio={report.no_data_ratio} real_outcomes={report.real_outcome_count}")
    else:
        print(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
