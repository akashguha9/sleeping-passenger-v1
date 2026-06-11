"""Secret custody abstraction for provider API keys (advisory MVP).

Gap being closed: read-only data-provider keys (EDINET, OpenDART,
Etherscan, xAI, NewsAPI, …) historically live as plaintext lines in the
gitignored ``.env``. This module lets the operator move them into OS key
custody without breaking anything.

Modes (selected by ``SECRET_PROVIDER`` env var):

* ``env`` (default) — current behavior: secrets come from the process
  environment / ``.env``. Works everywhere; documented as lower-security
  (plaintext at rest, readable by any same-user process).
* ``windows-credential-manager`` — secrets live in Windows Credential
  Manager (DPAPI-protected at rest, tied to the Windows account).
  Implemented via ``ctypes`` against ``advapi32`` — no extra dependency.
  On non-Windows platforms this provider is unavailable and says so.

There is deliberately NO "encrypted file" mode: an encryption key sitting
next to the encrypted file is security theater, and the repo has no
separate key-custody channel for one. Windows Credential Manager IS the
key custody channel on the supported platform.

App integration: ``hydrate_environment()`` is called at config import
time; when ``SECRET_PROVIDER=windows-credential-manager`` it copies known
secret names from the credential store into ``os.environ`` (setdefault —
real env always wins), so every existing loader keeps working unchanged.

Never logs or prints secret values. The owner token is NOT handled here —
it already has stronger custody (only its SHA-256 is stored anywhere).
"""
from __future__ import annotations

import os
import sys

_CRED_PREFIX = "sleeping-passenger-v1/"
_PROVIDER_ENV_VAR = "SECRET_PROVIDER"
MODE_ENV = "env"
MODE_WCM = "windows-credential-manager"
_VALID_MODES = (MODE_ENV, MODE_WCM)


def known_secret_names() -> tuple[str, ...]:
    """Provider-key names from the typed config contract (kind=secret)."""
    try:
        from scripts.config_contract import CONTRACT
    except ModuleNotFoundError:  # pragma: no cover - script-style env
        from config_contract import CONTRACT  # type: ignore[no-redef]
    # MVP_API_TOKEN/MVP_API_TOKEN_HASH have their own lifecycle
    # (generate_api_token.py) and are excluded from provider custody.
    return tuple(
        name
        for name, kind in CONTRACT.items()
        if kind == "secret" and not name.startswith("MVP_API_TOKEN")
    )


class SecretProviderError(RuntimeError):
    """Provider unavailable or operation failed (never carries a value)."""


class EnvProvider:
    """Process-environment custody — the documented lower-security default."""

    mode = MODE_ENV

    def get(self, name: str) -> str | None:
        value = os.environ.get(name, "").strip()
        return value or None

    def set(self, name: str, value: str) -> None:
        # Process-scope only; persistence stays the operator's .env. This
        # provider exists for parity + tests, not for durable writes.
        os.environ[name] = value

    def delete(self, name: str) -> None:
        os.environ.pop(name, None)

    def list_set_names(self) -> list[str]:
        return [n for n in known_secret_names() if self.get(n)]


class InMemoryProvider:
    """TEST-ONLY synthetic provider; never used for real custody."""

    mode = "in-memory-test"

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._store.get(name)

    def set(self, name: str, value: str) -> None:
        self._store[name] = value

    def delete(self, name: str) -> None:
        self._store.pop(name, None)

    def list_set_names(self) -> list[str]:
        return [n for n in known_secret_names() if n in self._store]


class WindowsCredentialManagerProvider:
    """Windows Credential Manager custody via ctypes/advapi32 (no deps).

    Secrets are stored as generic credentials named
    ``sleeping-passenger-v1/<NAME>``, DPAPI-protected at rest and bound to
    the logged-in Windows account. Available on Windows only.
    """

    mode = MODE_WCM
    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        if sys.platform != "win32":  # pragma: no cover - exercised on Windows
            raise SecretProviderError(
                "windows-credential-manager provider requires Windows. "
                "Use SECRET_PROVIDER=env on this platform."
            )
        import ctypes
        import ctypes.wintypes as wt

        self._ctypes = ctypes
        self._wt = wt
        self._advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [
                ("Flags", wt.DWORD),
                ("Type", wt.DWORD),
                ("TargetName", wt.LPWSTR),
                ("Comment", wt.LPWSTR),
                ("LastWritten", wt.FILETIME),
                ("CredentialBlobSize", wt.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wt.DWORD),
                ("AttributeCount", wt.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wt.LPWSTR),
                ("UserName", wt.LPWSTR),
            ]

        self._CREDENTIAL = CREDENTIAL

    def _target(self, name: str) -> str:
        return _CRED_PREFIX + name

    def get(self, name: str) -> str | None:  # pragma: no cover - Windows only
        ctypes = self._ctypes
        pcred = ctypes.POINTER(self._CREDENTIAL)()
        ok = self._advapi32.CredReadW(
            self._target(name), self._CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)
        )
        if not ok:
            return None
        try:
            cred = pcred.contents
            size = cred.CredentialBlobSize
            if not size:
                return None
            raw = ctypes.string_at(cred.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._advapi32.CredFree(pcred)

    def set(self, name: str, value: str) -> None:  # pragma: no cover - Windows only
        ctypes = self._ctypes
        blob = value.encode("utf-16-le")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = self._CREDENTIAL()
        cred.Flags = 0
        cred.Type = self._CRED_TYPE_GENERIC
        cred.TargetName = self._target(name)
        cred.Comment = "sleeping-passenger-v1 provider key (advisory-only MVP)"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist = self._CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = None
        if not self._advapi32.CredWriteW(ctypes.byref(cred), 0):
            raise SecretProviderError(
                f"CredWriteW failed for {name} "
                f"(winerror={ctypes.get_last_error()})"
            )

    def delete(self, name: str) -> None:  # pragma: no cover - Windows only
        self._advapi32.CredDeleteW(self._target(name), self._CRED_TYPE_GENERIC, 0)

    def list_set_names(self) -> list[str]:  # pragma: no cover - Windows only
        return [n for n in known_secret_names() if self.get(n) is not None]


def configured_mode() -> str:
    raw = os.environ.get(_PROVIDER_ENV_VAR, "").strip().lower()
    return raw if raw in _VALID_MODES else MODE_ENV


def get_provider(mode: str | None = None):
    """Return the active provider; fails loudly for an unavailable mode."""
    mode = (mode or configured_mode()).strip().lower()
    if mode == MODE_WCM:
        return WindowsCredentialManagerProvider()
    return EnvProvider()


def resolve_secret(name: str) -> str | None:
    """Provider lookup with env fallback — missing secrets return None,
    they never raise mid-request (loaders already skip cleanly on None)."""
    try:
        value = get_provider().get(name)
    except SecretProviderError:
        value = None
    if value:
        return value
    return EnvProvider().get(name)


def hydrate_environment() -> int:
    """Copy known secrets from OS custody into os.environ (setdefault).

    No-op unless ``SECRET_PROVIDER=windows-credential-manager``. Real
    environment variables always win. Returns the number of names
    hydrated; never raises (config import must not die because custody
    is unavailable — the loaders will simply see unset keys and skip).
    """
    if configured_mode() != MODE_WCM:
        return 0
    try:
        provider = get_provider(MODE_WCM)
    except SecretProviderError:
        return 0
    count = 0
    for name in known_secret_names():
        if os.environ.get(name, "").strip():
            continue
        try:
            value = provider.get(name)
        except Exception:
            continue
        if value:
            os.environ.setdefault(name, value)
            count += 1
    return count
