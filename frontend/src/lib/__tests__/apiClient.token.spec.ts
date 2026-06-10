/**
 * Sprint 8.1 — Vitest spec for apiClient token-mode helpers.
 *
 * The client must:
 *   * round-trip a token through sessionStorage
 *   * attach Authorization: Bearer <token> on EVERY request (the backend
 *     gates reads too via require_api_token_for_reads, so GETs without
 *     the header would 401 once MVP_API_TOKEN is set)
 *   * raise ApiTokenRequiredError on 401/403 with a safe message that
 *     does NOT promise execution permission
 *   * never touch localStorage / cookies
 */
import {
  getStoredApiToken,
  setStoredApiToken,
  clearStoredApiToken,
  hasStoredApiToken,
  ApiTokenRequiredError,
  postManualTrade,
  getManualTrades,
} from '@/lib/apiClient';

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

describe('apiClient token storage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it('round-trips a token through sessionStorage', () => {
    expect(getStoredApiToken()).toBeNull();
    setStoredApiToken('test-token-abc');
    expect(getStoredApiToken()).toBe('test-token-abc');
    expect(hasStoredApiToken()).toBe(true);
    clearStoredApiToken();
    expect(getStoredApiToken()).toBeNull();
    expect(hasStoredApiToken()).toBe(false);
  });

  it('trims whitespace and treats empty/whitespace as clear', () => {
    setStoredApiToken('   ');
    expect(getStoredApiToken()).toBeNull();
    setStoredApiToken('  spaced-token  ');
    expect(getStoredApiToken()).toBe('spaced-token');
  });

  it('never writes to localStorage', () => {
    setStoredApiToken('do-not-leak');
    expect(window.localStorage.length).toBe(0);
  });
});

describe('apiClient request headers', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    // @ts-ignore vitest's vi global
    vi.restoreAllMocks?.();
  });

  it('attaches Authorization on POST when a session token exists', async () => {
    setStoredApiToken('post-token-xyz');
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch' as any)
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ ok: true }),
      } as any);
    await postManualTrade({
      event_id: 'EV',
      ticker: 'X',
      side: 'BUY',
      quantity: 1,
      price: 1,
      thesis: 't',
    }).catch(() => undefined);
    expect(fetchSpy).toHaveBeenCalled();
    const [, init] = fetchSpy.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers['Authorization']).toBe('Bearer post-token-xyz');
  });

  it('attaches Authorization on GET requests too (reads are token-gated)', async () => {
    setStoredApiToken('get-token-abc');
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch' as any)
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ trades: [] }),
      } as any);
    await getManualTrades();
    expect(fetchSpy).toHaveBeenCalled();
    const [, init] = fetchSpy.mock.calls[0];
    const headers = (init as RequestInit | undefined)?.headers as
      | Record<string, string>
      | undefined;
    expect(headers?.['Authorization']).toBe('Bearer get-token-abc');
  });

  it('does not attach Authorization when no token is stored', async () => {
    const fetchSpy = vi
      .spyOn(globalThis, 'fetch' as any)
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ trades: [] }),
      } as any);
    await getManualTrades();
    const [, init] = fetchSpy.mock.calls[0];
    const headers = (init as RequestInit | undefined)?.headers as
      | Record<string, string>
      | undefined;
    expect(headers?.['Authorization']).toBeUndefined();
  });

  it('raises a safe ApiTokenRequiredError on 401', async () => {
    vi.spyOn(globalThis, 'fetch' as any).mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({}),
    } as any);
    let caught: unknown = null;
    try {
      await postManualTrade({
        event_id: 'EV',
        ticker: 'X',
        side: 'BUY',
        quantity: 1,
        price: 1,
        thesis: 't',
      });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiTokenRequiredError);
    const msg = ((caught as Error).message ?? '').toLowerCase();
    expect(msg).toMatch(/mvp_api_token/);
    expect(msg).toMatch(/does not authorize trade execution/);
    // Forbidden execution-y language must not appear.
    expect(msg).not.toMatch(/permission granted/);
    expect(msg).not.toMatch(/place order/);
    expect(msg).not.toMatch(/auto[- ]trade/);
  });
});
