# Architecture

> The technical map of the sleeping-passenger MVP. Paired with `SHOWCASE.md`
> (product story) and `docs/PERSISTENCE_MODEL.md` (data truth model).

---

## 1. System architecture

```mermaid
flowchart LR
    subgraph Sources[Live Source Families]
        Poly[Polymarket]
        GDELT[GDELT]
        EDGAR[SEC EDGAR]
        NewsAPI[NewsAPI]
        EventReg[Event Registry]
        Etherscan[Etherscan]
        Grok[Grok/xAI]
        MD[Market Data]
        India[India NSE/RBI/SEBI]
        GF[Global Filings]
        AD[Asia Disclosure]
    end
    Orchestrator[run_live_refresh.py<br/>--dry-run default]
    Registry[live_source_registry.py]
    Phase1[run_live_sources_phase1.py]
    Phase2[run_live_sources_phase2.py]
    AISchema[ai_output_schema.py]
    Persistence[persistence.py]
    DB[(runtime/mvp_local.db)]
    API[FastAPI api_server.py]
    Front[Next.js dashboard]
    Backup[backup_db.py / restore_db.py]
    BackupDir[(runtime/backups/)]
    Sched[Windows Task Scheduler / cron<br/>every 6h]

    Sched --> Orchestrator
    Orchestrator --> Registry
    Orchestrator --> Phase1
    Orchestrator --> Phase2
    Phase1 --> Poly
    Phase1 --> GDELT
    Phase1 --> EDGAR
    Phase2 --> NewsAPI
    Phase2 --> EventReg
    Phase2 --> Etherscan
    Phase2 --> Grok
    Phase2 --> MD
    Phase2 --> India
    Phase2 --> GF
    Phase2 --> AD
    Phase1 --> Persistence
    Phase2 --> Persistence
    Grok --> AISchema
    AISchema --> Persistence
    Persistence --> DB
    Persistence --> Backup
    Backup --> BackupDir
    API --> Persistence
    Front --> API
```

---

## 2. Canonical workflow

```mermaid
flowchart TD
    Start([Start app]) --> Health[Verify backend / DB / safety health]
    Health --> Refresh[Refresh or inspect live signals]
    Refresh --> Inbox[Review signal inbox]
    Inbox --> Detail[Inspect signal detail]
    Detail --> Reflect[Reflect / validate / discuss]
    Reflect --> Decide[Human manual decision]
    Decide --> LogTrade[Log manual trade]
    LogTrade --> Reconcile[Reconcile outcome]
    Reconcile --> Moltbook[Learn through Moltbook]
    Moltbook --> Export[Export / review history]
    Export --> Backup[Back up DB]
    Backup --> Restore{Restore needed?}
    Restore -- Yes --> RestoreFlow[Run restore_db.py --dry-run first]
    Restore -- No --> Loop[Loop on next signal]
    RestoreFlow --> Loop
```

---

## 3. Safety invariant path

```mermaid
flowchart LR
    Input[Any incoming AI / signal / refresh payload] --> Stamp[Apply advisory safety stamps]
    Stamp --> Schema[Validate against schema or registry]
    Schema --> Route[Route response]
    Route --> Lock{Safety lock<br/>execution_gate = LOCKED}
    Lock --> Persist[Persist with stamps]
    Persist --> SurfaceUI[Surface in dashboard with stamps visible]
    Lock --> NeverExec[No broker call, no execution surface exists]
```

Every step asserts:

```
advisory_status          = "ADVISORY_ONLY"
execution_gate           = "LOCKED"
broker_api_called        = false
ai_execution_count       = 0
broker_order_id          = "NONE"
human_execution_required = true
```

---

## 4. Persistence model

```mermaid
erDiagram
    SIGNAL_EVENTS ||--o{ SIGNAL_DECISIONS : has
    SIGNAL_EVENTS ||--o{ USER_REFLECTIONS : has
    SIGNAL_EVENTS ||--o{ AI_DISCUSSION_SUMMARIES : has
    SIGNAL_DECISIONS ||--o{ MANUAL_TRADES : produces
    MANUAL_TRADES ||--o{ RECONCILIATION_RESULTS : reconciled_by
    USER_REFLECTIONS ||--o{ MOLTBOOK_ENTRIES : feeds
    AI_DISCUSSION_SUMMARIES ||--o{ MOLTBOOK_ENTRIES : feeds
    LIVE_SOURCE_RUNS }o--|| SIGNAL_EVENTS : refreshed_by

    SIGNAL_EVENTS {
        text event_id PK
        text source_name
        text symbol
        text title
        text payload_json
        text advisory_status
        bool broker_api_called
        int ai_execution_count
        text execution_gate
        datetime created_at
    }
    SIGNAL_DECISIONS {
        text decision_id PK
        text event_id FK
        text status
        text rationale
        datetime created_at
    }
    USER_REFLECTIONS {
        text reflection_id PK
        text event_id FK
        text body
        datetime created_at
    }
    AI_DISCUSSION_SUMMARIES {
        text summary_id PK
        text event_id FK
        text payload_json
        text validation_status
        text prompt_version
        datetime created_at
    }
    MANUAL_TRADES {
        text trade_id PK
        text decision_id FK
        text symbol
        text side
        real quantity
        real price
        datetime executed_at
    }
    RECONCILIATION_RESULTS {
        text reconciliation_id PK
        text trade_id FK
        text status
        text notes
        datetime reconciled_at
    }
    MOLTBOOK_ENTRIES {
        text entry_id PK
        text source_kind
        text source_id
        text body
        datetime created_at
    }
    LIVE_SOURCE_RUNS {
        text run_id PK
        text source_name
        text status
        int fetched_count
        text error_message
        datetime timestamp_utc
    }
```

Full truth model: `docs/PERSISTENCE_MODEL.md`.

---

## 5. Live signals refresh model

```mermaid
sequenceDiagram
    autonumber
    participant Sched as Scheduler<br/>(Task Scheduler / cron)
    participant Orch as run_live_refresh.py
    participant Reg as live_source_registry
    participant Run1 as run_live_sources_phase1.py
    participant Run2 as run_live_sources_phase2.py
    participant DB as SQLite live_source_runs

    Sched->>Orch: trigger every 6h (--dry-run default)
    Orch->>Reg: list_live_source_families()
    Orch->>Reg: detect_source_credential_state(env)
    loop per source
        alt phase1 source
            Orch->>Run1: invoke --source <key> --dry-run|--write
        else phase2 source
            Orch->>Run2: invoke --source <key> --dry-run|--write
        end
        Run1->>DB: row(status, fetched_count, error_message)
        Run2->>DB: row(status, fetched_count, error_message)
    end
    Orch-->>Sched: structured report (JSON or text)
```

---

## 6. Component map

| Component | File(s) | Responsibility |
|---|---|---|
| API server | `scripts/api_server.py` | FastAPI routes (`/health`, `/api/version`, `/db/status`, `/signals`, `/manual-trades`, `/reconciliation`, `/moltbook`, `/source-health/summary`, `/exports/*.csv`) |
| Signal inbox API | `scripts/signal_inbox_api.py` | signal listing, AI summary, decision/reflection capture |
| Moltbook API | `scripts/moltbook_api.py` | Moltbook learning journal |
| Persistence | `scripts/persistence.py` | SQLite read/write, WAL, busy-timeout, foreign-key hardening |
| AI output schema | `scripts/ai_output_schema.py` | canonical AI payload contract, safety overrides, secret redaction |
| Live source registry | `scripts/live_source_registry.py` | 11 source families, credential state, 6h cadence |
| Refresh orchestrator | `scripts/run_live_refresh.py` | dry-run-safe 6h refresh CLI |
| Phase1 runner | `scripts/run_live_sources_phase1.py` / `live_source_runner.py` | Polymarket / GDELT / SEC EDGAR |
| Phase2 runner | `scripts/run_live_sources_phase2.py` / `live_source_runner_phase2.py` | the other 8 families |
| Source health | `scripts/source_health_summary.py` | per-source severity, category, redacted error text |
| Backup | `scripts/backup_db.py` / `restore_db.py` | DB backup / non-destructive restore |
| Smoke check | `scripts/smoke_check.py` | one-shot health/version/db verification |
| Rate limiter | `scripts/rate_limiter.py` | request-rate protection |
| Frontend | `frontend/src/app/**/*.tsx` | Next.js dashboard, sidebar, signal pages, mock fallback |

---

## 7. What is intentionally **not** present

| Not present | Why |
|---|---|
| Broker SDK | No execution surface. Period. |
| Order placement code | Same. |
| Auto-trading scheduler | Same. |
| Public landing page / marketing site | Not a public product. |
| Real multi-user auth | Out of scope for a local-first MVP (designed in `docs/PRIVATE_BETA_AUTH_DESIGN.md`). |
| Hosted Postgres | Out of scope (planned in `docs/POSTGRES_MIGRATION_PLAN.md`). |
| Hosted deployment | Out of scope (planned in `docs/HOSTED_DEPLOYMENT_PLAN.md`). |
| Always-on refresh daemon | Refresh is operator-driven via cron / Task Scheduler. |
| Per-tick streaming | The 6-hour cadence is the right floor for advisory use. |
| Sport-archetype analogy modules in critical path | They exist as docs and engines for context; the canonical workflow does not require them. |

---

## 8. Deployment topology (local-first today)

```mermaid
flowchart LR
    User[Operator] --> Front[Next.js dev server :3000]
    Front --> API[FastAPI uvicorn :8000]
    API --> DB[(SQLite runtime/mvp_local.db)]
    Scheduler[Task Scheduler / cron] --> Orch[run_live_refresh.py]
    Orch --> Runners[phase1/phase2 runners]
    Runners --> DB
    Backup[backup_db.py] --> BackupDir[(runtime/backups/)]
```

For the hosted topology (private beta, when implemented), see
`docs/HOSTED_DEPLOYMENT_PLAN.md`.

---

## 9. Configuration surface

| Source | What | Notes |
|---|---|---|
| `.env` | API keys, `MVP_API_TOKEN`, `MVP_DB_PATH`, `SEC_USER_AGENT` | Never committed |
| `config/llm_provider_config.json` | Grok/xAI provider defaults | Overridable per-call |
| `config/external_data_config.json` | external adapter wiring | n/a for live refresh |
| `config/sources.yaml`, `config/external_adapters.yaml` | signal-source taxonomy | configurable |
| `config/thresholds.yaml` | scoring thresholds | configurable |

---

## 10. Operational guarantees

| Guarantee | Mechanism | Evidence |
|---|---|---|
| Safety stamps cannot be bypassed | `apply_advisory_safety_stamps()` overrides every unsafe field | `tests/test_ai_output_schema.py::test_invalid_payload_never_creates_action_permission` |
| Secrets never reach frontend | Registry returns `configured: bool` only | `tests/test_live_source_registry.py::test_credential_state_redacts_values_completely` |
| Failures are per-source | Orchestrator's `_classify_for_execution()` returns skip-not-fail | `tests/test_live_refresh_orchestrator.py::test_source_failure_does_not_abort_whole_run` |
| Backup is non-destructive | `restore_db.py` writes pre-restore backup before any overwrite | `tests/test_db_backup_restore.py` |
| Persistence is canonical | Single source of truth (SQLite) with documented schema | `docs/PERSISTENCE_MODEL.md` |
