# Threat Model — Sleeping Passenger (Advisory-Only MVP)

One page, verified against the code on 2026-06-12. Every claim below is
enforced by a test, a CI gate, or a startup check — citations inline.
This consolidates a posture that previously lived scattered across
safety docs; it is the document a security reviewer should read first.

## Assets to protect

1. **The advisory-only contract** — no order may ever be executed.
2. **Verdict integrity** — scores must not be gameable by crafted input.
3. **Operator data** — the local journal DB, reflections, trade log.
4. **Secrets** — API tokens, provider keys (operator-supplied only).

## Trust boundaries

```
Internet ──X── (no inbound by default: API binds 127.0.0.1)
Operator ──→ FastAPI (Bearer token on ALL mutating routes; reads
             token-gated or loopback-only) ──→ pure scoring engines
                                           ──→ local SQLite (runtime/)
Frontend (localhost:3000) ──CORS-pinned──→ API
```

## Adversaries considered

| Adversary | Vector | Defense (verified) |
|---|---|---|
| Network attacker | hitting exposed API | Default bind 127.0.0.1; startup preflight refuses non-loopback without `MVP_API_TOKEN` (`api_server.py` preflight); rate limits per IP (read 120/min, write 30/min); 1MB body cap; CORS pinned to localhost:3000, credentials off |
| Malicious caller | NaN/Infinity in JSON payloads | Non-finite values coerce to conservative defaults at the single choke point (`validation_utils.coerce_float`); `clip` resolves NaN to the MINIMUM bound; `tests/test_adversarial_inputs.py` proves a NaN-poisoned payload scores exactly like one with those fields absent |
| Malicious caller | type confusion (string/list where dict expected) | All payload sections degrade to "absent" via `section_dict`; 51 parametrized junk-section tests prove no 500s |
| Malicious caller | combinatoric DoS (many risk factors) | Crash simulator caps at the 10 strongest factors (≤165 combinations); wind-tunnel replay caps bars (2000) and decisions (200) |
| Gaming caller | optimistic opponent overrides | Cross-exam asymmetry: optimistic overrides lose to engine-derived values and are recorded (`OPPONENT_OVERRIDE_CHALLENGED`); suppressible fields are *published* in `gameable_inputs` rather than denied |
| Gaming caller | many small lies, no big one | Risk-convergence committee: ≥2 independent doubt families cap the verdict; doubts deduplicated by root cause |
| Compromised dependency | supply chain | CI `dep_audit`: pip-audit (strict) + npm audit (high/critical) + weekly schedule |
| Leaked secrets | commits | gitleaks in CI **and** pre-commit; repo-hygiene gate blocks `.env`/`.db`/broker-token filenames from ever being tracked |
| Future developer | accidentally adding execution | Kante defensive gate (CI): compliance preflight asserts no broker routes, no "we trade for you" language; advisory stamps (`execution_gate=LOCKED`, `ai_execution_count=0`) asserted on every code path; route-forbid tests |
| Stack-trace leakage | unhandled exceptions | Global handler returns generic `internal_error`; full detail server-side only |

## Deliberately out of scope (single-operator MVP)

- Multi-user auth/roles (one operator, one token).
- Encryption at rest for the local SQLite journal (host-level concern).
- DDoS resistance beyond per-IP rate limits (do not expose publicly).
- Prompt-injection: no LLM consumes untrusted third-party text at
  decision time; AI summaries are operator-initiated and advisory.

## Residual risks (honest)

1. **Token handling is binary** — one bearer token, no rotation or
   scoping. Acceptable for a sole operator; revisit before any second
   user.
2. **Read routes on loopback without a token are open by design** —
   anything else running on the same host can read journal data.
3. **`MVP_ALLOW_UNAUTH=1` exists** as an explicit foot-gun override;
   it is logged loudly but it is still a foot-gun.
4. **Verdict gaming via wholesale payload fabrication remains
   epistemically possible** — the system can only enforce internal
   consistency and publish its gaming surface (see
   `counterfactual_wind_tunnel.gameable_inputs`); it cannot verify the
   world outside the payload.

## Standing rule

If a change touches auth, routes, advisory stamps, or payload
validation, it must keep `tests/test_adversarial_inputs.py`,
the route-forbid tests, and the Kante defensive gate green — these are
the contract, not decoration.

## CSP status (2026-06-12)

`script-src 'self' 'unsafe-inline'` is the current, deliberate setting.
The stricter `script-src 'self'` shipped by the S8 sprint blocked
Next.js App Router's inline hydration scripts and silently turned the
entire client into static HTML — caught the day Playwright e2e entered
CI. The hardening path back is **nonce-based CSP via Next middleware**
(generate a per-request nonce in `middleware.ts`, emit it in the CSP
header; Next ≥14 propagates it to its inline scripts automatically).
That change must land WITH the e2e suite as its gate — never again a
CSP change verified only by tests that don't execute a browser.
Residual exposure until then: inline-script XSS would execute; exfil
remains constrained by the pinned `connect-src` and the absence of any
third-party script origin.
