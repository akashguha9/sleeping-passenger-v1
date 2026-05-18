/**
 * Vitest spec for the defensive fake-marker filter used as the final
 * layer on the Manual Trade Log surface.
 *
 * The backend already strips fake rows via
 * scripts/manual_trade_origin.is_visible_manual_trade.  This frontend
 * filter only fires if a fake row somehow arrives anyway — and these
 * tests pin the rules so the two implementations cannot drift.
 */
import {
  fakeManualTradeReason,
  filterVisibleManualTrades,
  isFakeManualTradeRow,
} from '@/lib/manualTradeFakeMarkers';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const REAL_ROW = {
  trade_id: 'MT_real_user',
  event_id: 'EV_USER_GENUINE',
  ticker: 'ICICIBANK.NS',
  side: 'BUY',
  quantity: 3.8908,
  price: 40.72,
  thesis: 'break of pivot on bank-nifty breadth confirmation',
  logged_by: 'human',
  ai_model_used: 'Claude Code',
  broker_order_id: 'NONE',
  executed_at: '2026-05-15T12:00:00+00:00',
  leverage: 1.0,
};

describe('manualTradeFakeMarkers', () => {
  it('blocks the exact visible AAPL row (trade_id blocklist)', () => {
    const row = { ...REAL_ROW, trade_id: 'MT_6b11745fc3f3' };
    expect(isFakeManualTradeRow(row as never)).toBe(true);
    expect(fakeManualTradeReason(row as never)).toBe('fake_trade_id_blocklist');
  });

  it('blocks AAPL/$180/qty5 fingerprint', () => {
    const row = {
      ...REAL_ROW,
      trade_id: 'MT_unknown',
      ticker: 'AAPL',
      quantity: 5,
      price: 180,
      thesis: 'plausible reasoning',
    };
    expect(fakeManualTradeReason(row as never)).toBe('fake_aapl_fingerprint');
  });

  it('blocks AAPL/$180/qty10 fingerprint with probe thesis', () => {
    const row = {
      ...REAL_ROW,
      trade_id: 'MT_other',
      ticker: 'AAPL',
      quantity: 10,
      price: 180,
      thesis: 'probe',
    };
    expect(isFakeManualTradeRow(row as never)).toBe(true);
  });

  it('blocks EV_AAPL event_id prefix', () => {
    const row = {
      ...REAL_ROW,
      trade_id: 'MT_eva',
      event_id: 'EV_AAPL_FOLLOWUP',
      ticker: 'MSFT',
      price: 421,
      quantity: 1,
    };
    expect(fakeManualTradeReason(row as never)).toBe('fake_event_id_prefix');
  });

  it('blocks "no currency given" thesis', () => {
    const row = {
      ...REAL_ROW,
      trade_id: 'MT_n',
      ticker: 'MSFT',
      price: 421,
      quantity: 1,
      thesis: 'no currency given',
    };
    const reason = fakeManualTradeReason(row as never);
    expect(reason && reason.startsWith('fake_thesis_marker:')).toBeTruthy();
  });

  it('keeps a genuine user row', () => {
    expect(isFakeManualTradeRow(REAL_ROW as never)).toBe(false);
    expect(fakeManualTradeReason(REAL_ROW as never)).toBeNull();
  });

  it('filterVisibleManualTrades drops fake rows and keeps real ones', () => {
    const fake = { ...REAL_ROW, trade_id: 'MT_6b11745fc3f3' };
    const real = { ...REAL_ROW, trade_id: 'MT_real_one' };
    const out = filterVisibleManualTrades([fake, real] as never[]);
    expect(out).toHaveLength(1);
    expect(out[0].trade_id).toBe('MT_real_one');
  });

  it('filterVisibleManualTrades handles null / undefined safely', () => {
    expect(filterVisibleManualTrades(null)).toEqual([]);
    expect(filterVisibleManualTrades(undefined)).toEqual([]);
  });
});
