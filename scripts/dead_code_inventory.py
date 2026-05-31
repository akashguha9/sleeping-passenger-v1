"""Real Evidence Sprint — Phase 7: safe dead-code / maintainability inventory.

READ-ONLY static analysis.  It NEVER deletes, moves, or edits any file — it
produces a *map* and a quarantine *plan* so a human can decide what (if
anything) to remove later.

It surfaces, conservatively:
  * scripts not imported by any other script/test (unreferenced candidates),
  * legacy / quarantine files (under ``_legacy_layers`` / ``_quarantine``),
  * modules with no obvious test coverage,
  * modules whose names are metaphor/archetype-only (candidate for renaming),
  * runtime-artifact path patterns that should remain untracked.

Everything is reported as a *candidate*, never an instruction to delete.  Entry
points (``run_*``, ``*_server``, CLIs) and dunder files are excluded from the
"unreferenced" list because they are invoked, not imported.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

try:  # package layout
    from scripts.runtime_common import REPO_ROOT
except ModuleNotFoundError:  # pragma: no cover - flat-layout fallback
    REPO_ROOT = Path(__file__).resolve().parents[1]

_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?:scripts\.)?([A-Za-z0-9_\.]+)\s+import|import\s+(?:scripts\.)?([A-Za-z0-9_\.]+))",
    re.MULTILINE,
)

# Files that are invoked (CLIs / entry points), not imported — never flagged as
# unreferenced.
_ENTRYPOINT_RE = re.compile(r"(^run_|_server$|^api_|^smoke_|^bootstrap_|^start_|^backup_|^restore_)")

# Metaphor / archetype name markers — candidates for a plainer name (advisory).
_METAPHOR_MARKERS = (
    "archetype", "baines", "bruce_lee", "busquets", "gallardo", "kante",
    "tennis", "chess", "reactor", "meltdown", "moltbook", "buoyancy",
    "metabolism", "geometry", "tribe", "kronos", "kante",
)

# Runtime-artifact path patterns that must stay untracked.
_RUNTIME_ARTIFACT_PATTERNS = [
    "runtime/",
    "runtime/*.db",
    "logs/",
    "*.db",
    "data/daily_payload_backup_*/",
    "data/daily_payload/*.json",
    "tests/_tmp_runtime/",
]


def _module_stems(scripts_dir: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(scripts_dir.glob("*.py")):
        if p.name.startswith("__"):
            continue
        out.append(p.stem)
    return out


def _collect_referenced(roots: list[Path]) -> set[str]:
    referenced: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath:
                continue
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                try:
                    text = (Path(dirpath) / fn).read_text(encoding="utf-8", errors="ignore")
                except OSError:  # pragma: no cover - defensive
                    continue
                for m in _IMPORT_RE.finditer(text):
                    mod = m.group(1) or m.group(2) or ""
                    # last dotted component is the module name
                    stem = mod.split(".")[-1].strip()
                    if stem:
                        referenced.add(stem)
    return referenced


def build_inventory(repo_root: str | Path | None = None) -> dict[str, Any]:
    """Build the read-only dead-code / maintainability inventory."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    scripts_dir = root / "scripts"
    tests_dir = root / "tests"

    stems = _module_stems(scripts_dir)
    referenced_anywhere = _collect_referenced([scripts_dir, tests_dir])
    referenced_in_tests = _collect_referenced([tests_dir])

    unreferenced: list[str] = []
    no_tests: list[str] = []
    metaphor_labeled: list[str] = []
    for stem in stems:
        is_entrypoint = bool(_ENTRYPOINT_RE.search(stem))
        if stem not in referenced_anywhere and not is_entrypoint:
            unreferenced.append(stem)
        if stem not in referenced_in_tests and not is_entrypoint:
            no_tests.append(stem)
        if any(mark in stem for mark in _METAPHOR_MARKERS):
            metaphor_labeled.append(stem)

    # Legacy / quarantine files (never auto-removed).
    legacy_quarantine: list[str] = []
    for sub in ("_legacy_layers", "_quarantine"):
        d = scripts_dir / sub
        if d.exists():
            for dirpath, _dirs, files in os.walk(d):
                for fn in files:
                    rel = (Path(dirpath) / fn).relative_to(root)
                    legacy_quarantine.append(str(rel).replace(os.sep, "/"))

    return {
        "repo_root": str(root),
        "n_scripts": len(stems),
        "unreferenced_candidates": sorted(unreferenced),
        "n_unreferenced_candidates": len(unreferenced),
        "modules_without_tests": sorted(no_tests),
        "n_modules_without_tests": len(no_tests),
        "metaphor_labeled_modules": sorted(metaphor_labeled),
        "n_metaphor_labeled": len(metaphor_labeled),
        "legacy_quarantine_files": sorted(legacy_quarantine),
        "n_legacy_quarantine": len(legacy_quarantine),
        "runtime_artifact_patterns": list(_RUNTIME_ARTIFACT_PATTERNS),
        "deletes_files": False,
        "note": (
            "READ-ONLY. All entries are candidates for human review, NOT "
            "deletion instructions. Entry points (run_*, *_server, CLIs) are "
            "excluded from unreferenced lists because they are invoked, not "
            "imported."
        ),
        "advisory_status": "ADVISORY_ONLY",
        "execution_gate": "LOCKED",
    }


def render_markdown(inv: dict[str, Any]) -> str:
    def _list(items: list[str], cap: int = 60) -> str:
        if not items:
            return "_(none)_"
        shown = items[:cap]
        extra = "" if len(items) <= cap else f"\n- … and {len(items) - cap} more"
        return "\n".join(f"- `{x}`" for x in shown) + extra

    lines = [
        "# Dead-Code & Maintainability Audit — sleeping-passenger-v1",
        "",
        "> READ-ONLY map. Nothing here is deleted automatically. Every entry is a "
        "**candidate for human review**, not a deletion instruction.",
        "",
        f"- Scripts scanned: **{inv['n_scripts']}**",
        f"- Unreferenced candidates: **{inv['n_unreferenced_candidates']}**",
        f"- Modules without obvious tests: **{inv['n_modules_without_tests']}**",
        f"- Metaphor/archetype-named modules: **{inv['n_metaphor_labeled']}**",
        f"- Legacy/quarantine files: **{inv['n_legacy_quarantine']}**",
        "",
        "## Runtime-artifact patterns (keep untracked)",
        "",
        "```",
        *inv["runtime_artifact_patterns"],
        "```",
        "",
        "## Unreferenced module candidates",
        "",
        "Not imported by any other script or test (excludes CLI entry points). "
        "Review before any action — some may be reflective/CLI tools.",
        "",
        _list(inv["unreferenced_candidates"]),
        "",
        "## Modules without obvious test coverage",
        "",
        _list(inv["modules_without_tests"]),
        "",
        "## Metaphor / archetype-named modules (rename candidates)",
        "",
        _list(inv["metaphor_labeled_modules"]),
        "",
        "## Legacy / quarantine files",
        "",
        _list(inv["legacy_quarantine_files"]),
        "",
        "## Quarantine plan (safe, human-driven)",
        "",
        "1. Confirm a candidate is truly unused (grep + run full suite).",
        "2. Move — do not delete — to `scripts/_quarantine/` in a dedicated PR.",
        "3. Run the full test suite; if green, keep quarantined one release.",
        "4. Delete only after a release with no regression and explicit sign-off.",
        "",
    ]
    return "\n".join(lines)


def write_report(inv: dict[str, Any], path: str | Path | None = None) -> str:
    target = Path(path) if path is not None else (REPO_ROOT / "docs" / "DEAD_CODE_AUDIT.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(inv), encoding="utf-8")
    return str(target)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse
    import json

    p = argparse.ArgumentParser(description="Read-only dead-code inventory (never deletes).")
    p.add_argument("--write", action="store_true")
    args = p.parse_args(argv)

    inv = build_inventory()
    if args.write:
        inv["report_path"] = write_report(inv)
    print(json.dumps({
        "n_scripts": inv["n_scripts"],
        "n_unreferenced_candidates": inv["n_unreferenced_candidates"],
        "n_modules_without_tests": inv["n_modules_without_tests"],
        "n_legacy_quarantine": inv["n_legacy_quarantine"],
        "deletes_files": inv["deletes_files"],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    raise SystemExit(main(sys.argv[1:]))


__all__ = ["build_inventory", "render_markdown", "write_report", "main"]
