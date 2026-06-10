"""Owner token lifecycle: generate / rotate / verify the local API token.

The advisory MVP fails closed: the API server refuses to start until an
owner token is configured (see ``runtime_config.preflight_auth_or_die``).

Preferred storage is HASH MODE: only ``MVP_API_TOKEN_HASH`` (SHA-256 of
the token) is written to the gitignored ``.env``; the raw token is printed
exactly once at generation and exists nowhere else on disk. SHA-256
without stretching is appropriate ONLY because the token is 256 bits of
machine randomness — never reuse this scheme for human passwords.

Usage (Windows PowerShell or any shell):

    python scripts/generate_api_token.py                      # print token + hash
    python scripts/generate_api_token.py --write-env          # store hash in .env
    python scripts/generate_api_token.py --rotate --write-env # new token, old one dies
    python scripts/generate_api_token.py --verify-token       # paste token on stdin

Safety:
  * The raw token is printed ONCE to stdout at generation and never again.
    There is no way to recover it: only the hash is stored. If lost,
    rotate.
  * ``--verify-token`` reads the candidate from stdin (never argv, so it
    cannot land in shell history) and prints only MATCH / NO MATCH.
  * ``--write-env`` updates the MVP_API_TOKEN_HASH line and REMOVES any
    legacy plaintext MVP_API_TOKEN line; all other .env content is
    preserved. ``.env`` is gitignored — never commit it.
  * Advisory-only invariants are unaffected: this token gates the local
    journal API; it never authorizes broker execution (there is none).
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_PATH = _REPO_ROOT / ".env"


def generate_token() -> str:
    """256 bits of urlsafe randomness — far beyond brute-force reach."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Lowercase-hex SHA-256 of the token, the only thing stored on disk."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_env_hash(token_hash: str, env_path: Path | None = None) -> str:
    """Set MVP_API_TOKEN_HASH in .env; drop any legacy plaintext line.

    Every other line is preserved. Returns "created", "updated", or
    "appended" for operator feedback. ``env_path`` resolves at call time
    so tests can monkeypatch ``_ENV_PATH``.
    """
    if env_path is None:
        env_path = _ENV_PATH
    if not env_path.exists():
        env_path.write_text(f"MVP_API_TOKEN_HASH={token_hash}\n", encoding="utf-8")
        return "created"
    lines = env_path.read_text(encoding="utf-8-sig").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MVP_API_TOKEN_HASH="):
            out.append(f"MVP_API_TOKEN_HASH={token_hash}")
            replaced = True
        elif stripped.startswith("MVP_API_TOKEN="):
            # Rotation/upgrade invalidates the legacy plaintext token: the
            # server prefers hash mode, so leaving the old line behind
            # would only be misleading residue.
            continue
        else:
            out.append(line)
    if not replaced:
        out.append(f"MVP_API_TOKEN_HASH={token_hash}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return "updated" if replaced else "appended"


def read_env_hash(env_path: Path | None = None) -> str | None:
    """Read MVP_API_TOKEN_HASH from .env (no other secrets touched)."""
    if env_path is None:
        env_path = _ENV_PATH
    try:
        text = env_path.read_text(encoding="utf-8-sig")
    except (FileNotFoundError, OSError):
        return None
    for line in text.splitlines():
        if line.strip().startswith("MVP_API_TOKEN_HASH="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'").lower()
            return value or None
    return None


def verify_candidate(candidate: str, stored_hash: str) -> bool:
    """Constant-time check: Verify(T_raw, H_env).

    Invariant (test-pinned): True iff sha256(candidate) == stored_hash;
    every other candidate returns False.
    """
    import hmac

    return hmac.compare_digest(hash_token(candidate), stored_hash.strip().lower())


def _cmd_generate(write_env: bool, rotating: bool) -> int:
    token = generate_token()
    token_hash = hash_token(token)
    # The ONLY place the raw token is ever emitted.
    print(token)
    print(f"[hash] MVP_API_TOKEN_HASH={token_hash}", file=sys.stderr)
    if write_env:
        action = write_env_hash(token_hash)
        verb = "rotated into" if rotating else f"{action} in"
        print(f"[ok] MVP_API_TOKEN_HASH {verb} {_ENV_PATH}", file=sys.stderr)
        if rotating:
            print(
                "[ok] The previous token is now invalid. Restart the backend "
                "and re-paste the new token in the frontend panel.",
                file=sys.stderr,
            )
        else:
            print(
                "[ok] Restart the backend, then paste the token into the "
                "frontend's local API token panel (sessionStorage only).",
                file=sys.stderr,
            )
    else:
        print(
            "[hint] Re-run with --write-env to store the hash in .env. "
            "Only the hash is stored; the raw token above is shown ONCE "
            "and cannot be recovered — store it in a password manager or "
            "rotate when lost.",
            file=sys.stderr,
        )
    print(
        "[note] This token gates the local journal API only. It never "
        "authorizes trade execution; the MVP has no broker integration.",
        file=sys.stderr,
    )
    return 0


def _cmd_verify() -> int:
    import os

    stored = os.environ.get("MVP_API_TOKEN_HASH", "").strip().lower() or read_env_hash()
    if not stored:
        print("[error] no MVP_API_TOKEN_HASH found in env or .env", file=sys.stderr)
        return 2
    print("Paste token to verify (input is not echoed back):", file=sys.stderr)
    candidate = sys.stdin.readline().strip()
    if not candidate:
        print("[error] empty input", file=sys.stderr)
        return 2
    if verify_candidate(candidate, stored):
        print("MATCH")
        return 0
    print("NO MATCH")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="store MVP_API_TOKEN_HASH in the gitignored repo-root .env "
        "(removes any legacy plaintext MVP_API_TOKEN line)",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="generate a fresh token and invalidate the previous one "
        "(same as generate; spelled out for operator intent)",
    )
    parser.add_argument(
        "--verify-token",
        action="store_true",
        help="read a candidate token from stdin and check it against the "
        "stored hash; prints MATCH / NO MATCH only",
    )
    args = parser.parse_args(argv)

    if args.verify_token:
        if args.write_env or args.rotate:
            parser.error("--verify-token cannot be combined with generation flags")
        return _cmd_verify()
    if args.rotate and not args.write_env:
        parser.error("--rotate requires --write-env (rotation must persist the new hash)")
    return _cmd_generate(write_env=args.write_env, rotating=args.rotate)


if __name__ == "__main__":
    raise SystemExit(main())
