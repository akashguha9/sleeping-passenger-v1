"""Dead-diagnostic / maintainability audit (Maintainability — Task 10).

Complements :mod:`scripts.architecture_fitness` (which owns the import-graph
*boundary* checks) by answering a different maintainability question: **which
scripts are dead weight or unguarded?**  For every module under ``scripts/`` it
reports whether the module is

* **tested** — a ``tests/test_<name>.py`` exists *or* the module is referenced
  by some test;
* **imported** — referenced by another ``scripts/`` or ``src/`` module;
* **runnable** — exposes a ``main()`` / ``__main__`` CLI entrypoint;
* **advisory-stamped** — report-producing modules (``build_report`` /
  ``build_audit`` / ``evaluate``) must carry the advisory safety vocabulary.

A module that is none of tested/imported/runnable is an **orphan** (dead code).
A report producer with no advisory stamp is an **unstamped diagnostic**.  The
audit also scans for a forbidden broker/execution *call* pattern (``place_order(``
etc.) — distinct from architecture_fitness's import check — while excluding the
safety modules that legitimately *enumerate* those tokens.

    DiagnosticUsefulnessScore = UsefulScripts / max(TotalScripts, 1)

Read-only: parses source text, never imports the modules under test; no broker
calls, no execution.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from scripts import advisory_contract as _contract
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import advisory_contract as _contract  # type: ignore[no-redef]

try:
    from scripts import architecture_fitness as _arch
except ModuleNotFoundError:  # pragma: no cover - script-style fallback
    import architecture_fitness as _arch  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEAN, WARN, BLOCK = "CLEAN", "WARN", "BLOCK"

# Advisory-stamp evidence tokens.
_ADVISORY_TOKENS = (
    "advisory_contract", "advisory_safety_stamps", "execution_lock_stamp",
    "ADVISORY_ONLY", "advisory_status",
)
# Report-producer signatures — only these modules are *expected* to be stamped.
_REPORT_SIGNATURES = ("def build_report", "def build_audit", "def evaluate(")

# Forbidden broker/execution call tokens (identifier style → call pattern).
_BROKER_CALL_TOKENS = (
    "place_order", "submit_order", "execute_trade", "broker_execute",
    "auto_execute",
)
# Modules that legitimately reference the forbidden tokens (they define/scan the
# forbidden list); excluded from the broker-call offender check.
_BROKER_TOKEN_ALLOWLIST = frozenset({
    "advisory_contract.py", "dead_diagnostic_audit.py", "architecture_fitness.py",
    "compliance_preflight.py", "private_scope_guard.py",
})

_EXCLUDE_NAMES = frozenset({"__init__.py"})


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:  # pragma: no cover
        return ""


def _normalize_module_name(target: str) -> str:
    """Reduce an import target to a bare ``scripts/`` module stem."""
    t = target[len("scripts."):] if target.startswith("scripts.") else target
    return t.split(".")[0]


def _referenced_modules(py_files: list[Path], *, exclude: Path | None = None) -> set[str]:
    names: set[str] = set()
    for path in py_files:
        if exclude is not None and path == exclude:
            continue
        for target in _arch.import_targets(_read(path)):
            names.add(_normalize_module_name(target))
    return names


def _broker_call_offenders(scripts_dir: Path) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {}
    patterns = {tok: re.compile(rf"(?<![\w.])(?:\w+\.)?{re.escape(tok)}\s*\(")
                for tok in _BROKER_CALL_TOKENS}
    for path in sorted(scripts_dir.glob("*.py")):
        if path.name in _BROKER_TOKEN_ALLOWLIST:
            continue
        text = _read(path)
        hits = [tok for tok, pat in patterns.items() if pat.search(text)]
        if hits:
            offenders[path.name] = sorted(hits)
    return offenders


def evaluate(repo_root: Path | None = None) -> dict[str, Any]:
    """Audit ``scripts/`` for orphan/untested/unstamped modules + broker calls."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    scripts_dir = root / "scripts"
    tests_dir = root / "tests"
    src_dir = root / "src"

    scripts = [p for p in sorted(scripts_dir.glob("*.py"))
               if p.name not in _EXCLUDE_NAMES]
    test_files = sorted(tests_dir.glob("*.py")) if tests_dir.exists() else []
    code_files = scripts + (sorted(src_dir.rglob("*.py")) if src_dir.exists() else [])

    test_referenced = _referenced_modules(test_files)
    # imports across the code base, ignoring each module's self-reference
    code_imported: set[str] = set()
    for path in code_files:
        for target in _arch.import_targets(_read(path)):
            name = _normalize_module_name(target)
            if name != path.stem:
                code_imported.add(name)

    modules: list[dict[str, Any]] = []
    orphans: list[str] = []
    untested: list[str] = []
    unstamped: list[str] = []

    for path in scripts:
        name = path.stem
        text = _read(path)
        has_test = (tests_dir / f"test_{name}.py").exists() or name in test_referenced
        is_imported = name in code_imported
        has_main = "__main__" in text or "def main(" in text
        has_advisory = any(tok in text for tok in _ADVISORY_TOKENS)
        is_report = any(sig in text for sig in _REPORT_SIGNATURES)

        useful = has_test or is_imported or has_main
        if not useful:
            orphans.append(path.name)
        if not has_test:
            untested.append(path.name)
        if is_report and not has_advisory:
            unstamped.append(path.name)

        modules.append({
            "module": path.name,
            "has_test": has_test,
            "is_imported": is_imported,
            "has_main": has_main,
            "advisory_stamped": has_advisory,
            "is_report_producer": is_report,
            "useful": useful,
        })

    total = len(scripts)
    useful_count = sum(1 for m in modules if m["useful"])
    usefulness = round(useful_count / max(total, 1), 4)
    broker_offenders = _broker_call_offenders(scripts_dir)

    if broker_offenders:
        impact = BLOCK
    elif orphans or unstamped:
        impact = WARN
    else:
        impact = CLEAN

    return {
        "report": "dead_diagnostic_audit",
        "repo_root": str(root),
        "total_scripts": total,
        "useful_scripts": useful_count,
        "diagnostic_usefulness_score": usefulness,
        "orphan_scripts": orphans,
        "untested_scripts": untested,
        "unstamped_report_producers": unstamped,
        "broker_call_offenders": broker_offenders,
        "release_gate_impact": impact,
        "modules": modules,
        **_contract.advisory_safety_stamps(),
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dead_diagnostic_audit.py",
        description=(
            "Find orphan/untested/unstamped scripts + forbidden broker call "
            "patterns. Read-only; never a broker call."
        ),
    )
    p.add_argument("--repo-root", type=Path, default=None)
    p.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = evaluate(args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("Dead-Diagnostic / Maintainability Audit (advisory-only)")
        print("=======================================================")
        print(f"  total scripts            : {report['total_scripts']}")
        print(f"  usefulness score         : {report['diagnostic_usefulness_score']}")
        print(f"  orphan scripts           : {len(report['orphan_scripts'])}")
        print(f"  untested scripts         : {len(report['untested_scripts'])}")
        print(f"  unstamped report producers: {len(report['unstamped_report_producers'])}")
        print(f"  broker call offenders    : {report['broker_call_offenders']}")
        print(f"  release gate impact      : {report['release_gate_impact']}")
        if report["orphan_scripts"]:
            print(f"  orphans: {report['orphan_scripts']}")
        if report["unstamped_report_producers"]:
            print(f"  unstamped: {report['unstamped_report_producers']}")
    return 0 if report["release_gate_impact"] != BLOCK else 1


__all__ = ["evaluate"]


if __name__ == "__main__":
    raise SystemExit(main())
