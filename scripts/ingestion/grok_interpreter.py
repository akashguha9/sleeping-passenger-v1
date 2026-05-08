"""
xAI Grok read-only interpreter — Phase 2 Global Signal Fabric.

Requires XAI_API_KEY env var. Skips cleanly if missing.
Returns structured textual observations from Grok as advisory signals.
This module only reads/interprets — it never executes or places orders.
"""
from __future__ import annotations

from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_XAI_BASE = "https://api.x.ai/v1/chat/completions"
_TIMEOUT = 30
_DEFAULT_MODEL = "grok-beta"
_ADVISORY_SYSTEM_PROMPT = (
    "You are a read-only market observation assistant. "
    "Provide factual, observational summaries only. "
    "Never recommend actions. "
    "All outputs are advisory and require human review."
)


class GrokInterpreter(BaseSourceLoader):
    source_name = "grok_xai"
    requires_key = True

    def __init__(
        self,
        prompt: str | None = None,
        model: str = _DEFAULT_MODEL,
        timeout: int = _TIMEOUT,
        base_url: str = _XAI_BASE,
    ) -> None:
        self._prompt = prompt or (
            "Summarize current macro market conditions in 3 bullet points."
        )
        self._model = model
        self._timeout = timeout
        self._base_url = base_url

    def fetch(self) -> LoaderResult:
        """Query xAI Grok for advisory market observations. Requires XAI_API_KEY."""
        api_key = self._require_env_key("XAI_API_KEY")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _ADVISORY_SYSTEM_PROMPT},
                {"role": "user", "content": self._prompt},
            ],
            "max_tokens": 512,
        }
        try:
            resp = requests.post(
                self._base_url, json=payload, headers=headers, timeout=self._timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise SkipLoader(f"xAI Grok API unreachable: {exc}") from exc

        content = ""
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content", "")

        rec: dict[str, Any] = {
            "model": self._model,
            "prompt": self._prompt,
            "response": content,
            "source": "grok_xai",
        }
        self._stamp_record(rec)
        return LoaderResult(source_name=self.source_name, records=[rec])
