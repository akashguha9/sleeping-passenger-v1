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

import json
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.runtime_common import REPO_ROOT, repo_relative
except ModuleNotFoundError:  # pragma: no cover
    from runtime_common import REPO_ROOT, repo_relative


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

    if not curated_present and not runtime_present:
        canonical = "none"
        warning = (
            "Neither moltbook/open_positions.json nor runtime/paper_positions.json "
            "exists; there is no active position truth in this checkout."
        )
        divergence = False
    elif curated_present and not runtime_present:
        canonical = "curated_moltbook"
        warning = (
            "Only curated moltbook/open_positions.json exists. The runtime "
            "paper-position ledger has not been created."
        )
        divergence = False
    elif runtime_present and not curated_present:
        canonical = "runtime_paper"
        warning = (
            "Only runtime/paper_positions.json exists. The curated moltbook "
            "position fixture is absent from this checkout."
        )
        divergence = False
    else:
        # Both exist. Canonical source for diagnostics remains the curated
        # fixture (that is what action_engine reads). We report divergence
        # whenever the two disagree by symbol OR by count, without
        # suppressing either side.
        divergence = bool(missing_from_runtime) or bool(missing_from_curated) or (
            curated_count != runtime_count
        )
        canonical = "curated_moltbook"
        if divergence:
            warning = (
                "Position sources diverge: curated moltbook and runtime paper "
                "ledgers disagree on symbols or counts. Neither file was "
                "modified; this summary is visibility-only."
            )
        else:
            warning = None

    return {
        "position_truth_source": canonical,
        "canonical_position_source": canonical,
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
        "position_truth_warning": warning,
    }


def format_position_truth_summary(summary: dict[str, Any]) -> list[str]:
    """Shape the summary as the four summary lines diagnostics surface."""
    lines = [
        f"position_truth_source={summary.get('canonical_position_source', 'none')}",
        (
            "position_source_divergence_detected="
            f"{str(bool(summary.get('position_source_divergence_detected'))).lower()}"
        ),
        f"curated_positions_count={int(summary.get('curated_moltbook_positions_count', 0))}",
        f"runtime_paper_positions_count={int(summary.get('runtime_paper_positions_count', 0))}",
    ]
    warning = summary.get("position_truth_warning")
    if warning:
        lines.append(f"position_truth_warning={warning}")
    return lines


__all__ = [
    "DEFAULT_CURATED_PATH",
    "DEFAULT_RUNTIME_PATH",
    "build_position_truth_summary",
    "format_position_truth_summary",
]
