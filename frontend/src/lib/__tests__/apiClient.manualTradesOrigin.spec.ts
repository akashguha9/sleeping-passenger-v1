/**
 * Vitest spec for apiClient.getManualTrades — origin-filter contract.
 *
 * The leaked-AAPL incident was caused by the Manual Trade Log page
 * fetching `/manual-trades` with no `origin` query, which returned every
 * row in the DB (822 of them) including 799 with empty `created_via`.
 *
 * This spec locks in the contract that the client ALWAYS sends
 * `origin=manual_trade_log` unless the caller explicitly asks for the
 * audit ("all") scope.
 */
import { getManualTrades } from '@/lib/apiClient';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;
// @ts-ignore
declare const vi: any;

const FAKE_OK = {
  operation: 'list_manual_trades',
  trade_count: 0,
  trades: [],
  advisory_status: 'ADVISORY_ONLY',
  execution_mode: 'HUMAN_ONLY',
  ai_execution_count: 0,
  human_review_required: true,
  broker_api_called: false,
  generated_at: '2026-05-18T00:00:00Z',
};

function makeFetchSpy() {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => FAKE_OK,
    text: async () => JSON.stringify(FAKE_OK),
  } as unknown as Response);
  // jsdom doesn't ship fetch by default — provide it.
  // @ts-ignore
  globalThis.fetch = spy;
  return spy;
}

describe('apiClient.getManualTrades origin scope', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('defaults to origin=manual_trade_log when caller passes nothing', async () => {
    const spy = makeFetchSpy();
    await getManualTrades();
    expect(spy).toHaveBeenCalledTimes(1);
    const url = spy.mock.calls[0][0] as string;
    expect(url).toMatch(/[?&]origin=manual_trade_log\b/);
  });

  it('still sends origin=manual_trade_log when caller passes an empty options object', async () => {
    const spy = makeFetchSpy();
    await getManualTrades({});
    expect(spy).toHaveBeenCalledTimes(1);
    const url = spy.mock.calls[0][0] as string;
    expect(url).toMatch(/[?&]origin=manual_trade_log\b/);
  });

  it('honours an explicit origin override (audit/all scope)', async () => {
    const spy = makeFetchSpy();
    await getManualTrades({ origin: 'all' });
    expect(spy).toHaveBeenCalledTimes(1);
    const url = spy.mock.calls[0][0] as string;
    expect(url).toMatch(/[?&]origin=all\b/);
    expect(url).not.toMatch(/[?&]origin=manual_trade_log\b/);
  });

  it('returns null on fetch failure — never a synthetic fallback array', async () => {
    // @ts-ignore
    globalThis.fetch = vi.fn().mockRejectedValue(new Error('network down'));
    const result = await getManualTrades();
    expect(result).toBeNull();
  });
});
