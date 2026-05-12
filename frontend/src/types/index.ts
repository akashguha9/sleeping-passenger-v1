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
  // Bridge metadata — present when the item came from the live-events bridge.
  signal_origin?: 'live_event' | 'legacy_fabric' | string;
  source_name?: string;
  age_hours?: number;
}

export interface ManualTradeLog {
  trade_id: string;
  event_id: string;
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  leverage?: number;
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
  total_tickers?: number;
  total_signals?: number;
  source_files?: number;
  // Bridge-mode fields (present when /signals derived items from signal_events)
  promoted_candidate_count?: number;
  freshness_window_hours?: number;
  limit?: number;
  [key: string]: number | undefined;
}

export interface InboxListResponse {
  operation: string;
  item_count: number;
  items: InboxItem[];
  fabric_bull_state: string;
  fabric_stats: FabricStats;
  signal_source?: 'live_events' | 'legacy_fabric' | string;
  freshness_window_hours?: number;
  mock_fallback?: boolean;
  advisory_status: string;
  human_review_required: boolean;
  execution_mode: string;
  ai_execution_count: number;
  generated_at: string;
}

export interface InboxDiagnosticsResponse {
  signal_events_total: number;
  fresh_window_hours: number;
  latest_signal_event_at: string | null;
  newest_fresh_event_at: string | null;
  source_counts: Record<string, number>;
  fresh_source_counts: Record<string, number>;
  promoted_candidate_count: number;
  mock_fallback: boolean;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  generated_at: string;
  error?: string;
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

export type SourceHealthSeverity = 'ok' | 'info' | 'warning' | 'error';

export interface SourceHealthSummaryEntry {
  source_name: string;
  label: string;
  status: string;
  severity: SourceHealthSeverity;
  category: string;
  human_message: string;
  skipped_reason: string;
  error_message: string;
  fetched_count: number;
  duration_ms: number;
  last_run_at: string;
  event_row_count: number;
}

export interface SourceHealthSummaryResponse {
  sources: SourceHealthSummaryEntry[];
  warning_count: number;
  error_count: number;
  ok_count: number;
  total_count?: number;
  advisory_status: string;
  execution_mode: string;
  ai_execution_count: number;
  human_review_required: boolean;
  broker_api_called?: boolean;
  error?: string;
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

export type LiveSignalSource = 'polymarket' | 'gdelt' | 'sec_edgar' | 'newsapi' | 'event_registry' | 'etherscan' | 'grok_xai' | 'market_data' | 'india' | 'global_filings' | 'asia_disclosure';

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
  // grok_xai
  interpreted_topic?: string;
  narrative_frame?: string;
  contradiction_flags?: string[];
  confidence_score?: number | null;
  source_prompt?: string;
  model_name?: string;
  summary_text?: string;
  grok_response?: string;
  created_at?: string;
  // market_data (Phase C.5 — read-only price confirmation, no execution)
  symbol?: string;
  provider?: string;
  period?: string;
  interval?: string;
  latest_price?: number | null;
  previous_close?: number | null;
  price_change?: number | null;
  price_change_pct?: number | null;
  average_volume?: number | null;
  volume_change_ratio?: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  close?: number | null;
  market_confirmation_score?: number | null;
  // india (Phase C.6 — NSE/RBI/SEBI read-only, no execution)
  index_name?: string;
  last_price?: number | null;
  change?: number | null;
  percent_change?: number | null;
  regulatory_source?: string;
  regulatory_url?: string;
  regulatory_note?: string | null;
  // global_filings (Phase C.7 — global exchange/regulator disclosures, no execution)
  issuer_name?: string;
  ticker_or_identifier?: string;
  exchange_or_regulator?: string;
  jurisdiction?: string;
  disclosure_type?: string;
  summary?: string;
  broker_order_id?: string;
  // asia_disclosure (Phase C.8 — China/HK/Japan/Singapore/Korea disclosures, no execution)
  // Re-uses issuer_name, ticker_or_identifier, exchange_or_regulator, jurisdiction,
  // disclosure_type, published_at, url, summary, provider, language (all already declared above)
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

// ---------------------------------------------------------------------------
// Chart Structure (Phase D.3 / D.4) — advisory-only, no execution
// ---------------------------------------------------------------------------

export interface ChartOHLCVSummary {
  symbol: string;
  source: string;
  candle_count: number;
  first_timestamp: string | null;
  latest_timestamp: string | null;
  latest_close: number | null;
  latest_volume: number | null;
  price_change_abs: number | null;
  price_change_pct: number | null;
  high_low_range_pct: number | null;
  average_volume: number | null;
  volume_ratio_latest_to_average: number | null;
}

export interface ChartCandleAnatomy {
  candle_direction: string;
  candle_shape: string;
  body_pct: number | null;
  upper_wick_pct: number | null;
  lower_wick_pct: number | null;
  close_position_in_range: number | null;
}

export interface ChartTrend {
  short_sma: number | null;
  medium_sma: number | null;
  long_sma: number | null;
  trend_direction: string;
  trend_strength_score: number;
  consecutive_up_closes: number;
  consecutive_down_closes: number;
  distance_from_short_sma_pct: number | null;
}

export interface ChartVolatility {
  average_true_range: number | null;
  atr_pct: number | null;
  realized_volatility_proxy: number | null;
  volatility_regime: string;
  range_expansion_flag: boolean;
  gap_flag: boolean;
  large_move_flag: boolean;
}

export interface ChartSupportResistance {
  rolling_high: number | null;
  rolling_low: number | null;
  distance_to_rolling_high_pct: number | null;
  distance_to_rolling_low_pct: number | null;
  breakout_proximity: string;
}

export interface ChartMarketContext {
  chart_confirmation_score: number;
  confirmation_reasons: string[];
  contradiction_reasons: string[];
  chart_state: string;
}

export interface ChartAdvisory {
  advisory_summary: string;
  suggested_next_step: string;
}

export interface ChartStructureReport {
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
  summary: ChartOHLCVSummary | null;
  candle_anatomy: ChartCandleAnatomy | null;
  trend: ChartTrend | null;
  volatility: ChartVolatility | null;
  support_resistance: ChartSupportResistance | null;
  context: ChartMarketContext | null;
  advisory: ChartAdvisory | null;
}

export interface ChartStructureResponse {
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
  symbol: string;
  source_event_id: string | null;
  candle_count: number;
  chart_state?: string;
  advisory_summary?: string;
  run_ingestion?: string;
  discovery_command?: string;
  backfill_command?: string;
  input_symbol?: string;
  security?: GlobalSecurity | null;
  report: ChartStructureReport | null;
  error?: string;
  // Missing-data signal — emitted by backend when there are no local candles.
  ok?: boolean;
  reason?: 'NO_LOCAL_OHLCV' | string;
  can_bootstrap?: boolean;
  message?: string;
}

export type ChartBootstrapStepStatus = 'OK' | 'SKIPPED' | 'ERROR';

export interface ChartBootstrapResponse {
  ok: boolean;
  symbol: string;
  period: string;
  interval: string;
  discovery_status: ChartBootstrapStepStatus;
  backfill_status: ChartBootstrapStepStatus;
  candles_written: number | null;
  candles_fetched?: number;
  message: string;
  advisory_status: string;
  execution_mode: string;
  execution_gate: string;
  broker_api_called: boolean;
  broker_order_id: string;
  ai_execution_count: number;
  human_review_required: boolean;
}

// ---------------------------------------------------------------------------
// Global Securities (Phase F) — advisory-only, no execution
// ---------------------------------------------------------------------------

export interface GlobalSecurity {
  id?: number;
  canonical_symbol: string;
  provider_symbol: string;
  yahoo_symbol: string;
  isin: string | null;
  name: string;
  exchange_code: string;
  exchange_name: string;
  country: string;
  economy_rank: number | null;
  currency: string | null;
  asset_type: string;
  sector: string | null;
  industry: string | null;
  active: boolean;
  first_seen_at: string;
  last_seen_at: string;
  delisted_at: string | null;
  source: string;
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
}

export interface SymbolResolution {
  canonical_symbol: string;
  input_symbol: string;
  resolution_path: 'direct' | 'alias' | 'unknown';
  alias_used: string | null;
  security: GlobalSecurity | null;
  unknown: boolean;
  error?: string;
  message?: string;
  discovery_command: string;
  backfill_command: string;
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
}

export interface SecuritySearchResponse {
  query: string;
  count: number;
  results: GlobalSecurity[];
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
  error?: string;
}

export interface SecurityDetailResponse {
  symbol: string;
  canonical_symbol: string;
  found: boolean;
  resolution: SymbolResolution;
  security: GlobalSecurity | null;
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
  error?: string;
  discovery_command?: string;
  backfill_command?: string;
}

export interface SecurityCoverageResponse {
  canonical_symbol: string;
  input_symbol: string;
  in_securities_master: boolean;
  security: GlobalSecurity | null;
  candle_count: number;
  first_candle_at: string | null;
  last_candle_at: string | null;
  aliases: string[];
  discovery_command: string;
  backfill_command: string;
  resolution: SymbolResolution;
  advisory_status: string;
  execution_gate: string;
  human_review_required: boolean;
  ai_execution_count: number;
  broker_api_called: boolean;
  broker_order_id: string;
  error?: string;
}
