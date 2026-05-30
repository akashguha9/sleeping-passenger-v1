"""Secret-safe provider logging helpers — never print or persist raw secrets.

The real-provider activation work (UK filings, price providers, the daily
refresh) must report *whether* a credential is configured WITHOUT ever exposing
its value. A raw API key MUST never appear in a log line, a status dict, or a
report file written to disk.

Contract:
    * ``key_present`` answers the only question diagnostics ever need: is the
      credential set? It returns a bool, never the value.
    * ``redact`` collapses any secret-bearing value to ``***`` (optionally
      keeping a short suffix for operator disambiguation). It can never return
      the raw value.
    * ``provider_key_fields`` returns the secret-safe descriptor block embedded
      in every provider status: provider name, the env *name* (not value), and
      ``api_key_present``.
    * ``assert_no_secret`` is a defensive guard tests use to prove a rendered
      blob (log / report / status JSON) contains none of the live secret values.

This module performs NO network and NO execution. It is pure string handling.
"""
from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping


def key_present(env_name: str | None, env: Mapping[str, str] | None = None) -> bool:
    """Return True iff ``env_name`` resolves to a non-empty value.

    ``env`` defaults to ``os.environ`` but may be an injected mapping for
    deterministic tests. Never returns or logs the value itself.
    """
    if not env_name:
        return False
    source = os.environ if env is None else env
    return bool(str(source.get(env_name) or "").strip())


def redact(value: Any, *, keep_suffix: int = 0) -> str:
    """Return a redacted stand-in for a secret value — never the raw value.

    Empty / None -> ``"<absent>"``. With ``keep_suffix>0`` and a long-enough
    value, exposes only the trailing N chars behind ``***`` (e.g. ``***1a2b``);
    otherwise returns a bare ``***``.
    """
    text = str(value or "")
    if not text:
        return "<absent>"
    if keep_suffix > 0 and len(text) > keep_suffix:
        return "***" + text[-keep_suffix:]
    return "***"


def provider_key_fields(
    provider: str, env_name: str | None, env: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Secret-safe credential descriptor for a provider status block.

    Carries the env *name* (so an operator knows which variable to set) and a
    boolean ``api_key_present`` — never the secret value.
    """
    return {
        "provider": provider,
        "requires_api_key": env_name is not None,
        "api_key_env": env_name,
        "api_key_present": key_present(env_name, env) if env_name else False,
    }


def collect_secret_values(env_names: Iterable[str], env: Mapping[str, str] | None = None) -> list[str]:
    """Return the present (non-empty) raw values for the given env names.

    Intended only as input to :func:`assert_no_secret` so callers can prove a
    rendered blob does not leak any configured secret. The returned list is
    never logged by this module.
    """
    source = os.environ if env is None else env
    out: list[str] = []
    for name in env_names:
        raw = str(source.get(name) or "").strip()
        if raw:
            out.append(raw)
    return out


def assert_no_secret(blob: Any, secrets: Iterable[str]) -> bool:
    """Return True iff none of ``secrets`` appears verbatim in ``blob``.

    ``blob`` may be any object; dicts/lists are JSON-serialized first. Empty
    secret strings are ignored. Used by tests to fail loudly on a leak.
    """
    if isinstance(blob, (dict, list, tuple)):
        try:
            text = json.dumps(blob, default=str)
        except (TypeError, ValueError):
            text = str(blob)
    else:
        text = str(blob)
    for secret in secrets:
        if secret and str(secret) in text:
            return False
    return True


__all__ = [
    "key_present",
    "redact",
    "provider_key_fields",
    "collect_secret_values",
    "assert_no_secret",
]
