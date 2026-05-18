// Defensive frontend filter for fake / synthetic Manual Trade Log rows.
//
// The backend ``GET /manual-trades`` already filters fake rows out via
// ``scripts/manual_trade_origin.is_visible_manual_trade``.  This module
// is the final defensive layer: if a row ever arrives carrying a fake
// marker (because the backend was rolled back, the DB was hand-patched,
// or a proxy injected something), the UI still refuses to render it.
//
// Rules mirror the Python module so the two paths cannot drift —
// keep these in sync when adding new markers.  Read-only; no broker
// implications.

import type { ManualTradeLog } from '@/types';

export const FAKE_TRADE_IDS: ReadonlySet<string> = new Set([
  'MT_6b11745fc3f3',
  'MT_b1554a7e78a7',
]);

export const FAKE_THESIS_SUBSTRINGS: readonly string[] = [
  'probe',
  'test',
  'seed',
  'demo',
  'fixture',
  'smoke',
  'sample',
  'mock',
  'no currency given',
];

export const FAKE_EVENT_ID_PREFIXES: readonly string[] = [
  'EV_AAPL',
  'TEST_',
  'SEED_',
  'DEMO_',
  'MOCK_',
  'SAMPLE_',
  'SMOKE_',
  'FIXTURE_',
  'FABRIC_',
];

export const FAKE_LOGGED_BY_VALUES: ReadonlySet<string> = new Set([
  'automation',
  'seed',
  'smoke_test',
  'smoke',
  'fixture',
  'mock',
  'sample',
  'calibration_seed',
  'probe',
  'system',
  'demo',
  'test',
]);

const FAKE_AAPL_QUANTITIES: ReadonlySet<number> = new Set([5, 10]);
const FAKE_AAPL_PRICE = 180;
const FAKE_AAPL_TICKER = 'AAPL';

function containsMarker(text: string | null | undefined): string | null {
  if (!text) return null;
  const lowered = text.trim().toLowerCase();
  if (!lowered) return null;
  for (const marker of FAKE_THESIS_SUBSTRINGS) {
    if (lowered.includes(marker)) return marker;
  }
  return null;
}

/**
 * Return a short reason if ``row`` matches a fake-marker rule, or
 * ``null`` if it does not.  Mirrors
 * ``scripts.manual_trade_origin.fake_manual_trade_reason``.
 */
export function fakeManualTradeReason(
  row: Partial<ManualTradeLog> & Record<string, unknown>,
): string | null {
  if (!row || typeof row !== 'object') return null;

  const tradeId = String(row.trade_id ?? '').trim();
  if (FAKE_TRADE_IDS.has(tradeId)) return 'fake_trade_id_blocklist';

  const ticker = String(row.ticker ?? '').trim().toUpperCase();
  const price = Number(row.price ?? 0);
  const quantity = Number(row.quantity ?? 0);
  if (
    ticker === FAKE_AAPL_TICKER &&
    price === FAKE_AAPL_PRICE &&
    FAKE_AAPL_QUANTITIES.has(quantity)
  ) {
    return 'fake_aapl_fingerprint';
  }

  const eventId = String(row.event_id ?? '').trim();
  for (const prefix of FAKE_EVENT_ID_PREFIXES) {
    if (eventId.startsWith(prefix)) return 'fake_event_id_prefix';
  }

  const thesisHit = containsMarker(String(row.thesis ?? ''));
  if (thesisHit) return `fake_thesis_marker:${thesisHit}`;
  const notesHit = containsMarker(String((row as { notes?: string }).notes ?? ''));
  if (notesHit) return `fake_notes_marker:${notesHit}`;
  const reasonHit = containsMarker(
    String((row as { risk_reason?: string }).risk_reason ?? ''),
  );
  if (reasonHit) return `fake_risk_reason_marker:${reasonHit}`;

  for (const sourceKey of ['logged_by', 'created_by', 'source'] as const) {
    const sourceVal = String((row as Record<string, unknown>)[sourceKey] ?? '')
      .trim()
      .toLowerCase();
    if (sourceVal && FAKE_LOGGED_BY_VALUES.has(sourceVal)) {
      return `fake_source:${sourceKey}=${sourceVal}`;
    }
  }

  const aiModelUsed = String(row.ai_model_used ?? '').trim();
  if (!aiModelUsed) {
    for (const field of ['thesis', 'notes'] as const) {
      if (containsMarker(String((row as Record<string, unknown>)[field] ?? ''))) {
        return 'fake_empty_ai_model_with_marker';
      }
    }
  }

  return null;
}

export function isFakeManualTradeRow(
  row: Partial<ManualTradeLog> & Record<string, unknown>,
): boolean {
  return fakeManualTradeReason(row) !== null;
}

/** Strip rows that match a fake-marker rule. Pure, read-only. */
export function filterVisibleManualTrades(
  rows: readonly ManualTradeLog[] | null | undefined,
): ManualTradeLog[] {
  if (!rows) return [];
  return rows.filter((r) => !isFakeManualTradeRow(r as never));
}
