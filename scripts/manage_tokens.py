#!/usr/bin/env python3
"""S4-A3: local API-token management CLI.

    python scripts/manage_tokens.py create --role OPERATOR --name akash-local
    python scripts/manage_tokens.py list
    python scripts/manage_tokens.py revoke --id <token_id>
    python scripts/manage_tokens.py rotate --id <token_id>

The plaintext token is printed ONCE at create/rotate and never stored —
only its HMAC-SHA256 hash lives in the database.  Advisory-only tooling:
no broker, no execution.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.token_registry import (  # noqa: E402
    ROLES,
    create_token,
    list_tokens,
    revoke_token,
    rotate_token,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create")
    p_create.add_argument("--role", required=True, choices=list(ROLES))
    p_create.add_argument("--name", required=True)

    sub.add_parser("list")

    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("--id", required=True, dest="token_id")

    p_rotate = sub.add_parser("rotate")
    p_rotate.add_argument("--id", required=True, dest="token_id")

    args = parser.parse_args(argv)

    if args.command == "create":
        out = create_token(args.name, args.role)
        print(f"token_id: {out['token_id']}  role: {out['role']}  name: {out['name']}")
        print("PLAINTEXT TOKEN (shown once, store it now):")
        print(out["plaintext_token_shown_once"])
        return 0
    if args.command == "list":
        for t in list_tokens():
            status = "REVOKED" if t["revoked_at"] else "active"
            print(
                f"{t['token_id']}  {t['role']:<8} {status:<8} "
                f"name={t['name']} created={t['created_at']}"
            )
        return 0
    if args.command == "revoke":
        ok = revoke_token(args.token_id)
        print("revoked" if ok else "not found / already revoked")
        return 0 if ok else 2
    if args.command == "rotate":
        out = rotate_token(args.token_id)
        if out is None:
            print("not found / revoked")
            return 2
        print("PLAINTEXT TOKEN (shown once — the old token is now invalid):")
        print(out["plaintext_token_shown_once"])
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
