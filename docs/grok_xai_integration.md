# Grok xAI Intelligence Layer

This repo now includes `scripts/grok_xai_adapter.py` as a read-only intelligence overlay.

## What It Does

- Interprets observed payloads into strict JSON.
- Compresses narrative context into small structured fields.
- Ranks current candidate signals for operator review.
- Writes `runtime/grok_xai_report.json` as a stamped runtime artifact.

## What It Does Not Do

- It does not approve trades.
- It does not change governance or execution permissions.
- It does not place orders, sign wallets, or enable live trading.
- It does not convert model interpretation into market proof.
- It does not silently fall back to another model when `XAI_MODEL` is missing.

## Required Environment Variables

- `XAI_API_KEY`
- `XAI_API_BASE_URL`
- `XAI_MODEL`

The checked-in config surface is `config/llm_provider_config.json`. It stores only env var names, timeouts, mode flags, and the advisory contract. No secrets are committed.

## Supported Use Cases

- `polymarket_payload_interpreter`
- `blockscout_payload_interpreter`
- `signal_ranking_interpreter`

Each use case requests structured JSON and validates the returned shape before the artifact is marked successful.

## Local Commands

```powershell
python scripts\grok_xai_adapter.py --summary
python scripts\grok_xai_adapter.py --use-case polymarket_payload_interpreter --summary
python scripts\grok_xai_adapter.py --use-case blockscout_payload_interpreter --summary
python scripts\grok_xai_adapter.py --use-case signal_ranking_interpreter --summary
```

Optional custom input:

```powershell
python scripts\grok_xai_adapter.py --use-case polymarket_payload_interpreter --input-path runtime\polymarket_gamma_report.json --summary
python scripts\grok_xai_adapter.py --use-case signal_ranking_interpreter --input-json "{\"candidate_signals\":[{\"ticker\":\"RTX\"}]}" --summary
```

## Runtime Artifact

`runtime/grok_xai_report.json` truthfully records:

- request success or failure
- `error_kind` when it fails
- model requested and model used
- the selected use case
- a compact input preview
- validated structured output on success
- stamped `operating_mode`, `truth_origin`, `run_id`, and `config_fingerprint`
- the advisory-only contract

Failure states such as `unauthorized`, `empty_response`, `invalid_json`, `request_error`, and non-2xx HTTP responses are persisted explicitly.

## Health Report Integration

`pipeline_health_report.py` now accepts an explicit `grok_xai_report` payload and exposes a compact `intelligence_summary` block. This is optional. The health report does not auto-call Grok and does not auto-load Grok output by default.
