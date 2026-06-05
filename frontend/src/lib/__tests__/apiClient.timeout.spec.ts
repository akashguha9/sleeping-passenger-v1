/**
 * Regression spec for the infinite-loading root cause.
 *
 * The browser `fetch()` API has no default timeout. When the backend is
 * reachable-but-hanging (slow/blocking DB query) or the host DROPs packets
 * instead of refusing the connection, a bare `fetch()` never settles. Because
 * every dashboard screen clears its `loading` flag only after its
 * `Promise.all` resolves, a single hung request left all five tabs stuck on
 * "Loading…" forever.
 *
 * `apiFetch` now bounds every request with an AbortController-backed timeout.
 * These tests assert that a hung request settles (via the helpers' existing
 * mock/null fallbacks) instead of hanging, that a malformed body is handled,
 * and that the timeout error carries a safe, non-execution message.
 */
import {
  getLiveSignals,
  getSignals,
  getManualTrades,
  ApiTimeoutError,
} from '@/lib/apiClient';
import { API_TIMEOUT_MS } from '@/lib/config';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;
// @ts-ignore
declare const afterEach: any;
// @ts-ignore
declare const vi: any;

/**
 * A fetch mock that never resolves on its own — it only rejects with an
 * AbortError when the AbortSignal passed by apiFetch fires. This faithfully
 * models a hung backend / dropped-packet network policy.
 */
function hangingFetch() {
  return vi
    .spyOn(globalThis, 'fetch' as any)
    .mockImplementation((_url: string, init?: RequestInit) => {
      return new Promise((_resolve, reject) => {
        const signal = init?.signal;
        if (signal) {
          signal.addEventListener('abort', () => {
            const err = new Error('The operation was aborted.');
            err.name = 'AbortError';
            reject(err);
          });
        }
      });
    });
}

describe('apiClient request timeout (infinite-loading guard)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it('getLiveSignals resolves to null (not hang) when the backend never responds', async () => {
    hangingFetch();
    const promise = getLiveSignals();
    // Drive past the configured timeout; the AbortController should fire.
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 500);
    await expect(promise).resolves.toBeNull();
  });

  it('getManualTrades resolves to null (not hang) when the backend never responds', async () => {
    hangingFetch();
    const promise = getManualTrades();
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 500);
    await expect(promise).resolves.toBeNull();
  });

  it('getSignals falls back to mock data (not hang) when the backend never responds', async () => {
    hangingFetch();
    const promise = getSignals();
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 500);
    const result = await promise;
    expect(result.isMock).toBe(true);
    expect(Array.isArray(result.data.items)).toBe(true);
  });

  it('a malformed JSON 2xx body is handled as a fallback, never an unhandled crash', async () => {
    vi.spyOn(globalThis, 'fetch' as any).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => {
        throw new SyntaxError('Unexpected end of JSON input');
      },
    } as any);
    await expect(getManualTrades()).resolves.toBeNull();
  });
});

describe('ApiTimeoutError shape and safety', () => {
  it('exposes a safe, non-execution message and the timeout duration', () => {
    const err = new ApiTimeoutError(12000);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe('ApiTimeoutError');
    expect(err.timeoutMs).toBe(12000);
    const msg = err.message.toLowerCase();
    expect(msg).toMatch(/timed out/);
    // Must never imply trade execution.
    expect(msg).not.toMatch(/order/);
    expect(msg).not.toMatch(/execut/);
    expect(msg).not.toMatch(/broker/);
  });
});
