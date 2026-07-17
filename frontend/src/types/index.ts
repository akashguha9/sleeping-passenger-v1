import type { ScoreCalibration } from '@/lib/scoreCalibration';

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

// Signal Reactor states — canonical enum mirroring scripts/signal_reactor.py.
// "INSUFFICIENT_DATA" is the safe default the frontend uses when the
// backend hasn't computed a reactor verdict for this item.
export type ReactorState =
  | 'COLD_OBSERVE'
  | 'WARM_WATCH'
  | 'FUSION_REVIEW_CANDIDATE'
  | 'FISSION_MAP_ONLY'
  | 'HOT_CONTAINMENT_REQUIRED'
  | 'WASTE_DECAY'
  | 'ECHO_SUPPRESSED'
  | 'OPERATOR_CONTROL_RODS'
  | 'INSUFFICIENT_DATA';

export type ReactorFusionValidity =
  | 'valid_fusion'
  | 'weak_fusion'
  | 'echo_not_fusion'
  | 'overheated_uncontained'
  | 'insufficient_data';

// Common reactor-diagnostic shape attached to inbox items by the backend
// (`scripts.signal_inbox_api._decorate_with_reactor_diagnostics`).  All
// fields are optional on the wire so older payloads still type-check.
export interface ReactorDiagnostics {
  reactor_state?: ReactorState | string;
  decision_grade_energy?: number | null;
  echo_risk_score?: number | null;
  meltdown_risk_score?: number | null;
  fusion_validity?: ReactorFusionValidity | string;
  fission_branch_clarity?: number | null;
  operator_heat_score?: number | null;
  gallardo_block?: boolean;
  reactor_recommendation?: string;
  reactor_available?: boolean;
}

export interface InboxItem extends ReactorDiagnostics {
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
  source_names?: string[];
  age_hours?: number;
  event_count?: number;
  duplicate_suppressed_count?: number;
  cross_source_support_count?: number;
  representative_event_id?: string;
  aggregated_event_ids?: string[];
  first_observed_at?: string;
  last_observed_at?: string;
  promotion_reason?: string;
  execution_gate?: string;
  broker_api_called?: boolean;
}

export interface ManualTradeLog {
  trade_id: string;
  event_id: string;
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  leverage?: number;
  // P0 leverage governance — computed at log time. A breaching trade is still
  // recorded (journal, not an execution blocker) but flagged so the operator
  // sees the policy breach. Display-only — never grants execution permission.
  leverage_ceiling?: number;
  leverage_breach?: boolean;
  leverage_policy_severity?: 'NONE' | 'WARNING' | 'POLICY_BREACH' | string;
  leverage_policy_reason?: string;
  jurisdiction_group?: 'INDIA' | 'REST_OF_WORLD' | 'UNKNOWN' | string;
  jurisdiction_resolution_source?:
    | 'EXPLICIT'
    | 'SECURITIES_MASTER'
    | 'TICKER_HEURISTIC'
    | 'UNKNOWN_FAIL_CLOSED'
    | string;
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
  // Operator-discipline / journal-quality fields. All optional so legacy
  // rows logged before this sprint still validate.
  invalidation_level?: string;
  expected_horizon?: string;
  risk_reason?: string;
  entry_reason?: string;
  exit_plan?: string;
  confidence_before?: number | null;
  emotional_state?: string;
  mistake_tags?: string;
  lesson?: string;
  // Journal-quality annotations attached by /manual-trades list endpoint.
  journal_completeness_score?: number;
  learning_readiness_score?: number;
  learning_ready?: boolean;
  missing_journal_fields?: string[];
  decision_quality_flags?: string[];
  // Soft-cancel fields populated by the Reconciliation tab's "Cancel Log"
  // action.  Cancellation is record-keeping only — broker_api_called and
  // ai_execution_count are unaffected.  Empty string / undefined means
  // "not cancelled".
  reconciliation_status?: string;
  cancel_reason?: string;
  cancelled_at?: string;
  // Provenance marker for the Reconciliation queue contract.  Rows the
  // operator entered through the Manual Trade Log UI/API carry
  // 'manual_trade_log'.  Empty / unknown rows (smoke seeds, demo
  // fixtures, JSONL imports) are excluded from the live Reconciliation
  // queue.  Storing this NEVER grants execution permission.
  created_via?: string;
  // Sprint I — Native currency the operator selected on log.  Either a
  // supported ISO code (USD/INR/EUR/JPY/...) or 'UNKNOWN' for legacy
  // rows that pre-date the dropdown.  Storing this NEVER grants
  // execution permission.
  currency?: string;
  // Free-text operator label naming which AI / model / source produced
  // the signal the operator acted on (e.g. "GPT-5.5", "Claude Code",
  // "Grok", "Gemini", "DeepSeek", "Perplexity", "Copilot",
  // "Human-only", "Multi-model consensus").  Optional; legacy rows
  // read back as '' and the UI renders "—".  Display-only — never
  // grants execution permission.
  ai_model_used?: string;
  // Sprint I — Reconciliation origin classifier output.  One of
  // USER_MANUAL / EXCLUDED_PROVENANCE / EXCLUDED_TRADE_MODE /
  // EXCLUDED_LOGGED_BY / EXCLUDED_PROBE_THESIS / EXCLUDED_EVENT_ID /
  // EXCLUDED_BROKER_FLAG / EXCLUDED_AI_COUNT.  Only USER_MANUAL rows
  // are eligible for the live Reconciliation queue.  Display-only —
  // never grants execution permission.
  origin_label?: string;
  // Duplicate-group metadata: rows with the same ticker/side/qty/price
  // logged in the same UTC minute share a duplicate_group_key.  The UI
  // surfaces possible_duplicate so the operator can Cancel Log the
  // accidental second click.  Real distinct trades that differ in size
  // or price are unaffected.
  duplicate_group_key?: string;
  duplicate_count?: number;
  possible_duplicate?: boolean;
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
  // Skill-vs-luck / skill-vs-process attribution fields. Optional.
  outcome_quality?: string;
  process_error?: string;
  process_error_notes?: string;
  mistake_tags?: string;
  lesson?: string;
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
  duplicate_suppressed_count?: number;
  freshness_window_hours?: number;
  limit?: number;
  [key: string]: number | undefined;
}

export interface ActionCounts {
  ignore: number;
  have_a_look: number;
  watchlist: number;
  human_review: number;
  manual_review_candidate: number;
}

export interface InboxListResponse {
  operation: string;
  item_count: number;
  items: InboxItem[];
  action_counts?: ActionCounts;
  fabric_bull_state: string;
  fabric_stats: FabricStats;
  signal_source?: 'live_events' | 'legacy_fabric' | string;
  freshness_window_hours?: number;
  mock_fallback?: boolean;
  // Honest calibration status for the priority scores in `items`. When absent
  // or UNCALIBRATED the UI must warn the operator not to size from the score.
  score_calibration?: ScoreCalibration;
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
  fresh_event_count?: number;
  duplicate_suppressed_count?: number;
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

export interface JournalQualityAggregate {
  diagnostic: string;
  entry_count: number;
  learning_ready_count: number;
  average_completeness: number;
  average_learning_readiness: number;
  factor_pass_rates?: Record<string, number>;
  validation_status?: string;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
}

export interface ManualTradeListResponse {
  operation: string;
  trade_count: number;
  trades: ManualTradeLog[];
  truth_source?: string;
  fallback_used?: boolean;
  canonical?: boolean;
  journal_quality_aggregate?: JournalQualityAggregate | null;
  advisory_status: string;
  execution_mode: string;
  execution_gate?: string;
  execution_permission?: boolean;
  can_execute?: boolean;
  ai_execution_count: number;
  human_review_required: boolean;
  broker_api_called: boolean;
  generated_at: string;
}

export interface ReconciliationQueueItem {
  trade_id: string;
  event_id: string;
  ticker: string;
  side: string;
  quantity: number;
  price: number;
  executed_at: string;
  age_days: number | null;
  thesis: string;
  invalidation_level: string;
  expected_horizon: string;
  risk_reason: string;
  entry_reason: string;
  exit_plan: string;
  confidence_before: number | null;
  emotional_state: string;
  mistake_tags: string;
  lesson: string;
  journal_completeness_score: number;
  learning_readiness_score: number;
  learning_ready: boolean;
  missing_journal_fields: string[];
  needs_reconciliation: boolean;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
}

export interface ReconciliationQueueSummary {
  unreconciled_count: number;
  oldest_unreconciled_age_days: number | null;
  average_journal_completeness: number;
  average_learning_readiness: number;
  learning_ready_count: number;
  missing_field_distribution: Record<string, number>;
  by_ticker: Record<string, number>;
  by_emotional_state: Record<string, number>;
  by_expected_horizon: Record<string, number>;
}

export interface ReconciliationQueueResponse {
  report: string;
  db_path: string;
  db_available: boolean;
  items: ReconciliationQueueItem[];
  summary: ReconciliationQueueSummary;
  warnings: string[];
  operator_action: string;
  advisory_disclaimer: string;
  generated_at: string;
  truncated?: boolean;
  truncated_to?: number;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
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
  suggested_command?: string;
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

export type SourceHealthLabel =
  | 'healthy'
  | 'watch'
  | 'degraded'
  | 'unhealthy'
  | 'planned_not_scored'
  | 'optional_config_missing'
  | string;

export interface LiveSourceStatusEntry {
  source_key: string;
  freshness_state:
    | 'fresh'
    | 'stale'
    | 'overdue'
    | 'never_run'
    | 'skipped'
    | 'failed'
    | string;
  last_success_at: string | null;
  hours_since_last_success: number | null;
  next_expected_refresh_at: string | null;
  cadence_hours: number;
  credential_configured: boolean;
  adapter_status: string;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
  may_inform_human_review: boolean;
  may_execute: boolean;
  may_call_broker: boolean;
  // Refresh-attempt diagnostics added by /live-sources/status
  last_refresh_attempt?: string | null;
  last_refresh_success_at?: string | null;
  last_refresh_success?: boolean;
  last_refresh_skipped?: boolean;
  last_refresh_error?: string;
  last_refresh_skipped_reason?: string;
  refresh_age_hours?: number | null;
  stale_threshold_hours?: number;
  is_stale?: boolean;
  stale_reason?: string;
  stale_excluded_reason?: 'planned_not_scored' | 'optional_config_missing' | string;
  // Sprint 7D.1 — reliability scoring
  health_score?: number | null;
  health_label?: SourceHealthLabel;
  health_reasons?: string[];
  stale_severity?: 'none' | 'soft' | 'moderate' | 'loud' | string;
  config_state?: 'configured' | 'optional_missing' | 'required_missing' | 'planned' | string;
  last_success_age_hours?: number | null;
  operator_message?: string;
  tier?: 'core' | 'secondary' | 'optional' | 'planned' | string;
  // Source display state — the read-only contract the UI uses to render
  // each tab honestly (live vs archived vs coverage vs stale).
  display_state?:
    | 'current_live'
    | 'optional_unconfigured_with_archive'
    | 'optional_unconfigured_empty'
    | 'optional_unconfigured_with_coverage'
    | 'planned_coverage'
    | 'stale_active'
    | 'never_run'
    | string;
  is_current_live?: boolean;
  is_configured?: boolean;
  is_optional?: boolean;
  is_planned?: boolean;
  is_active?: boolean;
  is_scored?: boolean;
  rows_are_current_live?: boolean;
  rows_are_archived?: boolean;
  rows_are_stale?: boolean;
  current_live_count?: number;
  archived_row_count?: number;
  coverage_row_count?: number;
  total_persisted_count?: number;
  latest_persisted_row_at_utc?: string | null;
  latest_current_refresh_at_utc?: string | null;
  latest_source_event_at_utc?: string | null;
  display_count_label?: string;
  display_timestamp_label?: string;
  display_timestamp_value?: string | null;
  source_display_warning?: string;
  rows_display_reason?: string;
  excluded_from_stale?: boolean;
  advisory_only?: boolean;
}

export interface SourceCoverageRow {
  country: string;
  disclosure_source: string;
  source_url: string;
  status: string;
  notes: string;
}

export interface SourceHealthSummary {
  health_label_distribution: Record<string, number>;
  core_health_label: SourceHealthLabel;
  average_scored_health: number | null;
  scored_count: number;
  planned_count: number;
  optional_missing_config_count: number;
  advisory_status?: string;
  execution_gate?: string;
  broker_api_called?: boolean;
  ai_execution_count?: number;
  execution_permission?: boolean;
  can_execute?: boolean;
}

export type AutoRefreshStatusCode =
  | 'PASS'
  | 'NOT_INSTALLED'
  | 'DISABLED'
  | 'FAILING'
  | 'STALE'
  | 'UNKNOWN'
  | 'UNSUPPORTED_PLATFORM';

export interface AutoRefreshStatus {
  task_name?: string;
  installed?: boolean;
  enabled?: boolean;
  cadence_hours?: number;
  last_run_time?: string | null;
  next_run_time?: string | null;
  last_task_result?: number | null;
  last_successful_refresh_utc?: string | null;
  last_attempted_refresh_utc?: string | null;
  stale_sources?: string[];
  stale_threshold_hours?: number;
  status: AutoRefreshStatusCode | string;
  status_reason?: string;
  suggested_command?: string | null;
  manual_refresh_command?: string;
  advisory_only?: boolean;
  broker_api_called?: boolean;
  ai_execution_count?: number;
  execution_gate?: string;
}

export interface LiveSourcesStatusResponse {
  operation: string;
  sources: Record<string, LiveSourceStatusEntry>;
  source_count: number;
  freshness_distribution: Record<string, number>;
  stale_sources?: string[];
  excluded_from_stale?: { source: string; reason: string }[];
  source_errors?: Record<string, string>;
  refresh_configured?: boolean;
  stale_threshold_hours?: number;
  last_refresh_attempt?: string | null;
  last_refresh_success?: string | null;
  scheduler_hint?: string;
  manual_refresh_command?: string;
  auto_refresh_status?: AutoRefreshStatus;
  health_summary?: SourceHealthSummary;
  source_coverage_rows?: Record<string, SourceCoverageRow[]>;
  asia_disclosure_coverage_rows?: SourceCoverageRow[];
  advisory_status: string;
  execution_mode?: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
  human_review_required: boolean;
  error?: string;
}

// ---------------------------------------------------------------------------
// Learning completeness (Sprint 7C.1) — advisory-only, read-only
// ---------------------------------------------------------------------------

export interface LearningCompletenessItem {
  trade_id: string;
  event_id: string;
  ticker: string;
  side: string;
  executed_at: string;
  outcome_status: string;
  outcome_quality: string;
  process_error: string;
  mistake_tags: string;
  lesson_pre_trade: string;
  lesson_reconciliation: string;
  learning_complete: boolean;
  missing_fields: string[];
  blocked_reason: string;
}

export interface LearningCompletenessResponse {
  report: string;
  db_path?: string;
  db_available: boolean;
  reconciled_count: number;
  learning_complete_count: number;
  learning_incomplete_count: number;
  // Convenience aliases for the frontend.
  complete_count?: number;
  incomplete_count?: number;
  // Sprint I split — separate the live awaiting queue from the
  // reconciled-but-journal-incomplete bucket so the landing page can
  // distinguish "trades that need an outcome" from "trades that need
  // journal fields".
  reconciled_but_learning_incomplete_count?: number;
  awaiting_reconciliation_count?: number;
  excluded_or_cancelled_count?: number;
  missing_field_distribution: Record<string, number>;
  trade_mode_distribution?: Record<string, number>;
  paper_trade_count?: number;
  real_manual_trade_count?: number;
  items: LearningCompletenessItem[];
  warnings: string[];
  operator_action: string;
  advisory_disclaimer: string;
  truncated?: boolean;
  truncated_to?: number;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
  human_review_required: boolean;
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

export type LiveSignalSource =
  | 'polymarket'
  | 'kalshi'
  | 'prediction_market_disagreement'
  | 'gdelt'
  | 'sec_edgar'
  | 'newsapi'
  | 'event_registry'
  | 'etherscan'
  | 'grok_xai'
  | 'market_data'
  | 'india'
  | 'global_filings'
  | 'asia_disclosure';

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
  // kalshi (Kalshi sprint — prediction-market signal, advisory-only)
  source?: string;
  source_label?: string;
  source_market_id?: string;
  category?: string;
  category_raw?: string;
  display_category?: string;
  mvp_category?: string | null;
  category_allowed?: boolean;
  quarantine_reason?: string;
  visible_in_kalshi_feed?: boolean;
  primary_title?: string;
  display_title?: string;
  raw_title?: string;
  title_source?: string;
  title_quality?: string;
  title_warnings?: string[];
  outcomes?: string[];
  source_freshness_status?: string;
  market_activity_status?: string;
  ui_badge_status?: string;
  source_freshness_ttl_seconds?: number;
  last_successful_fetch_at_utc?: string | null;
  rules?: string;
  market_url?: string;
  implied_probability?: number | null;
  yes_price?: number | null;
  no_price?: number | null;
  open_interest?: number | null;
  close_time_utc?: string;
  fetched_at_utc?: string;
  asset_tags?: string[];
  event_tags?: string[];
  semantic_text?: string;
  cross_venue_match_label?: string | null;
  is_mock_fixture?: boolean;
  advisory_only?: boolean;
  execution_permission?: string;
  // prediction_market_disagreement (cross-venue advisory alert)
  pair_id?: string;
  polymarket_event_id?: string;
  kalshi_event_id?: string;
  polymarket_title?: string;
  kalshi_title?: string;
  polymarket_probability?: number | null;
  kalshi_probability?: number | null;
  probability_gap?: number | null;
  disagreement_threshold?: number;
  semantic_similarity?: number;
  pair_type?: string;
  disagreement_triggered?: boolean;
  signal_class?: string;
  customer_label?: string;
  resolution_mismatch_reasons?: string[];
  pair_score_components?: Record<string, number>;
  probability_source_polymarket?: string;
  probability_source_kalshi?: string;
  status?: string;
  // Embedding provider stamps written by the disagreement scanner so
  // the frontend can render explainability without a backend round-trip.
  embedding_provider?: string;
  embedding_model?: string;
  embedding_available?: boolean;
  embedding_status_reason?: string;
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

// Market-data freshness gate (Sprint H — Stale OHLCV repair).
// Always present on a successful chart-structure response, plus on the
// missing-data response.  The frontend uses these fields to refuse to
// render a normal verdict over ancient / mock / seed / fixture data.
export type ChartFreshnessStatus =
  | 'FRESH'
  | 'DELAYED'
  | 'STALE'
  | 'ANCIENT'
  | 'MISSING'
  | 'MOCK_OR_DEMO_BLOCKED';

export type ChartFreshnessGate = 'PASS' | 'WARN' | 'BLOCK';

export type ChartSourceKind =
  | 'CANONICAL_SQLITE'
  | 'READ_ONLY_PROVIDER'
  | 'JSONL_AUDIT_ONLY'
  | 'MOCK'
  | 'DEMO'
  | 'SEED'
  | 'UNKNOWN';

export interface ChartFreshness {
  data_freshness_status: ChartFreshnessStatus;
  freshness_gate: ChartFreshnessGate;
  latest_candle_utc: string | null;
  first_candle_utc: string | null;
  data_age_hours: number | null;
  data_age_days: number | null;
  freshness_reason: string;
  source_kind: ChartSourceKind | string;
  candle_count: number;
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
  suggested_next_step?: string;
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
  // Freshness gate — see ChartFreshness above.  Top-level mirror fields
  // duplicate the most-used pieces so the UI does not need to optional-chain
  // through `freshness` everywhere.
  freshness?: ChartFreshness;
  data_freshness_status?: ChartFreshnessStatus;
  freshness_gate?: ChartFreshnessGate;
  latest_candle_utc?: string | null;
  data_age_days?: number | null;
  source_kind?: ChartSourceKind | string;
  // Sprint I — generic price-truth fields produced by the backend
  // chart_structure_price_truth layer.  Symbol-agnostic: every ticker
  // gets the same set of optional fields so the UI can render "Latest
  // daily close" + "Latest quote" + divergence panel uniformly.
  price_truth?: ChartPriceTruth;
  latest_daily_close?: number | null;
  latest_daily_candle_utc?: string | null;
  latest_quote_price?: number | null;
  latest_quote_currency?: string | null;
  latest_quote_timestamp_utc?: string | null;
  latest_quote_source?: string | null;
  quote_freshness_status?: string | null;
  quote_freshness_gate?: string | null;
  quote_age_minutes?: number | null;
  quote_price_delta?: number | null;
  quote_price_delta_pct?: number | null;
  price_truth_status?: ChartPriceTruthStatus | string | null;
  price_truth_reason?: string | null;
  // Sprint I patch — backend-resolved currency.  `display_currency` is
  // the currency the UI should label prices with; `currency_source`
  // tells the UI whether it came from the provider, market metadata,
  // a symbol-suffix fallback, or could not be resolved at all.
  display_currency?: string | null;
  latest_daily_close_currency?: string | null;
  currency_source?: ChartCurrencySource | string | null;
}

export type ChartPriceTruthStatus =
  | 'DAILY_ONLY'
  | 'QUOTE_ALIGNED'
  | 'QUOTE_DIVERGES_FROM_DAILY'
  | 'QUOTE_UNAVAILABLE'
  | 'INTERNAL_TIMESTAMP_MISMATCH'
  | 'INTERNAL_DATA_CONSISTENCY_ERROR'
  | 'SYMBOL_UNSUPPORTED_BY_QUOTE_SOURCE';

export type ChartCurrencySource =
  | 'PROVIDER'
  | 'MARKET_METADATA'
  | 'SYMBOL_SUFFIX_FALLBACK'
  | 'UNKNOWN';

export interface ChartPriceTruth {
  symbol: string;
  latest_daily_close: number | null;
  latest_daily_candle_utc: string | null;
  latest_quote_price: number | null;
  latest_quote_currency: string | null;
  latest_quote_timestamp_utc: string | null;
  latest_quote_source: string | null;
  quote_freshness_status: string | null;
  quote_freshness_gate: string | null;
  quote_age_minutes: number | null;
  quote_price_delta: number | null;
  quote_price_delta_pct: number | null;
  price_truth_status: ChartPriceTruthStatus | string;
  price_truth_reason: string;
  suggested_next_step: string;
  advisory_status: string;
  execution_gate: string;
  broker_api_called: boolean;
  ai_execution_count: number;
  execution_permission: boolean;
  can_execute: boolean;
  record_keeping_only: boolean;
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

// ---------------------------------------------------------------------------
// Simulation Intelligence Layer (SIL) — advisory-only six-lens council.
// Every response carries the standard advisory invariants. All simulation
// output is SIMULATED_ONLY / PROXY_DERIVED / MODEL_INFERRED — never measured,
// never execution. Backend producer: scripts/simulation_intelligence/.
// ---------------------------------------------------------------------------
export interface SimAdvisoryStamps {
  advisory_status: string;
  execution_gate: string;
  ai_execution_count: number;
  broker_api_called: boolean;
  human_review_required: boolean;
}

export interface SimLensResult {
  lens: string;
  state_interpretation: string;
  advisory_vote: string;
  confidence: number;
  evidence_label: string;
  uncertainty: number;
  robustness: number;
  fragility: number;
  regret: number;
  exploitability: number;
  main_risk: string;
  main_opportunity: string;
  tail_warning: string;
  missing_data_warnings: string[];
  scenario_branches: string[];
  freshness_status: string;
  error?: string;
  detail?: Record<string, unknown>;
}

export interface SimLensWeight {
  lens: string;
  final_weight: number;
  reasons: string[];
}

export interface SimStressResult {
  scenario_id: string;
  scenario_name: string;
  survived: boolean;
  impact: number;
  failure_modes: string[];
  band?: Record<string, number | string>;
}

export interface SimCouncilResult extends SimAdvisoryStamps {
  ok?: boolean;
  report?: string;
  run_id: string;
  contract_version: string;
  ticker: string;
  market: string;
  as_of: string;
  data_cutoff: string;
  seed: number;
  aggregate_vote: string;
  disagreement_class: string;
  aggregate_confidence: number;
  evidence_label: string;
  robustness: number;
  fragility: number;
  risk_block_engaged: boolean;
  risk_block_reason: string;
  simulation_only: boolean;
  usefulness_score: number;
  lens_results: SimLensResult[];
  lens_weights: SimLensWeight[];
  minority_warnings: string[];
  tail_warnings: string[];
  stress_results: SimStressResult[];
  dominant_assumptions: string[];
  missing_data_warnings: string[];
  aggregation_explanation: string[];
  engine_availability: Record<string, string>;
  freshness_status: string;
  persisted?: boolean;
}

export interface SimEngineEntry {
  engine: string;
  domain: string;
  integration_mode: string;
  final_decision: string;
  license: string;
  python313: string;
  windows: string;
  transplanted_into: string;
  reason: string;
}

export interface SimEnginesResponse extends SimAdvisoryStamps {
  manifest_version: string;
  summary: {
    engine_count: number;
    by_mode: Record<string, string[]>;
    honesty_note: string;
  };
  engines: SimEngineEntry[];
  availability: { available_now: string[]; available_count: number };
}

export interface SimScenario {
  scenario_id: string;
  name: string;
  description: string;
  tags: string[];
  operational: boolean;
}

export interface SimScenariosResponse extends SimAdvisoryStamps {
  count: number;
  default_scenario_ids: string[];
  scenarios: SimScenario[];
}

export interface SimHealthResponse extends SimAdvisoryStamps {
  sil_enabled: boolean;
  feature_flags: Record<string, unknown>;
  engine_count: number;
  engines_available_now: string[];
  engines_available_count: number;
  manifest_version: string;
  note: string;
}

export interface SimRunSummary {
  run_id: string;
  ticker: string;
  market: string;
  seed: number;
  aggregate_vote: string;
  disagreement_class: string;
  aggregate_confidence: number;
  evidence_label: string;
  risk_block_engaged: boolean;
  simulation_only: boolean;
  usefulness_score: number;
  created_at: string;
}

export interface SimRunsResponse extends SimAdvisoryStamps {
  count: number;
  runs: SimRunSummary[];
}

// --- Role-Adjusted Contribution Rating (RACR / "Kanté Index") ---------------

export interface SimRoleContract {
  component_id: string;
  component_name: string;
  role_template: string;
  primary_mandate: string;
  forbidden_mandates: string[];
  honest_ceiling: number;
  dimension_weights: Record<string, number>;
}

export interface SimRoleContractsResponse extends SimAdvisoryStamps {
  contract_version: string;
  component_count: number;
  components: SimRoleContract[];
  dimensions: string[];
}

export interface SimFiveScores {
  role_adjusted_performance: number;
  engineering_quality: number;
  decision_utility: number;
  empirical_validation: number;
  whole_mvp_maturity: number;
  empirical_sample_size: number;
  components_scored: number;
  components_runtime_reached: number;
  note: string;
  whole_mvp_detail: Record<string, unknown>;
}

export interface SimComponentRating {
  component_id: string;
  component_name: string;
  role_template: string;
  role_adjusted_performance: number;
  engineering_quality: number;
  decision_utility: number;
  empirical_validation: number;
  rating_confidence: number;
  support: string;
  evidence_grade: string;
  honest_ceiling: number;
  runtime_reached: boolean;
  empirically_validated: boolean;
  severe_events: number;
  caps_applied: string[];
  reasons: string[];
  dimension_scores: Array<{
    dimension: string;
    weight: number;
    value: number;
    grade: string;
    confidence: number;
    support: string;
    source: string;
    reason: string;
  }>;
}

export interface SimContributionEvent {
  event_id: string;
  component_id: string;
  event_type: string;
  direction: string;
  severity: string;
  event_class: string;
  target_dimension: string;
  counterfactual_impact: string;
  evidence: string;
  affected_final_result: boolean;
}

export interface SimLensContribution {
  lens: string;
  vote_changed: boolean;
  shapley_value: number;
  tail_warning_lost: number;
  coverage_loss: number;
  marginal_summary: string;
}

export interface SimRatingsResult extends SimAdvisoryStamps {
  ok: boolean;
  run_id: string;
  ticker: string;
  persisted?: boolean;
  five_scores: SimFiveScores;
  ratings: SimComponentRating[];
  contribution_events: SimContributionEvent[];
  context_difficulty: { score: number; band: string; dominant_factor: string };
  ablation: {
    most_valuable_lens: string;
    quietest_valuable_lens: string;
    shapley_exact: boolean;
    lens_contributions: SimLensContribution[];
  };
  council_vote: string;
  evidence_label: string;
  simulation_only: boolean;
}

export interface SimReliabilityResponse extends SimAdvisoryStamps {
  fault_injection: Array<{ fault: string; survived: boolean; safe: boolean; detail: string }>;
  all_faults_survived_safely: boolean;
}

export interface SimEngineValidationResponse extends SimAdvisoryStamps {
  engine_count: number;
  optional_real_integrations: string[];
  any_engine_available: boolean;
  base_app_runs_without_engines: boolean;
  all_never_real_execution: boolean;
  validations: Array<{ engine: string; status: string; available: boolean; integration_mode: string }>;
}

// --- Eureka closed-loop intelligence ---------------------------------------

export interface EurekaHealthResponse extends SimAdvisoryStamps {
  twins_frozen: number;
  predictions_resolved: number;
  mean_brier: number | null;
  empirical_readiness_score: number;
  empirical_score: number;
  empirical_note: string;
  loop_closed: boolean;
}

export interface DecisionTwinSummary {
  twin_id: string;
  candidate_id: string;
  info_cutoff: string;
  advisory_state: string;
  regime_key: string;
  immutability_hash: string;
  created_at: string;
}

export interface DecisionTwinsResponse extends SimAdvisoryStamps {
  count: number;
  twins: DecisionTwinSummary[];
}

export interface ShadowAttentionItem {
  candidate: string;
  advisory_state: string;
  priority: number;
  depth: string;
  regime: string;
  process_quality: number | null;
}

export interface DailyShadowRunResponse extends SimAdvisoryStamps {
  ok: boolean;
  mode: string;
  session_date: string;
  candidates_considered: number;
  rejected_cheaply: number;
  analysed: number;
  twins_created: number;
  predictions_frozen: number;
  outcome_jobs_registered: number;
  attention_queue: ShadowAttentionItem[];
  top_research_actions: Array<{ candidate: string; action: string; net_voi: number }>;
  no_research_needed: string[];
  human_action_required: boolean;
  persisted?: boolean;
}
