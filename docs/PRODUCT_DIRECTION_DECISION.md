# Product Direction Decision — Day 26

> Force an explicit strategic decision about what this MVP **is** today, what
> it can honestly claim, and which next path is safe to pursue.

This document is the canonical strategic anchor for the Day 26–35 sprint. It is
deliberately conservative. Every score below is grounded in what the repo
actually contains today, not what the README aspires to.

---

## 0. Identity (non-negotiable)

This MVP is a **local-first advisory signal review, reflection, manual
decision, manual trade logging, reconciliation, and learning journal**.

It is NOT a broker, an execution engine, an auto-trading product, a public
SaaS, a portfolio manager, an investment adviser, or anything that places
orders. AI may interpret, summarize, classify, flag, validate, and produce
advisory hypotheses — never execute.

Safety invariants (must remain true on every commit):

```
ADVISORY_ONLY            = true
HUMAN_EXECUTION_REQUIRED = true
BROKER_ORDER_PERMISSION  = false
AI_EXECUTION             = 0
execution_gate           = "LOCKED"
broker_api_called        = false
ai_execution_count       = 0
broker_order_id          = "NONE"
```

---

## 1. The three honest paths

| Path | Readiness /10 | Required before claiming it | Biggest blocker | Recommendation |
|---|---:|---|---|---|
| **A — Local-first showcase MVP** | 8.0 | reproducible setup; backup/restore; 2950 backend tests; demo script; honest source registry + 6h refresh model; SHOWCASE doc; advisory-only stamps everywhere | trivial polish (screenshots, demo recording) | **PURSUE NOW** |
| **B — Controlled private beta** | 4.5 | real multi-user auth, per-user data isolation, hosted Postgres, hosted deployment, basic monitoring, legal/privacy notes, source-ToS clearance, e2e proof | no real auth, no hosted DB, no hosted deployment, no monitoring | **DESIGN-ONLY this sprint** |
| **C — Public production SaaS** | 1.5 | everything in B + legal review, security review, source-ToS legal clearance, incident response, performance work, support process | regulated-content surface, no compliance work done | **DO NOT PURSUE** |

---

## 2. Decision formulas

### 2a. Local showcase

```
If
    Demo_Repeatability   >= 8
    AND Safety_Invariants  >= 9
    AND Setup_Reproducibility >= 8
    AND Test_Reality        >= 7
Then
    Local_Showcase = true
```

Evaluation today:
- Demo_Repeatability = 8 (DEMO.md, smoke check, mock fallback, working FastAPI+Next.js stack)
- Safety_Invariants  = 9 (advisory stamps wired through every mutating route, ai_execution_count = 0 everywhere)
- Setup_Reproducibility = 8 (SETUP.md, Windows launcher, Docker scaffold, smoke_check.py)
- Test_Reality = 7.5 (2950 backend tests; frontend unit/e2e still partial)

**Local_Showcase = true.** This is what we ship as the deliverable.

### 2b. Private beta

```
If
    Real_Auth     < 7
    OR User_Isolation < 7
    OR Hosted_DB   < 7
    OR Monitoring   < 6
Then
    Public_Production = false
```

Evaluation today:
- Real_Auth = 4 (single-token bearer for local convenience only)
- User_Isolation = 1 (single-tenant SQLite, no users table, no per-user scoping)
- Hosted_DB = 1 (SQLite only; no Postgres implementation)
- Monitoring = 3 (logging exists; no metrics/alerting)

**Public_Production = false.** Private beta is design-only this sprint.

### 2c. Live signal confidence

```
If
    Source_Health_Visible    = false
    OR Last_Refresh_Visible    = false
    OR Credential_State_Visible = false
Then
    Live_Signal_Confidence < 7
```

Evaluation today (post-sprint additions):
- Source_Health_Visible: TRUE (`/source-health/summary` already present;
  `scripts/source_health_summary.py` already classifies and redacts)
- Last_Refresh_Visible: TRUE for phase1+phase2 (rows persist via
  `live_source_runs`)
- Credential_State_Visible: TRUE via the new `scripts/live_source_registry.py`
  (Day 28) without exposing secret values

**Live_Signal_Confidence ≈ 6.5–7.** Honest: not perfect, but no fake claims.

---

## 3. The recommendation

**Track A (Local Showcase) — yes, now. Track B (Private Beta) — design only.
Track C (Public SaaS) — not on the table.**

Why this is the right call:
1. The repo today contains a **working** local-first product. Inflating it
   into a private beta without auth or hosted DB would be embarrassing.
2. A clean, honest, well-documented local artifact is the highest-leverage
   thing to ship in 10 days.
3. Designing private-beta auth/postgres/hosted/monitoring now (without
   implementing) keeps the door open without taking on risk we cannot deliver.

---

## 4. What we will and will not do in this sprint

| Will do | Will not do |
|---|---|
| AI output validation schema + tests | Auto-execute trades or call brokers |
| Live source registry (11 families, redacted credentials) | Fake adapters or fabricate "latest data" |
| 6-hour refresh orchestrator wrapping existing runners (dry-run default) | Hidden always-on daemon |
| Windows Task Scheduler wrapper, cron example | Run paid APIs without explicit `--write` and user intent |
| Showcase, architecture, legal/privacy, scheduling, postgres, hosted-deployment, monitoring, private-beta-auth, final-scorecard docs | Implement real multi-user auth |
| Final acceptance checklist + scorecard | Implement Postgres |
| Tests using mocks/fixtures | Run live ingestion or write-mode refresh |

---

## 5. The single biggest claim we are honest about

> **This MVP is a local-first advisory journal that helps a single operator
> review signals, reflect, log manual trades, and reconcile outcomes. It is
> not a multi-user product, not hosted, not auto-executing, and not financial
> advice.**

Anything beyond that requires the work in
[[private-beta-auth-design]], [[postgres-migration-plan]], and
[[hosted-deployment-plan]] to be done first.
