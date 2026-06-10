"""First-run owner setup: generate a strong local MVP_API_TOKEN.

The advisory MVP fails closed: the API server refuses to start until
``MVP_API_TOKEN`` is configured (see ``runtime_config.preflight_auth_or_die``).
This helper generates a cryptographically strong token and (optionally)
writes it into the gitignored repo-root ``.env``.

Usage (Windows PowerShell or any shell):

    python scripts/generate_api_token.py              # print a token
    python scripts/generate_api_token.py --write-env  # also store in .env

Safety:
  * The token is printed ONCE to stdout for the operator to paste into the
    frontend's local token panel.  It is never logged elsewhere.
  * ``--write-env`` updates only the MVP_API_TOKEN line; all other .env
    content is preserved.  ``.env`` is gitignored — never commit it.
  * Advisory-only invariants are unaffected: this token gates the local
    journal API; it never authorizes broker execution (there is none).
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO_ROOT / ".env"


def generate_token() -> str:
    """256 bits of urlsafe randomness — far beyond brute-force reach."""
    return secrets.token_urlsafe(32)


def write_env(token: str, env_path: Path = _ENV_PATH) -> str:
    """Set MVP_API_TOKEN in .env, preserving every other line.

    Returns "created", "updated", or "appended" for operator feedback.
    """
    if not env_path.exists():
        env_path.write_text(f"MVP_API_TOKEN={token}\n", encoding="utf-8")
        return "created"
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith("MVP_API_TOKEN="):
            out.append(f"MVP_API_TOKEN={token}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"MVP_API_TOKEN={token}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return "updated" if replaced else "appended"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="store the token as MVP_API_TOKEN in the gitignored repo-root .env",
    )
    args = parser.parse_args(argv)

    token = generate_token()
    print(token)
    if args.write_env:
        action = write_env(token)
        print(f"[ok] MVP_API_TOKEN {action} in {_ENV_PATH}", file=sys.stderr)
        print(
            "[ok] Restart the backend, then paste the token into the "
            "frontend's local API token panel (it is kept in sessionStorage "
            "only).",
            file=sys.stderr,
        )
    else:
        print(
            "[hint] Re-run with --write-env to store it in .env, or set it "
            "yourself: MVP_API_TOKEN=<token>",
            file=sys.stderr,
        )
    print(
        "[note] This token gates the local journal API only. It never "
        "authorizes trade execution; the MVP has no broker integration.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
