"""Static dead-weight census for ``scripts/`` modules.

Import-safe: importing this module has no side effects; all work happens in
the functions below or under ``__main__``. It does NOT import any repo module
(pure AST analysis on file text), so it cannot perturb runtime/governance.

Tiers (mutually exclusive, assigned in this precedence order):
  ACTIVE      - reachable by import-BFS from scripts/run_diagnostics_pipeline.py
  API_REACHED - reachable from scripts/api_server.py but NOT ACTIVE
  TEST_ONLY   - neither of the above, but imported by >= 1 file under tests/
  ORPHAN      - reachable from no entrypoint and no test

Reachability follows imports into subpackages too, but only top-level
``scripts/*.py`` modules are classified (that is the 320-module population).
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = REPO_ROOT / "tests"

ORCHESTRATOR = "run_diagnostics_pipeline"
API_ENTRY = "api_server"


def _top_level_modules() -> list[str]:
    return sorted(p.stem for p in SCRIPTS_DIR.glob("*.py"))


def _resolve_to_scripts_file(module_parts: list[str]) -> Path | None:
    """Resolve a dotted module path to a file under scripts/, or None.

    Accepts both ``scripts.foo.bar`` and bare ``foo.bar`` forms (the repo uses
    a try/except fallback that imports both ways).
    """
    parts = list(module_parts)
    if parts and parts[0] == "scripts":
        parts = parts[1:]
    if not parts:
        return None
    base = SCRIPTS_DIR.joinpath(*parts)
    candidate = base.with_suffix(".py")
    if candidate.exists():
        return candidate
    init = base / "__init__.py"
    if init.exists():
        return init
    return None


def _imports_from_file(path: Path) -> set[Path]:
    """Return scripts/ files imported by ``path`` (top-level + subpackage)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return set()
    edges: set[Path] = set()
    pkg_dir = path.parent
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                resolved = _resolve_to_scripts_file(alias.name.split("."))
                if resolved is not None:
                    edges.add(resolved)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                # relative import: resolve against the containing package
                anchor = pkg_dir
                for _ in range(node.level - 1):
                    anchor = anchor.parent
                tail = node.module.split(".") if node.module else []
                try:
                    rel = anchor.joinpath(*tail).relative_to(SCRIPTS_DIR)
                except ValueError:
                    continue
                resolved = _resolve_to_scripts_file(list(rel.parts))
                if resolved is not None:
                    edges.add(resolved)
            elif node.module:
                resolved = _resolve_to_scripts_file(node.module.split("."))
                if resolved is not None:
                    edges.add(resolved)
    return edges


def _bfs(seed_stem: str) -> set[Path]:
    seed = SCRIPTS_DIR / f"{seed_stem}.py"
    seen: set[Path] = set()
    frontier = {seed}
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for nxt in _imports_from_file(cur):
            if nxt not in seen:
                frontier.add(nxt)
    return seen


def _top_level_reached(reached_files: set[Path]) -> set[str]:
    out = set()
    for f in reached_files:
        try:
            rel = f.relative_to(SCRIPTS_DIR)
        except ValueError:
            continue
        if len(rel.parts) == 1 and rel.suffix == ".py":
            out.add(rel.stem)
    return out


def _modules_referenced_by_tests() -> set[str]:
    referenced: set[str] = set()
    tops = set(_top_level_modules())
    for path in TESTS_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "scripts" and len(parts) >= 2 and parts[1] in tops:
                        referenced.add(parts[1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] == "scripts" and len(parts) >= 2 and parts[1] in tops:
                    referenced.add(parts[1])
                elif parts[0] == "scripts" and len(parts) == 1:
                    # `from scripts import foo, bar` — the modules are names.
                    for alias in node.names:
                        if alias.name in tops:
                            referenced.add(alias.name)
                elif parts[0] in tops:
                    referenced.add(parts[0])
    return referenced


def _line_count(stem: str) -> int:
    return len((SCRIPTS_DIR / f"{stem}.py").read_text(encoding="utf-8-sig").splitlines())


def _has_dedicated_test(stem: str) -> bool:
    return (TESTS_DIR / f"test_{stem}.py").exists()


def compute_active_set() -> set[str]:
    return _top_level_reached(_bfs(ORCHESTRATOR))


def compute_census() -> dict:
    tops = _top_level_modules()
    active = compute_active_set()
    api = _top_level_reached(_bfs(API_ENTRY)) - active
    test_refs = _modules_referenced_by_tests()
    rows = {}
    for stem in tops:
        if stem in active:
            tier = "ACTIVE"
        elif stem in api:
            tier = "API_REACHED"
        elif stem in test_refs:
            tier = "TEST_ONLY"
        else:
            tier = "ORPHAN"
        edges = sorted(
            _top_level_reached(_imports_from_file(SCRIPTS_DIR / f"{stem}.py"))
            - {stem}
        )
        rows[stem] = {
            "tier": tier,
            "lines": _line_count(stem),
            "has_test": _has_dedicated_test(stem),
            "imports_scripts": edges,
        }
    counts = {t: sum(1 for r in rows.values() if r["tier"] == t)
              for t in ("ACTIVE", "API_REACHED", "TEST_ONLY", "ORPHAN")}
    return {"total": len(tops), "counts": counts, "modules": rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scripts/ module dead-weight census")
    parser.add_argument("--json", action="store_true", help="Emit full JSON census.")
    args = parser.parse_args(argv)
    census = compute_census()
    if args.json:
        print(json.dumps(census, indent=2))
    else:
        print(f"total={census['total']}")
        for tier, n in census["counts"].items():
            print(f"{tier}={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
