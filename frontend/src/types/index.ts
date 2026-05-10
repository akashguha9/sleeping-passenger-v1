export type BullState =
  | 'HURACÁN'
  | 'AVENTADOR'
  | 'MURCIÉLAGO'
  | 'DIABLO'
  | 'GALLARDO'
  | 'ISLERO'
  | 'MIURA'
  | 'UNKNOWN';

export type UserStatus = 'pending' | 'watchlist' | 'human_review' | 'rejected' | 'reconciled';

export type ReconciliationOutcome = 'WIN' | 'LOSS' | 'BREAKEVEN' | 'UNKNOWN';

export type MistakeCategory =
  | 'good_signal_bad_timing'
  | 'bad_signal_lucky_profit'
  | 'good_signal_good_execution'
  | 'bad_signal_correct_rejection'
  | 'missed_signal'
  | 'overtraded_signal'
  | 'chaos_ignored'
  | 'false_confirmation'
  | 'late_entry'
  | 'early_exit'
  | 'no_trade_correct'
  | 'no_trade_missed_opportunity';

export interface InboxItem {
  event_id: string;
  ticker: string;
  signal_state: string;
  entry_type: string;
  priority_score: number;
  observed_at: string;
  source_file: string;
  rejection_dimensions: string[];
  rejection_reason: string;
  persistence_score: number;
  blocker_pressure_score: number;
  kill_rate_score: number;
  blocker_attribution: string;
  user_status: UserStatus;
  has_reflection: boolean;
  has_ai_summary: boolean;
  advisory_status: string;
  human_review_required: boolean;
  execution_mode: string;
  ai_execution_count: number;
}

export interface ManualTradeLog {
  trade_id: string;
  event_id: string;
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  executed_at: string;
  thesis: string;
  notes: string;
  logged_by: string;
  execution_mode: string;
  ai_execution_count: number;
  advisory_status: string;
  human_review_required: boolean;
  broker_order_id: string;
  broker_api_called: boolean;
}

export interface TradeReconciliation {
  reconciliation_id: string;
  trade_id: string;
  event_id: string;
  reconciled_at: string;
  actual_fill_price: number;
  actual_quantity: number;
  outcome_notes: string;
  pnl_estimate: number;
  outcome_status: ReconciliationOutcome;
  execution_mode: string;
  ai_execution_count: number;
  advisory_status: string;
  human_review_required: boolean;
}

export interface MoltbookEntry {
  entry_id: string;
  event_id: string;
  ticker: string;
  original_signal_thesis: string;
  ai_interpretation: string;
  user_reflection: string;
  final_human_decision: string;
  manual_trade_log_id: string;
  outcome: string;
  mistake_type: MistakeCategory;
  lesson_learned: string;
  bias_detected: string;
  recalibration_note: string;
  future_rule_update: string;
  logged_at: string;
  advisory_status: string;
  human_review_required: boolean;
  execution_mode: string;
  ai_execution_count: number;
}

export interface ValidationResult {
  event_id: string;
  validated_at: string;
  validation_checks: Record<string, boolean>;
  validation_passed: boolean;
  validation_notes: string[];
  advisory_status: string;
  human_review_required: boolean;
  execution_gate: string;
}

export interface UserReflection {
  reflection_id: string;
  event_id: string;
  author: string;
  conviction_level: string;
  reflection_text: string;
  reflected_at: string;
  advisory_status: string;
  human_review_required: boolean;
}

export interface FabricStats {
  total_tickers: number;
  total_signals: number;
  source_files: number;
}

export interface InboxListResponse {
  operation: string;
  item_count: number;
  items: InboxItem[];
  fabric_bull_state: string;
  fabric_stats: FabricStats;
  advisory_status: string;
  human_review_required: boolean;
  execution_mode: string;
  ai_execution_count: number;
  generated_at: string;
}

export interface SignalDetailResponse {
  operation: string;
  event_id: string;
  signal: InboxItem;
  ticker_summary: Record<string, unknown>;
  reflections: UserReflection[];
  ai_summaries: AiSummary[];
  manual_trades: ManualTradeLog[];
  advisory_status: string;
  human_review_required: boolean;
  execution_mode: string;
  ai_execution_count: number;
  generated_at: string;
}

export interface AiSummary {
  summary_id: string;
  event_id: string;
  model_label: string;
  summary_text: string;
  summarized_at: string;
  advisory_status: string;
  human_review_required: boolean;
  advisory_note: string;
}

export interface SourceHealth {
  source_file: string;
  ticker_count: number;
  last_seen: string;
  status: 'active' | 'stale' | 'unknown';
}

export interface ManualTradeListResponse {
  operation: string;
  trade_count: number;
  trades: ManualTradeLog[];
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  broker_api_called: boolean;
  generated_at: string;
}

export interface SourceHealthResponse {
  operation: string;
  fabric_stats: {
    total_snapshot_rows?: number;
    total_signal_events?: number;
    total_tickers_observed?: number;
    [key: string]: number | undefined;
  };
  fabric_bull_state: string;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  generated_at: string;
}

export interface DbStatusResponse {
  db_path: string;
  db_exists: boolean;
  table_row_counts: Record<string, number>;
  advisory_status: string;
  ai_execution_count: number;
  broker_api_called: boolean;
  generated_at: string;
}

export type LiveSignalSource = 'polymarket' | 'gdelt' | 'sec_edgar' | 'newsapi' | 'event_registry' | 'etherscan';

export interface LiveSignalRawPayload {
  event_id?: string;
  source_name?: string;
  signal_type?: string;
  title?: string;
  // polymarket
  market_id?: string;
  volume?: number;
  liquidity?: number;
  end_date?: string;
  active?: boolean;
  // gdelt
  url?: string;
  seendate?: string;
  domain?: string;
  language?: string;
  sourcecountry?: string;
  // sec_edgar
  cik?: string;
  form_type?: string;
  filing_date?: string;
  accession_number?: string;
  // newsapi
  description?: string;
  published_at?: string;
  publisher?: string;
  // event_registry
  date_time?: string;
  body?: string;
  // etherscan
  hash?: string;
  from_address?: string;
  to_address?: string;
  value_wei?: string;
  block_number?: string;
  timestamp?: string;
  gas_used?: string;
  [key: string]: unknown;
}

export interface LiveSignalEvent {
  id: number;
  event_id: string;
  source_name: LiveSignalSource | string;
  raw_payload: LiveSignalRawPayload;
  fetched_at: string;
  advisory_status: string;
  human_review_required: boolean;
  execution_gate: string;
  ai_execution_count: number;
}

export interface LiveSignalsResponse {
  live_signal_events: LiveSignalEvent[];
  count: number;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  error?: string;
}
