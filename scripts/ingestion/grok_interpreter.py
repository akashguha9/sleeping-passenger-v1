"""
xAI Grok read-only interpreter — Phase 2 Global Signal Fabric.

Requires XAI_API_KEY env var. Skips cleanly if missing.
Returns structured interpretation observations from Grok as advisory signals.
This module only reads/interprets — it never executes or places orders.

Grok output is hypothesis/interpretation only, never truth.
All outputs carry advisory_status="ADVISORY_ONLY", human_review_required=True,
execution_gate="LOCKED", ai_execution_count=0, broker_api_called=False.

Safety invariants
-----------------
- advisory_status must remain ADVISORY_ONLY.
- human_review_required must remain true.
- execution_gate must remain LOCKED.
- ai_execution_count must remain 0.
- broker_api_called must remain false.
- No broker order path. No buy/sell/execute endpoint. No auto-trading.
- No private-key, wallet, signing, transaction, approval, transfer, or transmission logic.

Model fallback order
--------------------
1. XAI_MODEL env var (if set and not in the deprecated list)
2. grok-3-mini
3. grok-3
4. grok-2-latest
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from scripts.ingestion.base_loader import BaseSourceLoader, LoaderResult, SkipLoader

_XAI_BASE = "https://api.x.ai/v1/chat/completions"
_TIMEOUT = 30
_DEFAULT_MODEL = "grok-3-mini"
_DEFAULT_MAX_ITEMS = 1

# Models known to be deprecated or invalid — skip when found in env
_DEPRECATED_MODELS: frozenset[str] = frozenset({"grok-beta", "grok-1"})

# Ordered fallback list (tried in sequence on 400)
_MODEL_FALLBACK_ORDER: list[str] = ["grok-3-mini", "grok-3", "grok-2-latest"]

_ADVISORY_SYSTEM_PROMPT = (
    "You are a read-only market observation assistant. "
    "Provide factual, observational summaries only. "
    "Never recommend actions, trades, buy/sell signals, or execution of any kind. "
    "All outputs are advisory hypotheses and require human review. "
    "Respond ONLY with a valid JSON object (no markdown, no code blocks) "
    "with these exact keys: "
    '"interpreted_topic" (string — the main subject), '
    '"narrative_frame" (string — the dominant narrative lens), '
    '"contradiction_flags" (array of strings — any contradictions or uncertainties), '
    '"confidence_score" (float 0.0 to 1.0 — your confidence in the interpretation), '
    '"summary_text" (string — 2-3 sentence observational summary). '
    "Do not include any text outside the JSON object."
)


def _build_model_candidates(env_model: str) -> list[str]:
    """Build the ordered list of models to try, skipping deprecated ones."""
    candidates: list[str] = []
    if env_model and env_model not in _DEPRECATED_MODELS:
        candidates.append(env_model)
    for m in _MODEL_FALLBACK_ORDER:
        if m not in candidates:
            candidates.append(m)
    return candidates


class GrokInterpreter(BaseSourceLoader):
    source_name = "grok_xai"
    requires_key = True

    def __init__(
        self,
        prompt: str | None = None,
        model: str = _DEFAULT_MODEL,
        max_items: int = _DEFAULT_MAX_ITEMS,
        timeout: int = _TIMEOUT,
        base_url: str = _XAI_BASE,
    ) -> None:
        self._prompt = prompt or (
            "Summarize current macro market conditions: identify the main theme, "
            "the dominant narrative, any visible contradictions, and your confidence level."
        )
        self._model = model
        self._max_items = max(1, max_items)
        self._timeout = timeout
        self._base_url = base_url

    def _try_model(
        self,
        requests_mod: Any,
        model: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        Attempt one API call with the given model.
        Returns (response_json, error_tag_or_None).
        error_tag: "400_model" (likely bad model), "400_other", "skip" (hard fail).
        """
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": _ADVISORY_SYSTEM_PROMPT},
                {"role": "user", "content": self._prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        try:
            resp = requests_mod.post(
                self._base_url, json=payload, headers=headers, timeout=self._timeout
            )
        except requests_mod.exceptions.Timeout:
            return None, "timeout"
        except Exception:
            return None, "skip"

        # Check for 400 explicitly before raise_for_status so we can fall back model
        try:
            status = int(resp.status_code)
        except (TypeError, ValueError):
            status = -1

        if status == 400:
            return None, "400_model"

        try:
            resp.raise_for_status()
            return resp.json(), None
        except Exception:
            return None, "skip"

    def fetch(self) -> LoaderResult:
        """Query xAI Grok for advisory interpretation. Requires XAI_API_KEY or GROK_API_KEY."""
        api_key = self._require_env_any("XAI_API_KEY", "GROK_API_KEY")

        try:
            import requests
        except ImportError:
            raise SkipLoader("requests library not installed")

        env_model = os.environ.get("XAI_MODEL", "").strip()
        candidates = _build_model_candidates(env_model or self._model)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        last_error = "no models tried"
        effective_model = candidates[0] if candidates else _DEFAULT_MODEL

        for model in candidates:
            effective_model = model
            data, err = self._try_model(requests, model, headers)
            if err is None and data is not None:
                # Success
                raw_content = ""
                choices = data.get("choices", []) if isinstance(data, dict) else []
                if choices and isinstance(choices[0], dict):
                    raw_content = (choices[0].get("message") or {}).get("content", "")

                created_at = datetime.now(timezone.utc).isoformat()
                rec = self._parse_grok_response(
                    raw_content, created_at, effective_model=model
                )
                self._stamp_record(rec)
                return LoaderResult(source_name=self.source_name, records=[rec])

            if err == "400_model":
                # This model was rejected — try the next one
                last_error = f"model {model!r} returned 400 (likely deprecated or unavailable)"
                continue

            if err == "timeout":
                last_error = f"[TIMEOUT] xAI Grok API timed out with model {model!r}"
                break

            # Hard failure — skip entirely
            last_error = f"xAI Grok API unreachable with model {model!r}"
            break

        raise SkipLoader(f"xAI Grok: all model candidates failed — last: {last_error}")

    def _parse_grok_response(
        self,
        raw_content: str,
        created_at: str,
        effective_model: str | None = None,
    ) -> dict[str, Any]:
        """Parse Grok JSON response; fall back gracefully on parse failure."""
        interpreted_topic = ""
        narrative_frame = ""
        contradiction_flags: list[str] = []
        confidence_score: float | None = None
        summary_text = raw_content.strip()

        if raw_content.strip():
            try:
                parsed = json.loads(raw_content.strip())
                if isinstance(parsed, dict):
                    interpreted_topic = str(parsed.get("interpreted_topic", ""))
                    narrative_frame = str(parsed.get("narrative_frame", ""))
                    cf = parsed.get("contradiction_flags", [])
                    contradiction_flags = [str(f) for f in cf] if isinstance(cf, list) else []
                    cs = parsed.get("confidence_score")
                    if isinstance(cs, (int, float)):
                        confidence_score = float(max(0.0, min(1.0, float(cs))))
                    summary_text = str(parsed.get("summary_text", raw_content.strip()))
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "source": "grok_xai",
            "model_name": effective_model or self._model,
            "source_prompt": self._prompt,
            "interpreted_topic": interpreted_topic,
            "narrative_frame": narrative_frame,
            "contradiction_flags": contradiction_flags,
            "confidence_score": confidence_score,
            "summary_text": summary_text,
            "grok_response": raw_content,
            "created_at": created_at,
            "ai_execution_count": 0,
            "broker_api_called": False,
        }
