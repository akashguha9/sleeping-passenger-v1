import { API_BASE } from './config';
import {
  MOCK_INBOX_RESPONSE,
  MOCK_MOLTBOOK_ENTRIES,
  getMockSignalDetail,
} from './mockData';
import type {
  InboxListResponse,
  InboxDiagnosticsResponse,
  SignalDetailResponse,
  MoltbookEntry,
  ManualTradeListResponse,
  SourceHealthResponse,
  SourceHealthSummaryResponse,
  LiveSourcesStatusResponse,
  DbStatusResponse,
  LiveSignalsResponse,
  ChartStructureResponse,
  ChartBootstrapResponse,
  SecuritySearchResponse,
  SecurityDetailResponse,
  SecurityCoverageResponse,
  ReconciliationQueueResponse,
  LearningCompletenessResponse,
  KalshiSourceHealthResponse,
  WatchdogSummaryResponse,
} from '@/types';

export interface HealthResponse {
  status: string;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  version: string;
  // Day 11-25 additions — optional so older mock fixtures still type-check.
  db_available?: boolean;
  db_path?: string;
  api_token_required?: boolean;
  environment?: string;
  rate_limit_enabled?: boolean;
  max_request_bytes?: number;
  security_headers_enabled?: boolean;
}

export interface ApiResult<T> {
  data: T;
  isMock: boolean;
}

export interface MoltbookListResponse {
  items: MoltbookEntry[];
  item_count: number;
  raw_total_entries?: number;
  visible_entries?: number;
  hidden_ineligible?: number;
  hidden_duplicates?: number;
  hidden_test_demo?: number;
  hidden_unconfirmed?: number;
  hidden_cross_source_duplicates?: number;
  visibility_reasons?: Record<string, number>;
  allowed_event_types?: string[];
  include_raw?: boolean;
  raw_debug_available?: boolean;
  default_view_notice?: string;
}

// Sprint 8.1 — local-only operator-token support.
//
// When `MVP_API_TOKEN` is set on the backend, mutating POST routes
// require an `Authorization: Bearer <token>` header.  The token is
// stored in **sessionStorage** (cleared when the tab closes) under
// `mvp_api_token` and is NEVER committed, NEVER exposed via
// `NEXT_PUBLIC_*`, and NEVER logged.  GET requests do not send the token
// by default — it is attached only to non-GET methods.
//
// Token-mode is local operator convenience, NOT a SaaS auth scheme.
// Setting a token does not authorise trades; the backend always returns
// `execution_gate=LOCKED` and `broker_api_called=false`.
const TOKEN_STORAGE_KEY = 'mvp_api_token';

export function getStoredApiToken(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredApiToken(token: string): void {
  if (typeof window === 'undefined') return;
  try {
    const trimmed = token.trim();
    if (!trimmed) {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    } else {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
    }
  } catch {
    // sessionStorage may be unavailable (private mode, SSR, etc.) — no-op.
  }
}

export function clearStoredApiToken(): void {
  if (typeof window === 'undefined') return;
  try {
    window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // no-op
  }
}

export function hasStoredApiToken(): boolean {
  return Boolean(getStoredApiToken());
}

function buildHeaders(init?: RequestInit): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const method = (init?.method ?? 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD') {
    const token = getStoredApiToken();
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }
  return headers;
}

export class ApiTokenRequiredError extends Error {
  status: number;
  constructor(status = 401) {
    super(
      'Write endpoint requires local MVP_API_TOKEN. Set the token for this browser session before retrying. This token does not authorize trade execution.',
    );
    this.name = 'ApiTokenRequiredError';
    this.status = status;
  }
}

// Backend FastAPI routes return structured error detail JSON for refused
// or not-found writes (see /manual-trades/{id}/cancel).  Surfacing the
// `reason` field lets the UI show "This trade has been reconciled"
// instead of the generic "HTTP 400 — kept" the user was complaining
// about.  All fields are optional and the class falls back to the bare
// status when the backend (or a proxy) returns a plain string body.
export class ApiHttpError extends Error {
  status: number;
  reason?: string;
  detail?: unknown;
  constructor(status: number, message: string, reason?: string, detail?: unknown) {
    super(message || `HTTP ${status}`);
    this.name = 'ApiHttpError';
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = buildHeaders(init);
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
  });
  if (res.status === 401 || res.status === 403) {
    throw new ApiTokenRequiredError(res.status);
  }
  if (!res.ok) {
    // FastAPI wraps HTTPException(detail=...) under a "detail" key.  The
    // cancel/reconcile routes now ship a structured object with
    // `message` and `reason` — extract them when present so callers can
    // render the actual cause.  If parsing fails we fall back to the
    // generic "HTTP <status>" string, preserving prior behaviour.
    let message = `HTTP ${res.status}`;
    let reason: string | undefined;
    let detail: unknown;
    try {
      const body = await res.json();
      detail = body;
      const raw = (body && typeof body === 'object' && 'detail' in (body as Record<string, unknown>))
        ? (body as { detail: unknown }).detail
        : body;
      if (raw && typeof raw === 'object') {
        const obj = raw as { message?: unknown; reason?: unknown; error?: unknown };
        if (typeof obj.message === 'string' && obj.message) {
          message = obj.message;
        } else if (typeof obj.error === 'string' && obj.error) {
          message = obj.error;
        }
        if (typeof obj.reason === 'string' && obj.reason) {
          reason = obj.reason;
        }
      } else if (typeof raw === 'string' && raw) {
        message = raw;
      }
    } catch {
      // Non-JSON body — keep the generic message.
    }
    throw new ApiHttpError(res.status, message, reason, detail);
  }
  return res.json() as Promise<T>;
}

export async function checkHealth(): Promise<HealthResponse | null> {
  try {
    return await apiFetch<HealthResponse>('/health');
  } catch {
    return null;
  }
}

export async function getSignals(
  limit = 50,
  hours = 72,
): Promise<ApiResult<InboxListResponse>> {
  try {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('hours', String(hours));
    const data = await apiFetch<InboxListResponse>(`/signals?${params.toString()}`);
    return { data, isMock: false };
  } catch {
    return {
      data: { ...MOCK_INBOX_RESPONSE, mock_fallback: true, signal_source: 'mock' },
      isMock: true,
    };
  }
}

export async function getSignalsDiagnostics(
  hours = 72,
): Promise<InboxDiagnosticsResponse | null> {
  try {
    const params = new URLSearchParams();
    params.set('hours', String(hours));
    return await apiFetch<InboxDiagnosticsResponse>(
      `/signals/diagnostics?${params.toString()}`,
    );
  } catch {
    return null;
  }
}

export async function getSignalDetail(eventId: string): Promise<ApiResult<SignalDetailResponse>> {
  try {
    const data = await apiFetch<SignalDetailResponse>(`/signals/${encodeURIComponent(eventId)}`);
    return { data, isMock: false };
  } catch {
    return { data: getMockSignalDetail(eventId), isMock: true };
  }
}

export async function validateSignal(eventId: string): Promise<unknown> {
  return apiFetch(`/signals/${encodeURIComponent(eventId)}/validate`, { method: 'POST' });
}

export async function postReflection(
  eventId: string,
  reflection_text: string,
  conviction_level: string,
  author = 'human',
): Promise<unknown> {
  return apiFetch(`/signals/${encodeURIComponent(eventId)}/reflection`, {
    method: 'POST',
    body: JSON.stringify({ reflection_text, author, conviction_level }),
  });
}

export async function postAiSummary(
  eventId: string,
  summary_text: string,
  model_label = 'AI_ADVISORY',
): Promise<unknown> {
  return apiFetch(`/signals/${encodeURIComponent(eventId)}/ai-summary`, {
    method: 'POST',
    body: JSON.stringify({ summary_text, model_label }),
  });
}

export async function postDecision(eventId: string, status: string): Promise<unknown> {
  return apiFetch(`/signals/${encodeURIComponent(eventId)}/decision`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  });
}

export async function postManualTrade(body: {
  event_id: string;
  ticker: string;
  side: string;
  quantity: number;
  price: number;
  thesis: string;
  notes?: string;
  logged_by?: string;
  leverage?: number;
  // Operator-discipline journal fields. All optional — older clients still work.
  invalidation_level?: string;
  expected_horizon?: string;
  risk_reason?: string;
  entry_reason?: string;
  exit_plan?: string;
  confidence_before?: number | null;
  emotional_state?: string;
  mistake_tags?: string;
  lesson?: string;
  // Sprint I — Native currency the operator selected.  Optional on
  // the wire so older callers stay valid; the backend normalises
  // unsupported codes to '' (UNKNOWN) rather than silently defaulting.
  currency?: string;
  // Free-text operator label naming which AI / model / source produced
  // the signal the operator acted on (e.g. "GPT-5.5", "Claude Code",
  // "Grok", "Gemini", "DeepSeek", "Perplexity", "Copilot",
  // "Human-only", "Multi-model consensus").  Optional; backend stores
  // verbatim (trimmed, length-capped at 120).  Storing this NEVER
  // grants execution permission.
  ai_model_used?: string;
}): Promise<unknown> {
  return apiFetch('/manual-trades', {
    method: 'POST',
    body: JSON.stringify({ logged_by: 'human', leverage: 1.0, ...body }),
  });
}

export async function reconcileTrade(
  tradeId: string,
  body: {
    actual_fill_price: number;
    actual_quantity: number;
    outcome_notes?: string;
    pnl_estimate?: number;
    outcome_status?: string;
    outcome_quality?: string;
    process_error?: string;
    process_error_notes?: string;
    mistake_tags?: string;
    lesson?: string;
    // Sprint H — Reconciliation productisation.  All optional; the
    // backend (signal_inbox_api.reconcile_trade) feeds these into
    // reconciliation_extras to compute realized P/L, set runner_status,
    // and serialise a structured outcome into outcome_notes.  Record-
    // keeping only — broker_api_called stays false, ai_execution_count
    // stays 0.
    post_trade_outcome?: string;
    reconciliation_status?: string;
    runner_quantity?: number | null;
    runner_status?: string;
    partial_take_profit_price?: number | null;
    partial_take_profit_quantity?: number | null;
    take_profit_plan?: string;
    stop_loss_price?: number | null;
    stop_loss_hit?: boolean;
    exit_reason?: string;
    invalidation_level?: string;
    lesson_takeaway?: string;
    notes?: string;
  },
): Promise<unknown> {
  return apiFetch(`/manual-trades/${encodeURIComponent(tradeId)}/reconcile`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

// Soft-cancel a duplicate / mis-logged manual trade log entry.  This is
// record-keeping only — the backend route NEVER calls a broker, NEVER
// cancels a real order, and NEVER changes ai_execution_count.  It only
// flips the local journal row's reconciliation_status so it stops
// appearing in the "Awaiting Reconciliation" queue.
export async function cancelManualTradeLog(
  tradeId: string,
  body: { reason?: string; status?: string } = {},
): Promise<unknown> {
  return apiFetch(`/manual-trades/${encodeURIComponent(tradeId)}/cancel`, {
    method: 'POST',
    body: JSON.stringify({
      reason: body.reason ?? '',
      status: body.status ?? 'CANCELLED_DUPLICATE',
    }),
  });
}

export async function getLearningCompleteness(
  limit = 50,
): Promise<LearningCompletenessResponse | null> {
  try {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    return await apiFetch<LearningCompletenessResponse>(
      `/learning-completeness?${params.toString()}`,
    );
  } catch {
    return null;
  }
}

export interface CockpitPartialFailure {
  subreport: string;
  status?: string;
  error_type: string;
  safe_recovery_command?: string | null;
}

export interface CockpitResponse {
  report: string;
  advisory_disclaimer: string;
  // Diagnostics integrity / degraded-state taxonomy (Kanté Task 6).  All
  // optional so older mock fixtures still type-check.
  status?: 'CLEAN' | 'WARN' | 'BLOCK' | 'DEGRADED' | 'UNKNOWN' | string;
  degraded_state?: string;
  cache_status?: string;
  cache_role?: string;
  canonical_truth_source?: string;
  generated_at_utc?: string | null;
  diagnostics_health?: number | null;
  partial_failures?: CockpitPartialFailure[];
  // Operator-guard coverage (advisory).
  auth_guard_status?: string | null;
  mutation_guard_coverage?: number | null;
  mutation_guard_release_impact?: string | null;
  mutation_scripts_unguarded_count?: number | null;
  closed_loop: {
    closed_loop_coverage: number;
    signals_without_outcomes: number;
    manual_trades_without_reconciliation: number;
    closed_losses_without_moltbook: number;
    unresolved_repair_debt: number;
  };
  learning_efficiency: Record<string, number | boolean>;
  truth_purity: {
    truth_purity_score: number;
    fake_rows_detected: number;
    release_gate_passed: boolean;
  };
  source_independence: { cohort_count: number; flagged_cohorts: string[] };
  broken_windows: {
    repair_debt_score: number;
    release_gate_impact: string;
    recommended_next_repair: string;
  };
  defensive_alpha: {
    total_defensive_events: number;
    fake_data_rows_blocked: number;
    closed_losses_captured_as_lessons: number;
  };
  invariants: Record<string, boolean>;
  advisory_status: string;
  broker_api_called: boolean;
  ai_execution_count: number;
}

export async function getDiagnosticsCockpit(): Promise<CockpitResponse | null> {
  try {
    return await apiFetch<CockpitResponse>('/diagnostics/cockpit');
  } catch {
    return null;
  }
}

export async function getReconciliationQueue(
  limit = 100,
): Promise<ReconciliationQueueResponse | null> {
  try {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    return await apiFetch<ReconciliationQueueResponse>(
      `/self-test/reconciliation-queue?${params.toString()}`,
    );
  } catch {
    return null;
  }
}

export async function getMoltbook(
  options?: { includeRaw?: boolean },
): Promise<ApiResult<MoltbookListResponse>> {
  try {
    const qs = options?.includeRaw ? '?include_raw=true' : '';
    const raw = await apiFetch<Record<string, unknown>>(`/moltbook${qs}`);
    const items =
      ((raw.items as MoltbookEntry[] | undefined) ??
        (raw.entries as MoltbookEntry[] | undefined) ??
        []);
    const item_count = Number(raw.item_count ?? raw.entry_count ?? items.length);
    return {
      data: {
        items,
        item_count,
        raw_total_entries: Number(raw.raw_total_entries ?? items.length),
        visible_entries: Number(raw.visible_entries ?? items.length),
        hidden_ineligible: Number(raw.hidden_ineligible ?? 0),
        hidden_duplicates: Number(raw.hidden_duplicates ?? 0),
        hidden_test_demo: Number(raw.hidden_test_demo ?? 0),
        hidden_unconfirmed: Number(raw.hidden_unconfirmed ?? 0),
        hidden_cross_source_duplicates: Number(
          raw.hidden_cross_source_duplicates ?? 0,
        ),
        visibility_reasons:
          (raw.visibility_reasons as Record<string, number> | undefined) ?? {},
        allowed_event_types: (raw.allowed_event_types as string[] | undefined) ?? [],
        include_raw: Boolean(raw.include_raw),
        raw_debug_available: Boolean(raw.raw_debug_available ?? true),
        default_view_notice: (raw.default_view_notice as string | undefined) ?? '',
      },
      isMock: false,
    };
  } catch {
    return {
      data: {
        items: MOCK_MOLTBOOK_ENTRIES,
        item_count: MOCK_MOLTBOOK_ENTRIES.length,
        raw_total_entries: MOCK_MOLTBOOK_ENTRIES.length,
        visible_entries: MOCK_MOLTBOOK_ENTRIES.length,
        hidden_ineligible: 0,
        hidden_duplicates: 0,
        hidden_test_demo: 0,
        hidden_unconfirmed: 0,
        hidden_cross_source_duplicates: 0,
        visibility_reasons: {},
        allowed_event_types: [],
        include_raw: false,
        raw_debug_available: true,
        default_view_notice:
          'Moltbook default view hides duplicates, test/demo fixtures, and unconfirmed closed-trade rows.',
      },
      isMock: true,
    };
  }
}

export async function postMoltbook(body: {
  event_id: string;
  ticker: string;
  original_signal_thesis: string;
  ai_interpretation: string;
  user_reflection: string;
  final_human_decision: string;
  manual_trade_log_id?: string;
  outcome?: string;
  mistake_type: string;
  lesson_learned: string;
  bias_detected?: string;
  recalibration_note?: string;
  future_rule_update?: string;
}): Promise<unknown> {
  return apiFetch('/moltbook', { method: 'POST', body: JSON.stringify(body) });
}

export async function getManualTrades(
  options?: { origin?: 'manual_trade_log' | 'all' | string },
): Promise<ManualTradeListResponse | null> {
  // Manual Trade Log surface contract: NEVER show seed / demo / fixture /
  // probe / paper-import rows.  We always send origin=manual_trade_log
  // unless the caller explicitly asks for the audit scope ("all").  The
  // backend defaults to the same value (defence in depth), so even if the
  // query param were ever dropped on the way out the response stays clean.
  const origin = options?.origin ?? 'manual_trade_log';
  const params = new URLSearchParams();
  params.set('origin', origin);
  const path = `/manual-trades?${params.toString()}`;
  try {
    return await apiFetch<ManualTradeListResponse>(path);
  } catch {
    return null;
  }
}

export async function getSourceHealth(): Promise<SourceHealthResponse | null> {
  try {
    return await apiFetch<SourceHealthResponse>('/source-health');
  } catch {
    return null;
  }
}

export async function getSourceHealthSummary(): Promise<SourceHealthSummaryResponse | null> {
  try {
    return await apiFetch<SourceHealthSummaryResponse>('/source-health/summary');
  } catch {
    return null;
  }
}

export async function getLiveSourcesStatus(): Promise<LiveSourcesStatusResponse | null> {
  try {
    return await apiFetch<LiveSourcesStatusResponse>('/live-sources/status');
  } catch {
    return null;
  }
}

/**
 * Fetch the refresh-watchdog summary written by the 30-minute scheduled
 * task (or the on-demand CLI).  The backend route is read-only and
 * returns a truthful ``status=MISSING`` payload when no watchdog summary
 * exists — the cockpit panel renders that as "watchdog never ran"
 * rather than pretending healthy.  This call never authorises trades.
 */
export async function getWatchdogSummary(): Promise<WatchdogSummaryResponse | null> {
  try {
    return await apiFetch<WatchdogSummaryResponse>('/source-health/watchdog');
  } catch {
    return null;
  }
}

/**
 * Fetch the sanitized Kalshi source-health summary that backs the
 * operator-truth panel.  The backend reads
 * ``runtime/release/kalshi_source_health.json`` and strips any
 * auth-bearing keys before serving it.  This fetch returns ``null``
 * on any failure so the page can degrade gracefully.
 */
export async function getKalshiSourceHealth(): Promise<KalshiSourceHealthResponse | null> {
  try {
    return await apiFetch<KalshiSourceHealthResponse>('/kalshi/source-health');
  } catch {
    return null;
  }
}

export async function getDbStatus(): Promise<DbStatusResponse | null> {
  try {
    return await apiFetch<DbStatusResponse>('/db/status');
  } catch {
    return null;
  }
}

export async function getLiveSignals(
  source?: string,
  limit = 100,
): Promise<LiveSignalsResponse | null> {
  try {
    const params = new URLSearchParams();
    if (source) params.set('source', source);
    params.set('limit', String(limit));
    return await apiFetch<LiveSignalsResponse>(`/live-signals?${params.toString()}`);
  } catch {
    return null;
  }
}

export async function getChartStructure(
  symbol: string,
  limit = 100,
  sourceEventId?: string,
): Promise<ChartStructureResponse | null> {
  try {
    const params = new URLSearchParams();
    params.set('symbol', symbol);
    params.set('limit', String(limit));
    if (sourceEventId) params.set('source_event_id', sourceEventId);
    return await apiFetch<ChartStructureResponse>(`/chart-structure?${params.toString()}`);
  } catch {
    return null;
  }
}

export async function bootstrapChartSymbol(
  symbol: string,
  period: string = 'max',
  interval: string = '1d',
): Promise<ChartBootstrapResponse | null> {
  try {
    return await apiFetch<ChartBootstrapResponse>('/chart-structure/bootstrap-symbol', {
      method: 'POST',
      body: JSON.stringify({ symbol, period, interval }),
    });
  } catch {
    return null;
  }
}

export async function searchSecurities(
  q: string,
  limit = 20,
): Promise<SecuritySearchResponse | null> {
  try {
    const params = new URLSearchParams({ q, limit: String(limit) });
    return await apiFetch<SecuritySearchResponse>(`/securities/search?${params.toString()}`);
  } catch {
    return null;
  }
}

export async function getSecurityDetail(symbol: string): Promise<SecurityDetailResponse | null> {
  try {
    return await apiFetch<SecurityDetailResponse>(
      `/securities/${encodeURIComponent(symbol)}`,
    );
  } catch {
    return null;
  }
}

export async function getSecurityCoverage(
  symbol: string,
): Promise<SecurityCoverageResponse | null> {
  try {
    return await apiFetch<SecurityCoverageResponse>(
      `/securities/${encodeURIComponent(symbol)}/coverage`,
    );
  } catch {
    return null;
  }
}

// Advisory-only operator refresh button — sprint Phase 4.
//
// Calls POST /api/live-refresh/run and returns the structured truth
// envelope (last run summary + locked status).  The backend NEVER
// triggers an actual network refresh from the HTTP path; it surfaces
// the artifact written by scripts/operator_live_provider_refresh.py.
//
// Setting an MVP_API_TOKEN does not authorise execution; the response
// always carries execution_gate=LOCKED and broker_api_called=false.
export interface LiveRefreshSourceResult {
  source: string;
  status: 'SUCCESS' | 'PARTIAL' | 'FAILED' | 'SKIPPED' | 'MOCK_UNAVAILABLE' | string;
  rows_written: number;
  skipped: boolean;
  error_redacted: string;
}

export interface LiveRefreshRunResponse {
  advisory_status: 'ADVISORY_ONLY' | string;
  execution_gate: 'LOCKED' | string;
  broker_api_called: boolean;
  ai_execution_count: number;
  refresh_status:
    | 'SUCCESS'
    | 'PARTIAL'
    | 'FAILED'
    | 'SKIPPED'
    | 'MOCK_UNAVAILABLE'
    | string;
  sources_attempted: number;
  sources_succeeded: number;
  sources_skipped: number;
  sources_failed: number;
  rows_written: number;
  started_at_utc: string | null;
  finished_at_utc: string | null;
  source_results: LiveRefreshSourceResult[];
  // Backwards-compat fields from the legacy locked envelope.
  ok?: boolean;
  error?: string;
  blocking_reasons?: string[];
  warnings?: string[];
  last_run_present?: boolean;
  last_run_path?: string;
}

export async function runLiveRefresh(): Promise<LiveRefreshRunResponse> {
  return apiFetch<LiveRefreshRunResponse>('/api/live-refresh/run', {
    method: 'POST',
  });
}

// External-evidence reliability — read-only advisory-only surface.
//
// Fetches GET /external-evidence/reliability.  The backend route never
// mutates state, never calls a broker, and returns an honest DISABLED /
// NO_PAYLOAD envelope when external adapters are off (the default).  The
// response is shaped so it can be passed straight to the
// ExternalEvidenceReliabilityCard as its `bundle` prop.  Returns null on
// any failure so the page can render its offline notice.
export interface ExternalEvidenceReliabilityResponse {
  status: 'OK' | 'DISABLED' | 'NO_PAYLOAD' | 'ERROR_SAFE' | string;
  mode: string;
  decision_impact: string;
  source?: string;
  artifact_present?: boolean;
  real_money_sizing_impact: string;
  real_money_weight_allowed: boolean;
  human_execution_required: boolean;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  external_evidence_status?: string;
  external_evidence_enabled?: boolean;
  external_evidence_decision_impact?: string;
  external_evidence_accepted_count?: number;
  external_evidence_score_delta_raw_uncalibrated?: number | null;
  external_evidence_score_delta_paper_calibrated?: number | null;
  external_evidence_score_delta_final?: number | null;
  external_evidence_calibration?: Record<string, unknown> | null;
  external_evidence_items?: unknown[];
  external_evidence_operator_readiness?: Record<string, unknown> | null;
}

export async function getExternalEvidenceReliability(): Promise<ExternalEvidenceReliabilityResponse | null> {
  try {
    return await apiFetch<ExternalEvidenceReliabilityResponse>(
      '/external-evidence/reliability',
    );
  } catch {
    return null;
  }
}

export function getCsvExportUrl(
  type:
    | 'signal-inbox'
    | 'reflections'
    | 'manual-trades'
    | 'reconciliation'
    | 'moltbook'
    | 'source-health',
): string {
  return `${API_BASE}/exports/${type}.csv`;
}
