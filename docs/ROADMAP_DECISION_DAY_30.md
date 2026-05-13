# Roadmap Decision — Day 30

> The strategic doc that answers "what should we *not* build yet?" and
> "what is the next honest unit of progress?" The Day 26 product-direction
> doc picked the *path*. This one picks the *next-30 / next-90 work*.

---

## 1. What is the MVP now?

A working, locally hostable signal review and reflection journal:

- FastAPI backend (`scripts/api_server.py`) with `/health`, `/api/version`,
  `/db/status`, signals, manual trades, reconciliation, reflections,
  moltbook, source-health summary, and exports.
- Next.js frontend with sidebar workflow grouping, dashboard mission-control,
  signal inbox/detail, manual trade pages, reconciliation, Moltbook,
  settings/help, mock fallback.
- SQLite persistence with WAL, busy-timeout, foreign-key hardening, backup,
  restore.
- 11 live source families covered (8 implemented end-to-end, 1 partial,
  1 implemented-but-mostly-placeholder for region, 1 planned).
- A 6-hour refresh orchestrator that is **dry-run safe by default**.
- An AI output validation schema with safety-stamp enforcement.
- 2950 + 67 new = ~3017 backend tests.
- Comprehensive documentation: setup, demo, testing, deployment, persistence,
  legal/privacy, source-ToS, AI-output validation, scheduling, refresh model.

---

## 2. What is the best next path?

**Local-first showcase first; private-beta design only.** See `docs/PRODUCT_DIRECTION_DECISION.md`.

---

## 3. What should not be built yet?

| Track | Why not |
|---|---|
| Broker integration | Crosses the regulatory line, violates safety contract. |
| Automated trading | Same. |
| Public landing page / marketing site | We do not have a public product. |
| New bull-state engines | We already have plenty of unvalidated content. |
| New sport-archetype modules | Unrelated to the MVP's actual goal. |
| Speculative ML / RL models | We have no calibration data and no labeled outcomes. |
| Paid product surface (billing, plans) | No buyers, no compliance, no support. |
| Mobile app | The local-first model does not yet need it. |
| Real-time tick streaming | The 6-hour cadence is the correct first model. |

---

## 4. Required for **local showcase** (Track A)

| Item | Status | Owner |
|---|---|---|
| Reproducible setup (SETUP.md, smoke check, Docker scaffold) | ✓ | done |
| Backup / restore proof | ✓ | done (Day 1–10) |
| 2950 backend tests pass | ✓ | done |
| SHOWCASE.md | ✓ Day 31 | this sprint |
| Architecture diagrams | ✓ Day 31 | this sprint |
| AI output validation + tests | ✓ Day 26 | this sprint |
| Legal / privacy notes | ✓ Day 27 | this sprint |
| Live source registry + refresh model | ✓ Day 28–29 | this sprint |
| Final acceptance checklist + scorecard | ✓ Day 35 | this sprint |
| Recorded demo (screen recording) | ✗ | post-sprint |
| Screenshots in repo | ✗ | post-sprint |
| Frontend unit/e2e tests | partial | next-30 |

---

## 5. Required for **private beta** (Track B)

| Item | Status |
|---|---|
| Real multi-user auth | designed (Day 32), not implemented |
| Per-user data isolation | designed (Day 32), not implemented |
| Hosted Postgres | planned (Day 33), not implemented |
| Hosted deployment | planned (Day 34), not implemented |
| Monitoring + alerts | planned (Day 34), not implemented |
| Hosted secrets management | planned (Day 34), not implemented |
| HTTPS termination | not implemented |
| Backup / retention policy in production | partial (local backup script exists) |
| Source-ToS clearance per family | checklist exists, not signed off |
| Legal / privacy review by counsel | not done |
| E2E proof of canonical flow | partial (backend tests cover most steps) |

**Verdict: private beta is design-complete after this sprint, but not
implementation-complete. Do not ship.**

---

## 6. Required for **public launch** (Track C)

Everything in Track B, plus:

- Compliance review for the regulatory surface of the operator's
  jurisdiction (US/UK/IN/EU/SG/HK depending on intended users).
- Security review of the hosted surface (penetration test, threat model,
  CIS hardening).
- Production-grade monitoring (uptime, latency SLOs, error-rate alerts,
  source-health alerts, DB-size alerts).
- Incident response runbook with on-call rotation.
- User support process (email, ticketing, response SLAs).
- Performance work for >1 operator (concurrent SQLite is *not* the answer
  beyond a tiny private beta; Postgres is required).
- Source provider permission for the planned display pattern, in writing
  if redistribution is implied.

**Verdict: public launch is not on the table this year.**

---

## 7. 30-day recommendation

| Week | Theme | Deliverables |
|---|---|---|
| Week 1 | Polish | Take screenshots, record 5-min demo, fix any visual jank, ship to GitHub Pages or Vercel as a static portfolio page. |
| Week 2 | Frontend coverage | Add Playwright e2e covering the canonical 13-step workflow. |
| Week 3 | AI eval seed | Backfill 20–50 historical signals through the AI summary + validation schema; record `validation_status` distribution; that data seeds the eval harness. |
| Week 4 | Private-beta design execution | Choose the auth provider (Day 32 lays out the comparison); spike a feature branch with users-table + per-route scope check; no merge until the spike is complete. |

---

## 8. 90-day recommendation

| Month | Theme | Deliverables |
|---|---|---|
| M1 | Showcase + AI eval | The 30-day plan above. Demo and eval data in hand. |
| M2 | Private-beta scaffolding | Auth implemented behind a feature flag; users-table migration; per-user isolation tests; Postgres adapter spike; hosted-deployment Docker stack on a single VPS. |
| M3 | Closed-loop private beta | 3–5 trusted users; hosted backup; monitoring alerts wired; source-health alerts; weekly retro on what they actually use. |

If at the end of M3 the answer is "they actually use it daily," the public
launch path comes back into scope. If "they use it for a week then drift,"
the product needs a different shape than what this MVP captured.

---

## 9. Live-source roadmap

| Source family | Current | Next |
|---|---|---|
| Polymarket | implemented, key-free | nothing |
| GDELT | implemented, key-free | nothing |
| SEC EDGAR | implemented (UA only) | possibly per-issuer subscriptions |
| NewsAPI | implemented, key | quota monitoring before --write cron |
| Event Registry | implemented, key | quota monitoring |
| Etherscan | implemented, key | additional chain adapters only if asked |
| Grok/xAI | implemented, key | eval harness, prompt-version bump audit |
| Market Data (yfinance) | implemented, key-free | consider a paid OHLCV provider if displayed publicly |
| India (NSE/RBI/SEBI) | implemented, key-free | nothing |
| Global Filings | partial (ASX live, 6 placeholders) | implement HKEX or UK-RNS only when a user asks for it |
| Asia Disclosure | planned (all placeholders) | hold; this is roadmap, not Q1 work |

---

## 10. AI validation roadmap

| Phase | Deliverable |
|---|---|
| **Done (this sprint)** | Schema, malformed-output handling, validation_status / validation_errors, safety-stamp enforcement, prompt versioning, 28 tests. |
| **Next 30 days** | Wire the schema's `validate_ai_interpretation_payload` into the existing `signal_inbox_api.ai_summary` path so its persisted payload uses the canonical shape. |
| **Next 60 days** | Eval harness: record `validation_status` distribution per prompt version; surface in `/source-health/summary`. |
| **Next 90 days** | Calibration: hold-out comparison between AI summary and the operator's manual reflection; calibration delta as an observable metric. |
| **Not on the roadmap** | AI-driven execution. Ever. |

---

## 11. Decision thresholds (mathematical form)

```
Private_Beta_Go =
    Real_Auth_Design_Complete           # done (Day 32)
    ∧ User_Isolation_Design_Complete    # done (Day 32)
    ∧ Hosted_Deployment_Proof           # required, not done
    ∧ Backup_Restore_Proof              # done locally; hosted version required
    ∧ E2E_Canonical_Flow_Passes         # partial (backend coverage only)
    ∧ Legal_Privacy_Notes_Complete      # done (Day 27)
    ∧ Live_Source_Refresh_Health_Visible # done (Day 28–29)

Public_Launch_Go =
    Private_Beta_Go
    ∧ Production_Monitoring             # not done
    ∧ Legal_Review                      # not done
    ∧ Source_ToS_Clearance              # checklist exists, not cleared
    ∧ Security_Review                   # not done
    ∧ User_Support_Process              # not designed
    ∧ Incident_Response_Process         # planned (Day 34)
```

`Private_Beta_Go` evaluates to **false** today because hosted deployment is
unproven and e2e coverage is partial.

`Public_Launch_Go` evaluates to **false** today by a wide margin.

That is the honest answer and the right answer.

---

## 12. The single 30-day commitment

**Ship the local-first showcase publicly on GitHub with a 5-minute demo,
keep `--dry-run` as the default everywhere, and resist the urge to claim
production-readiness in the README.**

Everything else is a distraction.
