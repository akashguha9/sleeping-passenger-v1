"""H2: structural advisory-stamp backstop (ASGI middleware).

Sprint 1 stamped every handler and exception path individually; the audit
docked dimension 2 because the guarantee was per-handler convention, not
structure.  This middleware makes it structural: every outgoing
``application/json`` object response is inspected and any MISSING advisory
stamp is injected.  Handlers remain authoritative — existing keys are
never overwritten — the middleware is purely a fail-closed backstop for a
future handler someone forgets to stamp.

Scope rules:
* only ``http`` scopes; websockets/lifespan pass through untouched;
* only ``application/json`` responses whose body parses to a JSON object —
  CSV exports, file streams, arrays and scalars pass through byte-identical;
* bodies are buffered only for JSON responses (the journal API's JSON
  payloads are small; CSV/streaming responses are never buffered);
* if the body fails to parse as JSON it is forwarded unchanged — the
  middleware must never be able to break a response.

This module contains no broker calls and grants no execution permission;
it can only ADD the locked advisory stamps.
"""
from __future__ import annotations

import json
from typing import Any

# The canonical stamp block.  Values are the locked advisory constants —
# the middleware can only ever assert the SAFE state, never an unlocked one.
ADVISORY_STAMPS: dict[str, Any] = {
    "advisory_status": "ADVISORY_ONLY",
    "execution_mode": "HUMAN_ONLY",
    "execution_gate": "LOCKED",
    "ai_execution_count": 0,
    "broker_api_called": False,
    "broker_order_id": "NONE",
    "human_review_required": True,
}


def inject_missing_stamps(payload: dict[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with any missing advisory stamp added.

    Existing keys win unconditionally (handlers stay authoritative).
    """
    out = dict(payload)
    for key, value in ADVISORY_STAMPS.items():
        if key not in out:
            out[key] = value
    return out


class AdvisoryStampMiddleware:
    """Raw ASGI middleware — see module docstring."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_message: dict | None = None
        body_chunks: list[bytes] = []
        buffering = False

        async def send_wrapper(message) -> None:
            nonlocal start_message, buffering
            if message["type"] == "http.response.start":
                headers = message.get("headers") or []
                content_type = b""
                for name, value in headers:
                    if name.lower() == b"content-type":
                        content_type = value
                        break
                if content_type.split(b";")[0].strip() == b"application/json":
                    # Hold the start message until the full body is known so
                    # content-length can be rewritten after injection.
                    start_message = message
                    buffering = True
                else:
                    await send(message)
                return

            if message["type"] == "http.response.body" and buffering:
                body_chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                raw = b"".join(body_chunks)
                out = raw
                try:
                    parsed = json.loads(raw.decode("utf-8"))
                    if isinstance(parsed, dict):
                        out = json.dumps(
                            inject_missing_stamps(parsed),
                            separators=(",", ":"),
                        ).encode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    # Unparseable body — forward unchanged; the backstop
                    # must never be able to break a response.
                    out = raw
                assert start_message is not None
                headers = [
                    (n, v)
                    for n, v in (start_message.get("headers") or [])
                    if n.lower() != b"content-length"
                ]
                headers.append(
                    (b"content-length", str(len(out)).encode("ascii"))
                )
                await send({**start_message, "headers": headers})
                await send(
                    {"type": "http.response.body", "body": out, "more_body": False}
                )
                return

            await send(message)

        await self.app(scope, receive, send_wrapper)
