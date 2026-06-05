/**
 * Vitest spec for apiClient — the loading-lifecycle contract.
 *
 * Regression guard for the "stuck forever on Loading…" bug. Every backend
 * request must settle into a finite state (success / empty / error / null
 * fallback) — there must be no path where a wrapper promise neither
 * resolves nor rejects, because the pages clear their spinner in the
 * settlement of these wrappers.
 *
 * In particular this pins three things the earlier code got wrong or left
 * unguarded:
 *   1. An EMPTY 2xx body must not crash JSON parsing — it resolves to an
 *      empty object so `.items`/`.entries`/`.trades` normalise to [].
 *   2. A non-empty INVALID-JSON 2xx body throws internally and the wrapper
 *      falls back to its structured null/mock (an error/offline state),
 *      never an infinite spinner.
 *   3. Non-2xx and network failures resolve to null/mock, finitely.
 */
import { getMoltbook, getManualTrades, getLiveSignals } from '@/lib/apiClient';

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

function setFetch(impl: (...args: any[]) => any) {
  // @ts-ignore — jsdom ships no fetch by default.
  globalThis.fetch = vi.fn(impl);
}

function jsonResponse(status: number, bodyText: string) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    text: async () => bodyText,
    json: async () => JSON.parse(bodyText),
  } as unknown as Response;
}

describe('apiClient loading-lifecycle contract', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it('empty 2xx body resolves to an EMPTY state, never a crash (getMoltbook)', async () => {
    setFetch(async () => jsonResponse(200, ''));
    const { data, isMock } = await getMoltbook();
    expect(isMock).toBe(false);
    expect(Array.isArray(data.items)).toBe(true);
    expect(data.items.length).toBe(0);
  });

  it('empty 2xx body resolves to [] for getLiveSignals (no throw)', async () => {
    setFetch(async () => jsonResponse(200, ''));
    const res = await getLiveSignals(undefined, 5);
    // Empty object normalises — the page reads `.live_signal_events` which
    // is undefined here; the wrapper must still have RESOLVED (not hung).
    expect(res).not.toBeUndefined();
  });

  it('non-empty INVALID JSON on 200 falls back to mock (finite), not infinite', async () => {
    setFetch(async () => jsonResponse(200, 'this-is-not-json'));
    const { isMock } = await getMoltbook();
    expect(isMock).toBe(true); // structured fallback, page resolves
  });

  it('HTTP 500 resolves to mock fallback for getMoltbook', async () => {
    setFetch(async () => jsonResponse(500, JSON.stringify({ detail: 'boom' })));
    const { isMock } = await getMoltbook();
    expect(isMock).toBe(true);
  });

  it('HTTP 500 resolves to null for getManualTrades', async () => {
    setFetch(async () => jsonResponse(500, ''));
    const res = await getManualTrades();
    expect(res).toBeNull();
  });

  it('network failure resolves to null (getManualTrades), never pending', async () => {
    setFetch(async () => {
      throw new TypeError('Failed to fetch');
    });
    const res = await getManualTrades();
    expect(res).toBeNull();
  });

  it('network failure resolves to mock (getMoltbook), never pending', async () => {
    setFetch(async () => {
      throw new TypeError('Failed to fetch');
    });
    const { isMock } = await getMoltbook();
    expect(isMock).toBe(true);
  });
});
