/**
 * Sprint 7C.1 — Vitest spec for the LearningCompletenessCard component.
 *
 * The card surfaces the learning-completeness API.  It must:
 *   * render a safe empty state when API returned null
 *   * render the headline counts when data is present
 *   * render top missing fields when there are incomplete trades
 *   * render paper/manual distinction when present
 *   * carry advisory-only and execution-permission=false dataset attrs
 *   * never emit broker/execution/AI-approved copy
 */
// @ts-ignore — RTL globals
import { render, screen } from '@testing-library/react';
import { LearningCompletenessCard } from '@/components/LearningCompletenessCard';
import type { LearningCompletenessResponse } from '@/types';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const SAFETY_STAMPS = {
  advisory_status: 'ADVISORY_ONLY',
  execution_gate: 'LOCKED',
  broker_api_called: false,
  ai_execution_count: 0,
  execution_permission: false,
  can_execute: false,
  human_review_required: true,
};

const EMPTY_PAYLOAD: LearningCompletenessResponse = {
  report: 'learning_completeness_report',
  db_available: true,
  reconciled_count: 0,
  learning_complete_count: 0,
  learning_incomplete_count: 0,
  complete_count: 0,
  incomplete_count: 0,
  missing_field_distribution: {},
  items: [],
  warnings: [],
  operator_action: 'OK',
  advisory_disclaimer: 'advisory only',
  paper_trade_count: 0,
  real_manual_trade_count: 0,
  ...SAFETY_STAMPS,
};

const POPULATED_PAYLOAD: LearningCompletenessResponse = {
  ...EMPTY_PAYLOAD,
  reconciled_count: 3,
  learning_complete_count: 1,
  learning_incomplete_count: 2,
  complete_count: 1,
  incomplete_count: 2,
  paper_trade_count: 2,
  real_manual_trade_count: 1,
  missing_field_distribution: {
    outcome_quality: 2,
    lesson: 1,
  },
  items: [
    {
      trade_id: 'MT_1',
      event_id: 'EV_1',
      ticker: 'AAPL',
      side: 'BUY',
      executed_at: '2026-01-01T00:00:00Z',
      outcome_status: 'WIN',
      outcome_quality: '',
      process_error: '',
      mistake_tags: '',
      lesson_pre_trade: '',
      lesson_reconciliation: '',
      learning_complete: false,
      missing_fields: ['outcome_quality', 'lesson'],
      blocked_reason: 'Outcome quality is unlabelled.',
    },
  ],
};

describe('LearningCompletenessCard', () => {
  it('renders the safe load-failure state when data is null', () => {
    render(<LearningCompletenessCard data={null} />);
    const card = screen.getByTestId('learning-completeness-card');
    expect(card.getAttribute('data-state')).toBe('load-failed');
    expect(card.getAttribute('data-advisory-only')).toBe('true');
    expect(card.getAttribute('data-execution-permission')).toBe('false');
    expect(screen.getByTestId('lc-empty-copy').textContent).toMatch(
      /Could not load/i,
    );
    expect(screen.getByTestId('lc-safety-copy').textContent).toMatch(
      /advisory-only/i,
    );
  });

  it('renders the empty / no-data state when the DB is available but empty', () => {
    render(<LearningCompletenessCard data={EMPTY_PAYLOAD} />);
    const card = screen.getByTestId('learning-completeness-card');
    expect(card.getAttribute('data-state')).toBe('empty');
    expect(card.getAttribute('data-incomplete-count')).toBe('0');
    expect(screen.getByTestId('lc-empty-copy').textContent).toMatch(
      /No manual or paper journal entries yet/i,
    );
  });

  it('renders the headline counts when populated', () => {
    render(<LearningCompletenessCard data={POPULATED_PAYLOAD} />);
    const card = screen.getByTestId('learning-completeness-card');
    expect(card.getAttribute('data-state')).toBe('populated');
    expect(card.getAttribute('data-incomplete-count')).toBe('2');
    expect(screen.getByTestId('lc-counts').textContent).toMatch(
      /2 incomplete/i,
    );
    expect(screen.getByTestId('lc-mode-counts').textContent).toMatch(
      /2 paper/i,
    );
  });

  it('renders the top missing fields when present', () => {
    render(<LearningCompletenessCard data={POPULATED_PAYLOAD} />);
    expect(screen.getByTestId('lc-missing-fields')).toBeTruthy();
    expect(screen.getByTestId('lc-missing-outcome_quality').textContent).toMatch(
      /outcome_quality/,
    );
  });

  it('renders the oldest incomplete items when present', () => {
    render(<LearningCompletenessCard data={POPULATED_PAYLOAD} />);
    const items = screen.getByTestId('lc-incomplete-items');
    expect(items.textContent).toMatch(/AAPL/);
    expect(items.textContent).toMatch(/Outcome quality is unlabelled/);
  });

  it('never emits forbidden broker / execution / AI-approved copy', () => {
    const { container } = render(
      <LearningCompletenessCard data={POPULATED_PAYLOAD} />,
    );
    const blob = (container.textContent ?? '').toLowerCase();
    expect(blob).not.toMatch(/place order/);
    expect(blob).not.toMatch(/execute trade/);
    expect(blob).not.toMatch(/broker (api|order|connected)/);
    expect(blob).not.toMatch(/auto[- ]trade/);
    expect(blob).not.toMatch(/ai[- ]approved/);
    expect(blob).not.toMatch(/permission granted/);
    expect(blob).not.toMatch(/trade now/);
  });
});
