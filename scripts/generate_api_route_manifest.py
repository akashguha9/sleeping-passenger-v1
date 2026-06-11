"""API surface manifest — every HTTP endpoint is enumerated and frozen.

The advisory-only boundary audit checks route *semantics* (no /execute,
/buy, /sell, order placement). This manifest closes the complement: route
*completeness*. ``config/api_route_manifest.json`` is the committed,
reviewed list of every method+path the FastAPI app exposes;
``tests/test_api_route_manifest.py`` fails the suite the moment the live
surface differs in either direction. A "hidden webhook" or any quietly
added endpoint is therefore impossible to land without a visible,
reviewable manifest diff in the same commit — and that diff re-triggers
the semantics audit and human review.

Usage:
    python scripts/generate_api_route_manifest.py          # diff (exit 1 on drift)
    python scripts/generate_api_route_manifest.py --write  # accept new surface

``--write`` is the deliberate review event: run it only after reading the
diff and confirming the new surface is advisory-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = _REPO_ROOT / "config" / "api_route_manifest.json"

if str(_REPO_ROOT) not in sys.path:  # script-style invocation
    sys.path.insert(0, str(_REPO_ROOT))


def live_surface() -> list[dict[str, str]]:
    """Enumerate the live FastAPI surface as sorted {method, path} rows."""
    from scripts import api_server

    rows: list[dict[str, str]] = []
    for route in api_server.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue  # mounts/websockets/static — none exist today
        for method in sorted(m for m in methods if m != "HEAD"):
            rows.append({"method": method, "path": path})
    return sorted(rows, key=lambda r: (r["path"], r["method"]))


def load_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["routes"]


def diff_surface(
    manifest: list[dict[str, str]], live: list[dict[str, str]]
) -> dict[str, list[str]]:
    """Pure diff: {'added': [...], 'removed': [...]} (empty = in sync)."""
    fmt = lambda r: f"{r['method']} {r['path']}"  # noqa: E731
    manifest_set = {fmt(r) for r in manifest}
    live_set = {fmt(r) for r in live}
    return {
        "added": sorted(live_set - manifest_set),
        "removed": sorted(manifest_set - live_set),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write", action="store_true",
        help="accept the current live surface into the manifest "
             "(a review event — read the diff first)",
    )
    args = parser.parse_args(argv)

    live = live_surface()
    if args.write:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "policy": (
                        "Committed enumeration of every HTTP endpoint. Any "
                        "surface change requires regenerating this file in "
                        "the same commit (--write) and passes through the "
                        "advisory-only boundary audit + human review. "
                        "Advisory-only: no execution endpoints, ever."
                    ),
                    "route_count": len(live),
                    "routes": live,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {MANIFEST_PATH} ({len(live)} routes)")
        return 0

    if not MANIFEST_PATH.exists():
        print(f"FAIL — manifest missing: {MANIFEST_PATH} (run with --write)")
        return 1
    drift = diff_surface(load_manifest(), live)
    print(f"api route manifest check: {len(live)} live routes")
    if drift["added"] or drift["removed"]:
        print("FAIL — API surface drifted from the committed manifest:")
        for r in drift["added"]:
            print(f"  + {r}  (new, unreviewed endpoint)")
        for r in drift["removed"]:
            print(f"  - {r}  (vanished endpoint)")
        print("If intentional: review, then regenerate with --write.")
        return 1
    print("PASS — live API surface matches the committed manifest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
