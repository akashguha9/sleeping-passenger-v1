"""Position truth resolver — visibility-only helper over the split position sources.

Background:
    * ``moltbook/open_positions.json`` is the curated (seeded) position fixture
      used by the action engine and diagnostics.
    * ``runtime/paper_positions.json`` is the runtime paper-execution ledger
      produced by ``paper_execution.py``.

Those two files can drift — a position added via paper_execution may not be
mirrored in moltbook, and vice versa. Silently choosing either side as
authoritative invites confusion. This module produces a single, honest
summary of what each source says and flags divergence explicitly.

Rules:
    * Never mutate either file.
    * Never auto-migrate.
    * Never pick a side as "truth" and suppress the other.
    * When both exist but differ, report ``position_source_divergence_detected=True``.
    * When only one exists, call that out explicitly.
    * When neither exists, emit a no-position summary with a warning.

The resolver returns a plain dict so diagnostics can splice it into the
health report without coupling to internal classes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT, repo_relative
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import REPO_ROOT, repo_relative

try:
    from scripts.runtime_contracts import (
        PositionIntegrityState,
        TruthOrigin,
        coerce_position_state,
        coerce_truth_origin,
    )
except ModuleNotFoundError:  # pragma: no cover
    from runtime_contracts import (  # type: ignore[no-redef]
        PositionIntegrityState,
        TruthOrigin,
        coerce_position_state,
        coerce_truth_origin,
    )


DEFAULT_CURATED_PATH = REPO_ROOT / "moltbook" / "open_positions.json"
DEFAULT_RUNTIME_PATH = REPO_ROOT / "runtime" / "paper_positions.json"


def _load_positions_list(path: Path) -> list[dict[str, Any]] | None:
    """Load a positions file. Returns:
        * None        — file does not exist
        * []          — file exists but is empty / malformed
        * list[dict]  — parsed positions
    """
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        positions = data.get("positions")
        if isinstance(positions, list):
            return [row for row in positions if isinstance(row, dict)]
    return []


def _symbols(rows: Iterable[dict[str, Any]] | None) -> list[str]:
    if not rows:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker") or row.get("symbol") or "").strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return sorted(out)


def _checksum(source_name: str, symbols: list[str], count: int) -> str:
    payload = json.dumps(
        {
            "source": source_name,
            "symbols": sorted(symbols),
            "count": int(count),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_position_truth_summary(
    curated_path: Path | str | None = None,
    runtime_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a visibility-only summary of the two position sources.

    Does not modify either file. Does not pick a side.
    """
    curated_target = Path(curated_path) if curated_path is not None else DEFAULT_CURATED_PATH
    runtime_target = Path(runtime_path) if runtime_path is not None else DEFAULT_RUNTIME_PATH

    curated_rows = _load_positions_list(curated_target)
    runtime_rows = _load_positions_list(runtime_target)

    curated_present = curated_rows is not None
    runtime_present = runtime_rows is not None
    curated_symbols = _symbols(curated_rows)
    runtime_symbols = _symbols(runtime_rows)
    curated_count = len(curated_rows) if curated_rows else 0
    runtime_count = len(runtime_rows) if runtime_rows else 0

    overlap = sorted(set(curated_symbols) & set(runtime_symbols))
    missing_from_runtime = sorted(set(curated_symbols) - set(runtime_symbols))
    missing_from_curated = sorted(set(runtime_symbols) - set(curated_symbols))

    canonical = "curated_moltbook"
    advisory_sources = ["runtime_paper"] if runtime_present else []
    canonical_checksum = _checksum(canonical, curated_symbols, curated_count)
    advisory_checksum = _checksum("runtime_paper", runtime_symbols, runtime_count)

    if not curated_present and not runtime_present:
        position_integrity_state = "MISSING_CANONICAL"
        warning = (
            "Neither moltbook/open_positions.json nor runtime/paper_positions.json "
            "exists; there is no active position truth in this checkout."
        )
        divergence = False
    elif curated_present and not runtime_present:
        default_seeded_paths = (
            curated_target.resolve() == DEFAULT_CURATED_PATH.resolve()
            and runtime_target.resolve() == DEFAULT_RUNTIME_PATH.resolve()
        )
        position_integrity_state = "DIVERGED" if default_seeded_paths else "CLEAN"
        warning = (
            "Only curated moltbook/open_positions.json exists. The runtime "
            + (
                "paper-position ledger has not been created, so seeded/default "
                "position truth remains conservatively divergent until runtime "
                "paper state exists for reconciliation."
                if default_seeded_paths
                else "paper-position ledger has not been created."
            )
        )
        divergence = default_seeded_paths
    elif runtime_present and not curated_present:
        position_integrity_state = "MISSING_CANONICAL"
        warning = (
            "Only runtime/paper_positions.json exists. The canonical curated moltbook "
            "position fixture is absent, so runtime remains advisory only."
        )
        divergence = False
    else:
        divergence = bool(missing_from_runtime) or bool(missing_from_curated) or (
            curated_count != runtime_count
        )
        position_integrity_state = "DIVERGED" if divergence else "CLEAN"
        if divergence:
            warning = (
                "Position sources diverge: curated moltbook and runtime paper "
                "ledgers disagree on symbols or counts. Neither file was "
                "modified; this summary is visibility-only."
            )
        else:
            warning = None

    reconciliation_report = build_position_reconciliation_report(
        curated_path=curated_target,
        runtime_path=runtime_target,
    )

    return {
        "position_truth_source": canonical if curated_present else "missing_canonical",
        "canonical_position_source": canonical,
        "canonical_position_count": curated_count,
        "advisory_position_sources": advisory_sources,
        "curated_position_source_path": repo_relative(curated_target),
        "runtime_position_source_path": repo_relative(runtime_target),
        "curated_positions_present": curated_present,
        "runtime_paper_positions_present": runtime_present,
        "curated_moltbook_positions_count": curated_count,
        "runtime_paper_positions_count": runtime_count,
        "curated_symbols": curated_symbols,
        "runtime_symbols": runtime_symbols,
        "overlap_symbols": overlap,
        "missing_from_runtime": missing_from_runtime,
        "missing_from_curated": missing_from_curated,
        "position_source_divergence_detected": divergence,
        "position_integrity_state": position_integrity_state,
        "position_truth_warning": warning,
        "position_reconciliation_report": reconciliation_report,
        "position_reconciliation_artifact": reconciliation_report["position_reconciliation_artifact"],
        "curated_only_symbols": reconciliation_report["curated_only_symbols"],
        "runtime_only_symbols": reconciliation_report["runtime_only_symbols"],
        "overlapping_symbols": reconciliation_report["overlapping_symbols"],
        "recommended_canonical_source": reconciliation_report["recommended_canonical_source"],
        "divergence_severity": reconciliation_report["divergence_severity"],
        "safe_next_action": reconciliation_report["safe_next_action"],
        "canonical_position_checksum": canonical_checksum,
        "advisory_position_checksum": advisory_checksum,
    }


def build_position_reconciliation_report(
    curated_path: Path | str | None = None,
    runtime_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return a deterministic visibility-only reconciliation report.

    This is explicitly advisory. It never mutates curated/runtime ledgers and
    never auto-selects runtime paper state over the curated moltbook fixture.
    """
    curated_target = Path(curated_path) if curated_path is not None else DEFAULT_CURATED_PATH
    runtime_target = Path(runtime_path) if runtime_path is not None else DEFAULT_RUNTIME_PATH

    curated_rows = _load_positions_list(curated_target)
    runtime_rows = _load_positions_list(runtime_target)
    curated_present = curated_rows is not None
    runtime_present = runtime_rows is not None
    curated_symbols = _symbols(curated_rows)
    runtime_symbols = _symbols(runtime_rows)
    curated_only_symbols = sorted(set(curated_symbols) - set(runtime_symbols))
    runtime_only_symbols = sorted(set(runtime_symbols) - set(curated_symbols))
    overlapping_symbols = sorted(set(curated_symbols) & set(runtime_symbols))
    curated_count = len(curated_rows) if curated_rows else 0
    runtime_count = len(runtime_rows) if runtime_rows else 0

    canonical_position_checksum = _checksum("curated_moltbook", curated_symbols, curated_count)
    advisory_position_checksum = _checksum("runtime_paper", runtime_symbols, runtime_count)

    if not curated_present and not runtime_present:
        recommended_canonical_source = "none"
        divergence_severity = "HIGH"
        safe_next_action = (
            "No canonical curated position source exists; restore moltbook/open_positions.json "
            "before treating any runtime ledger as more than advisory."
        )
    elif curated_present and not runtime_present:
        recommended_canonical_source = "curated_moltbook"
        divergence_severity = "LOW"
        safe_next_action = (
            "Continue using curated moltbook as the canonical diagnostics source and "
            "create the runtime paper ledger before attempting position reconciliation."
        )
    elif runtime_present and not curated_present:
        recommended_canonical_source = "curated_moltbook"
        divergence_severity = "CRITICAL"
        safe_next_action = (
            "Keep runtime paper positions advisory only and restore the curated "
            "moltbook fixture before promoting any position truth as canonical."
        )
    else:
        recommended_canonical_source = "curated_moltbook"
        if curated_only_symbols or runtime_only_symbols or curated_count != runtime_count:
            divergence_severity = "HIGH"
            safe_next_action = (
                "Keep curated moltbook canonical, review symbol/count drift manually, "
                "and do not auto-migrate positions between sources."
            )
        else:
            divergence_severity = "NONE"
            safe_next_action = (
                "Sources agree; continue using curated moltbook as canonical while "
                "keeping runtime paper positions as a visibility cross-check."
            )

    return {
        "artifact_kind": "position_reconciliation_artifact",
        "artifact_version": 1,
        "curated_only_symbols": curated_only_symbols,
        "runtime_only_symbols": runtime_only_symbols,
        "overlapping_symbols": overlapping_symbols,
        "recommended_canonical_source": recommended_canonical_source,
        "divergence_severity": divergence_severity,
        "safe_next_action": safe_next_action,
        "position_reconciliation_artifact": {
            "canonical_source": "curated_moltbook",
            "canonical_position_count": curated_count,
            "canonical_position_symbols": curated_symbols,
            "advisory_sources": ["runtime_paper"] if runtime_present else [],
            "advisory_position_count": runtime_count,
            "advisory_position_symbols": runtime_symbols,
            "canonical_position_checksum": canonical_position_checksum,
            "advisory_position_checksum": advisory_position_checksum,
            "curated_only_symbols": curated_only_symbols,
            "runtime_only_symbols": runtime_only_symbols,
            "overlapping_symbols": overlapping_symbols,
        },
    }


def get_canonical_position_path(
    curated_path: Path | str | None = None,
    runtime_path: Path | str | None = None,
) -> Path | None:
    """Pick a single path that downstream action/diagnostics code can read.

    Default: ``moltbook/open_positions.json`` (the curated source is
    authoritative when present).
    Fallback: ``runtime/paper_positions.json`` if the curated file is absent
    but the runtime file exists.
    Return None when neither exists — the caller must handle that by
    failing closed rather than fabricating a position set.
    """
    curated_target = Path(curated_path) if curated_path is not None else DEFAULT_CURATED_PATH
    runtime_target = Path(runtime_path) if runtime_path is not None else DEFAULT_RUNTIME_PATH
    if curated_target.exists():
        return curated_target
    if runtime_target.exists():
        return runtime_target
    return None


def format_position_truth_summary(summary: dict[str, Any]) -> list[str]:
    """Shape the summary as the four summary lines diagnostics surface."""
    lines = [
        f"position_truth_source={summary.get('canonical_position_source', 'none')}",
        (
            "position_source_divergence_detected="
            f"{str(bool(summary.get('position_source_divergence_detected'))).lower()}"
        ),
        f"position_integrity_state={summary.get('position_integrity_state', 'UNKNOWN')}",
        f"curated_positions_count={int(summary.get('curated_moltbook_positions_count', 0))}",
        f"runtime_paper_positions_count={int(summary.get('runtime_paper_positions_count', 0))}",
    ]
    divergence_severity = str(summary.get("divergence_severity") or "").strip().upper()
    safe_next_action = str(summary.get("safe_next_action") or "").strip()
    recommended_canonical_source = str(summary.get("recommended_canonical_source") or "").strip()
    if divergence_severity or safe_next_action or recommended_canonical_source:
        lines.append(
            "position_truth_reconciliation="
            f"severity={divergence_severity or 'NONE'}, "
            f"recommended_canonical_source={recommended_canonical_source or 'none'}, "
            f"safe_next_action={safe_next_action or 'none'}"
        )
    lines.append(
        "position_checksums="
        f"canonical={summary.get('canonical_position_checksum')}, "
        f"advisory={summary.get('advisory_position_checksum')}"
    )
    warning = summary.get("position_truth_warning")
    if warning:
        lines.append(f"position_truth_warning={warning}")
    return lines


def resolve_position_integrity_contract(
    summary: dict[str, Any],
    truth_origin: Any = None,
) -> dict[str, Any]:
    """Map a position-truth summary onto the canonical contract states.

    The legacy resolver emits states like CLEAN / DIVERGED /
    MISSING_CANONICAL. This helper translates them into the canonical
    ``PositionIntegrityState`` enum and applies a single critical rule:

        ``MATCHED`` is not enough if truth_origin is seeded/demo.
        In that case the canonical state remains ``UNKNOWN`` because no
        external check has occurred. ``RECONCILED`` requires explicit
        evidence — either a non-seeded truth_origin or a runtime
        ``reconciliation_evidence`` flag on the summary.
    """

    raw_state = str(summary.get("position_integrity_state") or "UNKNOWN").upper()
    severity = str(summary.get("divergence_severity") or "").upper()

    if raw_state == "CLEAN":
        canonical = PositionIntegrityState.MATCHED
    elif raw_state == "DIVERGED":
        canonical = PositionIntegrityState.DIVERGED
    elif raw_state in {"MISSING_CANONICAL", "MISSING_SOURCE"}:
        canonical = PositionIntegrityState.MISSING_SOURCE
    else:
        canonical = coerce_position_state(raw_state)

    truth_origin_enum = coerce_truth_origin(truth_origin)
    has_reconciliation_evidence = bool(summary.get("reconciliation_evidence"))

    rationale_bits: list[str] = []
    if canonical == PositionIntegrityState.MATCHED and truth_origin_enum in {
        TruthOrigin.SEEDED,
        TruthOrigin.DEMO,
    }:
        rationale_bits.append(
            "MATCHED downgraded to UNKNOWN because truth_origin is "
            f"{truth_origin_enum.value} (no external check performed)"
        )
        canonical = PositionIntegrityState.UNKNOWN
    elif canonical == PositionIntegrityState.MATCHED and has_reconciliation_evidence:
        rationale_bits.append(
            "MATCHED + reconciliation_evidence → RECONCILED"
        )
        canonical = PositionIntegrityState.RECONCILED

    if severity in {"CRITICAL", "HIGH"} and canonical not in {
        PositionIntegrityState.DIVERGED,
        PositionIntegrityState.MISSING_SOURCE,
    }:
        rationale_bits.append(
            f"divergence_severity={severity} forces DIVERGED"
        )
        canonical = PositionIntegrityState.DIVERGED

    return {
        "canonical_position_integrity_state": canonical.value,
        "raw_position_integrity_state": raw_state,
        "truth_origin": truth_origin_enum.value,
        "is_clean": canonical
        in {PositionIntegrityState.MATCHED, PositionIntegrityState.RECONCILED},
        "blocks_capital": canonical
        in {
            PositionIntegrityState.DIVERGED,
            PositionIntegrityState.UNKNOWN,
            PositionIntegrityState.MISSING_SOURCE,
            PositionIntegrityState.STALE_SOURCE,
            PositionIntegrityState.QUANTITY_MISMATCH,
            PositionIntegrityState.PRICE_MISMATCH,
        },
        "rationale": "; ".join(rationale_bits) if rationale_bits else "",
    }


__all__ = [
    "DEFAULT_CURATED_PATH",
    "DEFAULT_RUNTIME_PATH",
    "build_position_reconciliation_report",
    "build_position_truth_summary",
    "format_position_truth_summary",
    "get_canonical_position_path",
    "resolve_position_integrity_contract",
]
