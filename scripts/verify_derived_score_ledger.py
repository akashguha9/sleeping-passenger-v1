"""Verify the derived score ledger chain + contract (Pass 6).

Usage:  python scripts/verify_derived_score_ledger.py [--path <jsonl>]
Exit 1 on tamper, broken chain, execution-shaped fields, missing
advisory/human-review stamps, or evidence-free scores not marked
NO_EVIDENCE_ABSTAIN.
"""
from __future__ import annotations

import argparse
from pathlib import Path

try:
    from scripts.derived_score_ledger import ledger_path, verify_chain
except ModuleNotFoundError:  # pragma: no cover - script-style env
    from derived_score_ledger import ledger_path, verify_chain  # type: ignore[no-redef]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=None)
    args = parser.parse_args(argv)
    target = Path(args.path) if args.path else ledger_path()
    result = verify_chain(target)
    print(f"derived score ledger: {target}")
    print(f"  records: {result['records']}")
    if result["valid"]:
        print("PASS — chain intact, contract satisfied.")
        return 0
    print(f"FAIL — {len(result['errors'])} error(s):")
    for e in result["errors"]:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
