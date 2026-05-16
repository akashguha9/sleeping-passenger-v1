/**
 * Vitest spec for ReconciliationCard currency rendering (Sprint I).
 *
 * Locks in:
 *   - Log Price and Fill Price render with the trade's native currency
 *   - Realized P&L renders with the same currency
 *   - Legacy trades whose currency reads back as UNKNOWN render without
 *     a hardcoded "$" prefix
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

import { ReconciliationCard } from '@/components/ReconciliationCard';
import type { ManualTradeLog, TradeReconciliation } from '@/types';

function makeTrade(overrides: Partial<ManualTradeLog> = {}): ManualTradeLog {
  return {
    trade_id: 'MT_001',
    event_id: 'EVT_1',
    ticker: 'BHARTIARTL.NS',
    side: 'BUY',
    quantity: 10,
    price: 1789.20,
    executed_at: '2026-05-15T16:00:00Z',
    thesis: 'thesis',
    notes: '',
    logged_by: 'human',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    broker_order_id: 'NONE',
    broker_api_called: false,
    currency: 'INR',
    ...overrides,
  };
}

function makeReconciliation(overrides: Partial<TradeReconciliation> = {}): TradeReconciliation {
  return {
    reconciliation_id: 'R_1',
    trade_id: 'MT_001',
    event_id: 'EVT_1',
    reconciled_at: '2026-05-16T16:00:00Z',
    actual_fill_price: 1789.20,
    actual_quantity: 10,
    outcome_notes: '',
    pnl_estimate: 116.20,
    outcome_status: 'WIN',
    execution_mode: 'HUMAN_ONLY',
    ai_execution_count: 0,
    advisory_status: 'ADVISORY_ONLY',
    human_review_required: true,
    ...overrides,
  } as TradeReconciliation;
}

describe('ReconciliationCard currency rendering', () => {
  it('renders INR price/fill/P&L for an Indian-symbol trade', () => {
    render(
      <ReconciliationCard
        trade={makeTrade({ currency: 'INR' })}
        reconciliation={makeReconciliation()}
      />,
    );
    expect(screen.getByTestId('reconciliation-log-price').textContent).toMatch(/1,?789\.20 INR/);
    expect(screen.getByTestId('reconciliation-fill-price').textContent).toMatch(/1,?789\.20 INR/);
    expect(screen.getByTestId('reconciliation-pnl').textContent).toMatch(/\+?116\.20 INR/);
  });

  it('renders USD for an AAPL trade', () => {
    render(
      <ReconciliationCard
        trade={makeTrade({ ticker: 'AAPL', price: 180.0, currency: 'USD' })}
        reconciliation={makeReconciliation({ actual_fill_price: 181.0, pnl_estimate: 10.0 })}
      />,
    );
    expect(screen.getByTestId('reconciliation-log-price').textContent).toMatch(/180\.00 USD/);
    expect(screen.getByTestId('reconciliation-fill-price').textContent).toMatch(/181\.00 USD/);
  });

  it('omits the currency tag for legacy UNKNOWN rows and never inserts a "$"', () => {
    render(
      <ReconciliationCard
        trade={makeTrade({ ticker: 'LEGACY', currency: 'UNKNOWN' })}
        reconciliation={makeReconciliation()}
      />,
    );
    const logPrice = screen.getByTestId('reconciliation-log-price').textContent ?? '';
    expect(logPrice.includes('$')).toBe(false);
    expect(logPrice).toMatch(/1,?789\.20/);
    // No currency code suffix when unknown — better than guessing USD.
    expect(logPrice.includes('UNKNOWN')).toBe(false);
  });
});
