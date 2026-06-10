"""Fail when an accepted dependency advisory is past its review date.

docs/DEPENDENCY_ADVISORY_REGISTER.md records advisories CI tolerates
(Moderate and below) with a mandatory ``Review by`` date. This audit
parses the "Open entries" table and exits non-zero when:

  * an entry's review date is in the past (stale accepted risk), or
  * an entry carries High/Critical severity (those must never be
    "accepted" — the hard CI gates handle them), or
  * an entry is missing a parsable date or owner.

Stdlib only:  python scripts/audit_dependency_advisory_register.py
"""
from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REGISTER = _REPO_ROOT / "docs" / "DEPENDENCY_ADVISORY_REGISTER.md"

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_FORBIDDEN_SEVERITIES = ("high", "critical")


def parse_open_entries(text: str) -> list[dict[str, str]]:
    """Parse the markdown table under '## Open entries'."""
    entries: list[dict[str, str]] = []
    in_open = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_open = stripped.lower().startswith("## open entries")
            continue
        if not in_open or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 10 or cells[0] in ("ID", "--") or set(cells[0]) <= {"-", " "}:
            continue
        entries.append(
            {
                "id": cells[0],
                "package": cells[1],
                "severity": cells[2],
                "review_by": cells[8],
                "owner": cells[9],
            }
        )
    return entries


def audit(
    register_path: Path = _REGISTER,
    today: _dt.date | None = None,
) -> list[str]:
    """Return violations (empty = clean)."""
    today = today or _dt.date.today()
    if not register_path.exists():
        return [f"register missing: {register_path}"]
    entries = parse_open_entries(register_path.read_text(encoding="utf-8"))
    violations: list[str] = []
    for entry in entries:
        eid = entry["id"]
        severity = entry["severity"].lower()
        if any(s in severity for s in _FORBIDDEN_SEVERITIES):
            violations.append(
                f"{eid}: severity '{entry['severity']}' may not be accepted — "
                "fix it; the hard CI gates exist for a reason"
            )
        m = _DATE_RE.search(entry["review_by"])
        if not m:
            violations.append(f"{eid}: unparsable review_by date: {entry['review_by']!r}")
            continue
        review_by = _dt.date.fromisoformat(m.group(1))
        if review_by < today:
            violations.append(
                f"{eid}: accepted advisory for {entry['package']} is past its "
                f"review date ({review_by.isoformat()} < {today.isoformat()}) — "
                "re-check upstream for a fix or re-justify and bump review_by"
            )
        if "akash" not in entry["owner"].lower():
            violations.append(f"{eid}: missing accepted-risk owner (got {entry['owner']!r})")
    return violations


def main() -> int:
    violations = audit()
    entries = parse_open_entries(_REGISTER.read_text(encoding="utf-8")) if _REGISTER.exists() else []
    print(f"dependency advisory register audit: {len(entries)} open entr(y/ies)")
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — all accepted advisories within their review window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
