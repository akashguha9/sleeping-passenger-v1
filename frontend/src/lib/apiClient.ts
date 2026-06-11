import { API_BASE } from './config';
import type { RealMoneyReadiness } from './realMoneyReadiness';
import type { CalibrationMap } from './calibrationMap';
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

// Hard ceiling on how long any single backend request may stay pending.
//
// Without this, a backend that accepts the TCP connection but never
// responds (a blocked/slow route, a stalled proxy) leaves `fetch` pending
// forever. Pages that `await Promise.all([...])` before clearing their
// `loading` flag then spin on "Loading…" indefinitely. Aborting after a
// bounded interval guarantees every request settles, so the existing
// per-call `try/catch` wrappers can fall back to null / mock instead of
// hanging the UI. Override with NEXT_PUBLIC_API_TIMEOUT_MS if needed.
const REQUEST_TIMEOUT_MS = (() => {
  const raw = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : 12_000;
})();

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = buildHeaders(init);
  // Per-request abort timer. If the caller already supplied a signal we
  // still layer our own timeout on top so a hung request can never escape
  // the ceiling.
  //
  // The timeout MUST cover the whole request — both the response headers
  // (fetch() resolving) AND the response body read. `fetch()` resolves as
  // soon as the status line + headers arrive; the body is streamed
  // afterwards. If we cleared the timer the instant fetch() resolved, a
  // backend that sent headers and then stalled the body would leave the
  // body read (res.json()/res.text()) pending forever — re-stranding the
  // page on "Loading…" even though the per-call wrappers fall back on
  // rejection. We therefore keep the timer armed until the body has been
  // fully consumed (success or error), clearing it only in `finally`.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      signal: init?.signal ?? controller.signal,
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
        const text = await res.text();
        const body = text ? JSON.parse(text) : undefined;
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
        // Non-JSON / empty body — keep the generic message.
      }
      throw new ApiHttpError(res.status, message, reason, detail);
    }
    // Success path. Read the body as text first so an EMPTY response body
    // (204 / Content-Length: 0) does not crash JSON parsing — return an
    // empty object so callers normalising `.items`/`.trades`/`.entries`
    // resolve to [] (an EMPTY state) rather than a thrown SyntaxError.
    // A non-empty body that is invalid JSON still throws, so the wrapper
    // falls back to its structured null/mock (an ERROR/offline state) per
    // the lifecycle contract — never an infinite spinner.
    const text = await res.text();
    if (!text) return {} as T;
    return JSON.parse(text) as T;
  } finally {
    clearTimeout(timer);
  }
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

// Market-physics simulator (advisory-only scoring; stateless, no order path).
// The response's `decision` field matches `SimulatorDecision` in
// `@/components/SimulatorVerdictCard`.
export async function postSimulatorEvaluate(
  payload: Record<string, unknown>,
): Promise<unknown> {
  return apiFetch('/simulator/evaluate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getSimulatorDoctrine(): Promise<unknown> {
  return apiFetch('/simulator/doctrine', { method: 'GET' });
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

export async function getMoltbook(): Promise<ApiResult<MoltbookListResponse>> {
  try {
    const raw = await apiFetch<Record<string, unknown>>('/moltbook');
    const items =
      ((raw.items as MoltbookEntry[] | undefined) ??
        (raw.entries as MoltbookEntry[] | undefined) ??
        []);
    const item_count = Number(raw.item_count ?? raw.entry_count ?? items.length);
    return { data: { items, item_count }, isMock: false };
  } catch {
    return {
      data: { items: MOCK_MOLTBOOK_ENTRIES, item_count: MOCK_MOLTBOOK_ENTRIES.length },
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

export async function getDbStatus(): Promise<DbStatusResponse | null> {
  try {
    return await apiFetch<DbStatusResponse>('/db/status');
  } catch {
    return null;
  }
}

export async function getRealMoneyReadiness(): Promise<RealMoneyReadiness | null> {
  try {
    return await apiFetch<RealMoneyReadiness>('/api/readiness/real-money');
  } catch {
    return null;
  }
}

export async function getCalibrationMap(): Promise<CalibrationMap | null> {
  try {
    return await apiFetch<CalibrationMap>('/api/calibration-map');
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
