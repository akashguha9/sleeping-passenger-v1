export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

/**
 * Per-request network timeout (milliseconds) for every browser → backend
 * call routed through `apiFetch`.
 *
 * Why this exists: the browser `fetch()` API has NO default timeout. When
 * the backend is reachable-but-hanging (slow/blocking DB query) or when the
 * host drops packets instead of refusing the connection (common behind a
 * restrictive network policy), a bare `fetch()` never settles. Every
 * dashboard screen clears its `loading` flag only after its `Promise.all`
 * resolves, so a single hung request leaves the whole tab stuck on
 * "Loading…" forever.
 *
 * Bounding each request guarantees the promise always settles, the existing
 * mock/null fallbacks fire, and the UI resolves to an error/empty/ready
 * state instead of infinite loading.
 *
 * Override with `NEXT_PUBLIC_API_TIMEOUT_MS`. A non-positive or non-numeric
 * value falls back to the 12s default.
 */
const RAW_TIMEOUT = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS);
export const API_TIMEOUT_MS =
  Number.isFinite(RAW_TIMEOUT) && RAW_TIMEOUT > 0 ? RAW_TIMEOUT : 12_000;
