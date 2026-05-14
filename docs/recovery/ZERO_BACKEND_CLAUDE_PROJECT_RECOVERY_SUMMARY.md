# Zero-Backend Claude Project — Recovery Summary

> Sanitized digest of what was found in the Claude data export at
> `C:\Users\akash\Downloads\Claude Data\` versus what already exists in
> this repository (local executable truth).
>
> **Doctrine**: Local repo is executable truth. The Claude export is
> design evidence only. No content from the export was injected into
> code blindly. No thesis material was injected into trading logic.

## Export inventory (what was actually in the export)

| File / folder | Size | Useful for MVP? | Note |
|---|---|---|---|
| `conversations.json` | ~71 MB, one-line JSON | partial | Contains the literal string "Zero-backend system architecture blueprint" exactly once (a chat reference). Other MVP keywords appear, but the file is one monolithic JSON line and cannot be sliced into individual conversations without a parser. Not imported into the repo. |
| `memories.json` | 7 KB | **yes — primary blueprint distillation** | Project memory for `//Sleeping Passenger` (uuid `01962ad6-…`) captures: 13 doctrine principles, LEAVE default, ATOM 35-core / 95-full dual layer, spot longs only, 10% stop, paper-trading phase, CHAOS_ENTRY classification. |
| `projects/01962ad3-…json` | small | no | "How to use Claude" starter project — irrelevant. |
| `projects/01962ad6-…json` | small | **no documents attached** | The user's MVP project named `//Sleeping Passenger`. `docs: []` — the Project Knowledge slot was empty at export time. There is no document literally titled "Zero-backend system architecture blueprint" attached to this project. |
| `users.json` | small | no | Account metadata only. |

### Verification result on the "Zero-backend system architecture blueprint" project

The literal project name described in the task does not exist in the export
as a discrete project entity. Two readings are consistent with the data:

1. The blueprint was authored as a Claude *Project* but its docs were
   not retained in the export (Anthropic exports of the project frame
   sometimes omit attached project knowledge, or the docs were never
   uploaded as project knowledge).
2. The blueprint was discussed in **conversations** rather than stored
   as project knowledge. The 71 MB `conversations.json` does contain
   the phrase once, suggesting at least one chat referenced it.

Either way, **the executable blueprint is the local repository plus the
`memories.json` digest**, not the export.

---

## A. What the Claude Project / memories.json claim the MVP should have

From the project-memory digest (`memories.json` → project_memories →
`01962ad6-…`):

- **Geopolitical Signal Pipeline V5.1+**, 250+ iteration sessions
- Thesis: *"attention precedes capital, capital follows narrative,
  narrative forms before price"*
- 13-principle governing doctrine, **LEAVE as default, ENTER as
  exception**
- **Spot longs only** — no shorts, no futures, no pre-market crypto
- 10% hard stop on all positions
- **ATOM dual-layer**: ~35 CORE fields (compact execution object) +
  95/150+ FULL fields (architecture document) — already reflected in
  the repo's safety-stamp/diagnostic split
- Signal sources: Polymarket Gamma API, Kalshi REST/WS
- AI/LLM: Grok API + Claude Haiku
- Persistence: Airtable / Supabase / Notion (planned), Apple Stocks for
  human tracker
- Frontend: Softr / Streamlit Cloud (planned); the live repo uses
  Next.js 14 instead — divergence noted
- Scoring layers: S0–S4, regime classifiers, game-theory tags
  (COIN/DICE/POKER/CHESS/COMBO/UNO), war-style tags, narrative
  maturity (PRE-NARRATIVE → SATURATION), PoNR framework
- **CHAOS_ENTRY** classification when entries happen against pipeline
  veto signals — pipeline integrity preserved by tracking the
  violation, not by hiding it
- Cross-model divergence scoring (`llm_curation_bias_flag`) is a
  required meta-layer (already partially reflected in
  `scripts/ai_output_schema.py` and `scripts/echo_risk_engine.py`)

## B. What appears relevant to current repo files

Match table — items from the export that map onto existing repo modules.
"Match strength" is the assessor's judgement after reading the file.

| Export concept | Existing repo file(s) | Match strength |
|---|---|---|
| 13-principle doctrine | `docs/SIGNAL_REACTOR_MODEL.md` §2 enumerates 13 one-line truths | strong |
| LEAVE as default | `scripts/signal_reactor.py` defaults to `COLD_OBSERVE`/`WARM_WATCH`; veto layer present | strong |
| Spot longs only / no broker | `scripts/signal_inbox_api.py` `_ADVISORY_STATUS`, `broker_api_called=False`, `ai_execution_count=0` | strong |
| ATOM 35/95 dual-layer | Safety-stamp pattern in every module; `signal_reactor.py` emits a compact decision payload + a `component_outputs` map | medium (concept rather than name match) |
| CHAOS_ENTRY tracking | `moltbook_*.py` family + manual_trade_log + reconciliation_results in `signal_inbox_api.py` | medium (mistake_tags / process_error fields already exist) |
| Polymarket / Kalshi adapters | `scripts/polymarket_clob_adapter.py`, `scripts/fetch_polymarket.py` | strong |
| Cross-model divergence / llm_curation_bias | `scripts/ai_output_schema.py`, `scripts/echo_risk_engine.py` | strong |
| Source independence | `scripts/echo_risk_engine.py` (independence_score) | strong |
| Narrative maturity | `scripts/narrative_*` family (`narrative_archetype_router`, `narrative_drift_monitor`, `narrative_inflation_index`) | strong |
| PoNR / point-of-no-return | `scripts/late_adoption_lockout.py`, `scripts/closure_deficit_monitor.py` | medium |
| Apple-Stocks-style portfolio tracker | not in repo by design — operator-external; not a code dependency | n/a |

## C. What appears unrelated or stale

- **Softr / Streamlit Cloud** frontend choice: superseded by the actual
  Next.js frontend in `frontend/`. Do not regress.
- **Make.com Core / GitHub Actions live phase**: there is no automation
  pipeline yet in this repo; the live phase has not started.
- **"S9 tooling build roadmap" with feedparser/PRAW/newspaper3k/KeyBERT/
  FinBERT etc.**: aspirational. No matching imports in the current
  scripts/ tree; introducing them now would add scope.
- **ATOM "retirement to 35 fields"** as a *codebase action item*: the
  spirit is already captured by the safety-stamp + diagnostic split.
  Renaming module fields to match the ATOM vocabulary would be
  cosmetic churn.

## D. What appears thesis-only and must NOT be injected into MVP code

A separate body of material in the export (in `memories.json` under
`conversations_memory`) belongs to the user's master's thesis at EBS
on **psychological ownership (PO) as a mediator between consumer
outcome-shaping (COS) and willingness to pay (WTP)**. This includes:

- thesis-quality scores (weighted ~7.6/10)
- methodology debates (between-subjects vs. within-subjects)
- randomisation methodology, manipulation checks
- PROCESS Model 4 bootstrapping
- 26-paper literature mapping in Excel; gap analysis document
- Jamovi / Excel methodology

This is **academic research**, not trading-system specification.

It may appear in this repo only as:

- documentation language (e.g. explaining the human-in-the-loop
  rationale)
- conceptual framing in `docs/PRODUCT_DIRECTION_DECISION.md` or
  positioning notes — only if explicitly requested by the user
- **never** as data schema, backend logic, or frontend behaviour

No thesis material was copied into source code as part of this
recovery sprint.

## E. What needs verification (open items)

1. The phrase "Zero-backend system architecture blueprint" appears
   once in `conversations.json`. The full surrounding conversation
   was not extracted into the repo. If the user wants the literal
   blueprint text, the next step is to script a one-line JSON parse
   of `conversations.json` filtered to that conversation only, then
   sanitize and place under `docs/recovery/` as a separate file. Not
   done in this sprint because the file is one 71 MB JSON line and
   the safer approach is operator-supervised extraction.
2. Whether the user has another local source of the literal blueprint
   text (`.docx` / `.txt` / Notion export) that should be merged in
   later.

---

## Cross-cutting safety statement

Every wiring change made in this recovery sprint:

- preserves `advisory_status == "ADVISORY_ONLY"`
- preserves `execution_gate == "LOCKED"`
- preserves `broker_api_called == False`
- preserves `ai_execution_count == 0`
- preserves `execution_permission == False`
- preserves `can_execute == False`

No broker call, no order placement, no auto-execution was introduced.
The Signal Reactor remains a *diagnostic* layer that produces labels,
not orders.
