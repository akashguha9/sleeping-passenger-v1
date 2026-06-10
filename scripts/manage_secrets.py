"""Operator CLI for provider-key custody (scripts/secret_provider.py).

Commands:

    python scripts/manage_secrets.py list-names
    python scripts/manage_secrets.py set --name EDINET_API_KEY   # value on stdin
    python scripts/manage_secrets.py get --name EDINET_API_KEY   # REDACTED
    python scripts/manage_secrets.py get --name X --show-secret I_UNDERSTAND
    python scripts/manage_secrets.py delete --name EDINET_API_KEY
    python scripts/manage_secrets.py audit

Rules (test-pinned):
  * values are read from stdin, never argv (shell history hygiene);
  * ``get`` is redacted by default; raw reveal requires the literal
    ``--show-secret I_UNDERSTAND``;
  * no secret value is ever logged or echoed by any other path;
  * ``audit`` re-uses the repo's data-protection audit and additionally
    confirms ``.env.example`` keeps every secret key as a placeholder.

Advisory-only scope: these are read-only data-provider keys. None of them
can place trades, move money, or touch a broker — no such integration
exists in this MVP.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from scripts import secret_provider as sp
except ModuleNotFoundError:  # pragma: no cover - script-style env
    import secret_provider as sp  # type: ignore[no-redef]

REDACTED = "<set (redacted)>"
NOT_SET = "<not set>"


def _require_known(name: str) -> None:
    if name not in sp.known_secret_names():
        known = ", ".join(sp.known_secret_names())
        raise SystemExit(f"[error] unknown secret name {name!r}. Known: {known}")


def cmd_list_names(provider) -> int:
    set_names = set(provider.list_set_names())
    print(f"provider mode: {provider.mode}")
    for name in sp.known_secret_names():
        print(f"  {name}: {'SET' if name in set_names else 'not set'}")
    return 0


def cmd_set(provider, name: str, stdin=None) -> int:
    _require_known(name)
    stdin = stdin or sys.stdin
    print(f"Paste value for {name} (input not echoed back):", file=sys.stderr)
    value = stdin.readline().strip()
    if not value:
        print("[error] empty value; nothing stored", file=sys.stderr)
        return 2
    provider.set(name, value)
    print(f"[ok] {name} stored in {provider.mode}", file=sys.stderr)
    return 0


def cmd_get(provider, name: str, show_secret: str | None) -> int:
    _require_known(name)
    value = provider.get(name)
    if value is None:
        print(NOT_SET)
        return 1
    if show_secret == "I_UNDERSTAND":
        # The ONLY raw-reveal path, and it demands the literal token.
        print(value)
        return 0
    print(REDACTED)
    return 0


def cmd_delete(provider, name: str) -> int:
    _require_known(name)
    provider.delete(name)
    print(f"[ok] {name} deleted from {provider.mode}", file=sys.stderr)
    return 0


def cmd_audit() -> int:
    try:
        from scripts import audit_local_data_protection as adp
    except ModuleNotFoundError:  # pragma: no cover
        import audit_local_data_protection as adp  # type: ignore[no-redef]

    violations = list(adp.audit(_REPO_ROOT))
    example = _REPO_ROOT / ".env.example"
    if example.exists():
        for line in example.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            for name in sp.known_secret_names():
                if stripped.startswith(f"{name}=") and stripped != f"{name}=":
                    violations.append(
                        f".env.example carries a non-empty value for {name}"
                    )
    print(f"secret custody audit (mode={sp.configured_mode()})")
    if violations:
        print(f"FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("PASS — no tracked secrets; .env.example placeholders empty.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-names")
    p_set = sub.add_parser("set")
    p_set.add_argument("--name", required=True)
    p_get = sub.add_parser("get")
    p_get.add_argument("--name", required=True)
    p_get.add_argument("--redacted", action="store_true",
                       help="(default behavior; flag kept for explicitness)")
    p_get.add_argument("--show-secret", default=None, metavar="I_UNDERSTAND",
                       help="raw reveal; requires the literal value I_UNDERSTAND")
    p_del = sub.add_parser("delete")
    p_del.add_argument("--name", required=True)
    sub.add_parser("audit")
    args = parser.parse_args(argv)

    if args.command == "audit":
        return cmd_audit()
    provider = sp.get_provider()
    if args.command == "list-names":
        return cmd_list_names(provider)
    if args.command == "set":
        return cmd_set(provider, args.name)
    if args.command == "get":
        if args.show_secret is not None and args.show_secret != "I_UNDERSTAND":
            print("[error] raw reveal requires --show-secret I_UNDERSTAND",
                  file=sys.stderr)
            return 2
        return cmd_get(provider, args.name, args.show_secret)
    if args.command == "delete":
        return cmd_delete(provider, args.name)
    return 2  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
