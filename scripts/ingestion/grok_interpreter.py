"""
xAI Grok read-only interpreter — Phase 2 Global Signal Fabric.

Requires XAI_API_KEY (or GROK_API_KEY) env var. Skips cleanly if missing.
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
- No wallet, signing, transaction, approval, transfer, or transmission logic.

Model fallback order
--------------------
1. XAI_MODEL env var (if set and not in the deprecated list)
2. grok-3-mini
3. grok-3
4. grok-2-latest

Error reporting
---------------
Each model attempt records the sanitized status code + a short body excerpt
so the operator can distinguish:
  * 401/403 → auth problem (bad key / missing entitlement)
  * 400 → bad model or malformed request (we fall back to next model)
  * 404 → model not available on this account
  * 429 → rate limited
  * Timeout / network error → transient
The API key is stripped from every reported error string.
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

# Ordered fallback list (tried in sequence on 400 / 404)
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


def _sanitize(text: str, api_key: str | None) -> str:
    """Strip the API key from any reported error text. Truncates to keep logs sane."""
    if not text:
        return ""
    cleaned = str(text)
    if api_key:
        cleaned = cleaned.replace(api_key, "<redacted>")
    # Strip Bearer header form if present
    cleaned = cleaned.replace(f"Bearer {api_key}", "Bearer <redacted>") if api_key else cleaned
    cleaned = cleaned.strip()
    # Truncate excessive bodies so error logs stay readable
    if len(cleaned) > 400:
        cleaned = cleaned[:400] + "…"
    return cleaned


def _extract_error_body(resp: Any, api_key: str | None) -> str:
    """Pull a short, sanitized description from a non-2xx response."""
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("type") or json.dumps(err)
                return _sanitize(str(msg), api_key)
            if err:
                return _sanitize(str(err), api_key)
            return _sanitize(json.dumps(body), api_key)
        return _sanitize(str(body), api_key)
    except Exception:
        pass
    try:
        return _sanitize(getattr(resp, "text", "") or "", api_key)
    except Exception:
        return ""


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
        api_key: str | None,
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        """
        Attempt one API call with the given model.
        Returns (response_json, error_tag_or_None, sanitized_detail).
        error_tag in: "400_model", "auth", "not_found", "rate_limited",
                       "timeout", "network", "http_error", "bad_json".
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
        except requests_mod.exceptions.Timeout as exc:
            return None, "timeout", _sanitize(f"{type(exc).__name__}: {exc}", api_key)
        except Exception as exc:
            return None, "network", _sanitize(f"{type(exc).__name__}: {exc}", api_key)

        try:
            status = int(resp.status_code)
        except (TypeError, ValueError):
            status = -1

        body_excerpt = _extract_error_body(resp, api_key)

        if status == 400:
            return None, "400_model", f"status=400 body={body_excerpt}"
        if status in (401, 403):
            return None, "auth", f"status={status} body={body_excerpt}"
        if status == 404:
            return None, "not_found", f"status=404 body={body_excerpt}"
        if status == 429:
            return None, "rate_limited", f"status=429 body={body_excerpt}"

        try:
            resp.raise_for_status()
        except Exception:
            return None, "http_error", f"status={status} body={body_excerpt}"

        try:
            return resp.json(), None, None
        except Exception as exc:
            return None, "bad_json", _sanitize(
                f"{type(exc).__name__}: {exc}", api_key
            )

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
        last_tag: str | None = None
        attempts: list[str] = []
        effective_model = candidates[0] if candidates else _DEFAULT_MODEL

        for model in candidates:
            effective_model = model
            data, err, detail = self._try_model(requests, model, headers, api_key)
            attempts.append(f"{model}={err or 'ok'}")

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

            last_tag = err
            last_error = f"model={model!r} {detail or err}"

            if err in ("400_model", "not_found"):
                # Try the next model — likely deprecated/unavailable for this account
                continue
            if err == "auth":
                # Auth problems won't be fixed by another model
                raise SkipLoader(
                    f"[XAI_AUTH] xAI Grok rejected the API key — {detail}"
                )
            if err == "rate_limited":
                raise SkipLoader(
                    f"[RATE_LIMITED] xAI Grok rate limit hit on {model!r} — {detail}"
                )
            if err == "timeout":
                raise SkipLoader(
                    f"[TIMEOUT] xAI Grok API timed out with model {model!r} — {detail}"
                )
            # network / http_error / bad_json — stop trying
            break

        summary = "; ".join(attempts)
        raise SkipLoader(
            f"xAI Grok unreachable: all model candidates failed [{summary}] "
            f"last_tag={last_tag} last={last_error}"
        )

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
