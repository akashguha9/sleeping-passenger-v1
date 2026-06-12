#!/usr/bin/env python3
"""Live Surface Census — which code can actually touch the user.

Two audits in a row misclassified ``src/scoring`` as dead code because
the repo had no authoritative map of WHICH ``src/`` modules are
reachable from WHICH entry lane. This census computes that map from
real imports (AST, no heuristics) and is pinned by
``tests/test_live_surface.py``:

* **api_lane** — transitively imported by ``scripts/api_server.py``:
  the only code that can influence a number shown to the operator
  through the API.
* **batch_lane** — transitively imported by the documented standalone
  CLIs (``run_scoring`` / ``run_paper_trading`` / ``run_ingestion`` /
  ``run_dashboard``; see README "Run scoring") but NOT by the API.
* **unreachable** — imported by neither lane. New modules may not land
  here silently: the guard test pins this set exactly, so dead code
  cannot regrow unnoticed and "tested but unreachable" can never again
  masquerade as live coverage.

Usage:
    python scripts/live_surface_census.py            # human summary
    python scripts/live_surface_census.py --json     # machine output

ADVISORY_ONLY repo; this tool reads source files and never mutates.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

API_ROOTS = ("scripts.api_server",)
BATCH_ROOTS = (
    "scripts.run_scoring",
    "scripts.run_paper_trading",
    "scripts.run_ingestion",
    "scripts.run_dashboard",
    "scripts.run_live_refresh",
    # The API surfaces "python scripts/refresh_live_signals.py --write"
    # as the operator command; phase1 runner pulls the live-source chain.
    "scripts.refresh_live_signals",
    "scripts.run_live_sources_phase1",
    "scripts.kalshi_live_smoke",  # documented live-source probe
    "scripts.import_outcomes",    # calibration ledger import CLI
    # Launched via `streamlit run`, a string command — declared here
    # because no static import can see it.
    "src.dashboard.streamlit_app",
)


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(REPO).with_suffix("").parts)


def _module_path(name: str) -> Path | None:
    base = REPO / Path(*name.split("."))
    if base.with_suffix(".py").exists():
        return base.with_suffix(".py")
    if (base / "__init__.py").exists():
        return base / "__init__.py"
    return None


def _local_imports(path: Path) -> set[str]:
    """First-party imports (src.* / scripts.*) declared in one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except (SyntaxError, OSError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ("src", "scripts"):
                    found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            if module.split(".")[0] in ("src", "scripts"):
                found.add(module)
                # `from scripts import x, y` style: each name may be a
                # module in its own right.
                for alias in node.names:
                    found.add(f"{module}.{alias.name}")
    return found


def _closure(roots: tuple[str, ...]) -> set[str]:
    """Transitive first-party import closure from the given roots."""
    seen: set[str] = set()
    queue = [r for r in roots if _module_path(r) is not None]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        path = _module_path(name)
        if path is None:
            continue
        seen.add(name)
        if path.name == "__init__.py" and not name.endswith("__init__"):
            seen.add(f"{name}.__init__")
        # Importing src.a.b implicitly executes src/a/__init__.py —
        # mark package __init__ ancestors reachable too.
        parts = name.split(".")
        for depth in range(1, len(parts)):
            if _module_path(".".join(parts[:depth])) is not None:
                seen.add(".".join(parts[:depth]) + ".__init__")
        for imported in _local_imports(path):
            # Normalize `pkg.sub.attr` down to a real module if `attr`
            # is not itself a module.
            candidate = imported
            while candidate and _module_path(candidate) is None:
                candidate = ".".join(candidate.split(".")[:-1])
            if candidate and candidate not in seen:
                queue.append(candidate)
    return seen


def _all_src_modules() -> set[str]:
    return {
        _module_name(p)
        for p in (REPO / "src").rglob("*.py")
        if "__pycache__" not in p.parts
    }


def build_census() -> dict[str, object]:
    api_closure = _closure(API_ROOTS)
    batch_closure = _closure(BATCH_ROOTS)
    src_modules = _all_src_modules()

    api_lane = sorted(m for m in src_modules if m in api_closure)
    batch_lane = sorted(
        m for m in src_modules
        if m in batch_closure and m not in api_closure
    )
    unreachable = sorted(
        m for m in src_modules
        if m not in api_closure and m not in batch_closure
    )
    return {
        "api_roots": list(API_ROOTS),
        "batch_roots": list(BATCH_ROOTS),
        "src_module_count": len(src_modules),
        "api_lane": api_lane,
        "batch_lane": batch_lane,
        "unreachable": unreachable,
        "api_lane_count": len(api_lane),
        "batch_lane_count": len(batch_lane),
        "unreachable_count": len(unreachable),
    }


def main(argv: list[str]) -> int:
    census = build_census()
    if "--json" in argv:
        print(json.dumps(census, indent=2))
        return 0
    print("Live Surface Census (src/)")
    print(f"  api_lane     : {census['api_lane_count']} module(s) — can "
          "influence user-facing output")
    print(f"  batch_lane   : {census['batch_lane_count']} module(s) — "
          "documented standalone CLIs only")
    print(f"  unreachable  : {census['unreachable_count']} module(s)")
    for name in census["unreachable"]:
        print(f"    - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
