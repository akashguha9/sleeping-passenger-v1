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
  DbStatusResponse,
  LiveSignalsResponse,
  ChartStructureResponse,
  ChartBootstrapResponse,
  SecuritySearchResponse,
  SecurityDetailResponse,
  SecurityCoverageResponse,
} from '@/types';

export interface HealthResponse {
  status: string;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  version: string;
}

export interface ApiResult<T> {
  data: T;
  isMock: boolean;
}

export interface MoltbookListResponse {
  items: MoltbookEntry[];
  item_count: number;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
  },
): Promise<unknown> {
  return apiFetch(`/manual-trades/${encodeURIComponent(tradeId)}/reconcile`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function getMoltbook(): Promise<ApiResult<MoltbookListResponse>> {
  try {
    const raw = await apiFetch<Record<string, unknown>>('/moltbook');
    const items = (raw.items as MoltbookEntry[]) ?? [];
    return { data: { items, item_count: items.length }, isMock: false };
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

export async function getManualTrades(): Promise<ManualTradeListResponse | null> {
  try {
    return await apiFetch<ManualTradeListResponse>('/manual-trades');
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
