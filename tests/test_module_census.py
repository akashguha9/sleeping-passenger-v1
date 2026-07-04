"""Gate the ACTIVE runtime set from silently growing.

Recomputes the ACTIVE module set (import-BFS from
``scripts/run_diagnostics_pipeline.py``) and asserts it stays at or below
today's pinned ceiling. Any future PR that pulls a new module onto the active
diagnostics path will fail this test, forcing a conscious decision (and an
update to both this ceiling and ``docs/module_census.md``).

Self-contained: the BFS is implemented here (no fixtures, no conftest, no
import of repo runtime modules — pure AST over file text).
"""

import ast
from pathlib import Path

# Pinned ceiling = current ACTIVE count (today's number + 0). See
# docs/module_census.md. Raising this is a deliberate act, not an accident.
# 70 -> 80 (2026-07-04, Close-the-Loop sprint): the action engine and signal
# refinery now import the canonical holdings gate (scripts/holdings_truth_gate)
# and its dependency closure — the forensic audit's SP-001 fix deliberately
# pulls the risk-truth path onto the diagnostics pipeline.
ACTIVE_CEILING = 80

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
ORCHESTRATOR = "run_diagnostics_pipeline"


def _resolve(parts: list[str]) -> Path | None:
    parts = list(parts)
    if parts and parts[0] == "scripts":
        parts = parts[1:]
    if not parts:
        return None
    base = SCRIPTS_DIR.joinpath(*parts)
    candidate = base.with_suffix(".py")
    if candidate.exists():
        return candidate
    init = base / "__init__.py"
    return init if init.exists() else None


def _edges(path: Path) -> set[Path]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return set()
    out: set[Path] = set()
    pkg_dir = path.parent
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve(alias.name.split("."))
                if resolved is not None:
                    out.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                anchor = pkg_dir
                for _ in range(node.level - 1):
                    anchor = anchor.parent
                tail = node.module.split(".") if node.module else []
                try:
                    rel = anchor.joinpath(*tail).relative_to(SCRIPTS_DIR)
                except ValueError:
                    continue
                resolved = _resolve(list(rel.parts))
                if resolved is not None:
                    out.add(resolved)
            elif node.module:
                resolved = _resolve(node.module.split("."))
                if resolved is not None:
                    out.add(resolved)
    return out


def _active_set() -> set[str]:
    seen: set[Path] = set()
    frontier = {SCRIPTS_DIR / f"{ORCHESTRATOR}.py"}
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier |= _edges(cur) - seen
    top_level = set()
    for f in seen:
        rel = f.relative_to(SCRIPTS_DIR)
        if len(rel.parts) == 1 and rel.suffix == ".py":
            top_level.add(rel.stem)
    return top_level


def test_active_module_set_does_not_exceed_ceiling() -> None:
    active = _active_set()

    # Sanity: the BFS actually traversed (guards against a silently-empty set
    # passing the ceiling check).
    assert ORCHESTRATOR in active
    assert {"pipeline_health_report", "action_engine", "runtime_common"} <= active

    assert len(active) <= ACTIVE_CEILING, (
        f"ACTIVE runtime set grew to {len(active)} (ceiling {ACTIVE_CEILING}). "
        "A new module was pulled onto the run_diagnostics_pipeline path. "
        "If intended, bump ACTIVE_CEILING and update docs/module_census.md."
    )
