/**
 * Vitest spec for the Manual Trade Log error-routing fix.
 *
 * The form previously caught every error with the same message:
 *   "Failed to log trade — backend may be offline. Start the FastAPI
 *    server and try again."
 * This was wrong for 4xx responses (backend rejected the trade with a
 * structured reason — e.g. rejected_non_user_manual_trade_marker) and
 * for 401/403 token-gate responses.  The patched describeSubmitError
 * helper differentiates:
 *   * ApiHttpError (4xx/5xx) → show status + reason + message
 *   * ApiTokenRequiredError → "set MVP_API_TOKEN" copy
 *   * TypeError (network)   → "backend offline" copy
 *
 * Record-keeping only — no broker call paths are touched.
 */
// @ts-ignore
import { describe, it, expect } from 'vitest';
import {
  describeSubmitError,
} from '@/components/ManualTradeLogForm';
import {
  ApiHttpError,
  ApiTokenRequiredError,
} from '@/lib/apiClient';

describe('describeSubmitError', () => {
  it('routes a 400 with structured reason to a fix-input message (not offline)', () => {
    const err = new ApiHttpError(
      400,
      'rejected: row matches fake-manual-trade marker (fake_thesis_marker:probe)',
      'rejected_non_user_manual_trade_marker',
    );
    const out = describeSubmitError(err);
    expect(out).toMatch(/Backend refused \(HTTP 400\)/);
    expect(out).toMatch(/rejected_non_user_manual_trade_marker/);
    expect(out).not.toMatch(/backend may be offline/i);
    expect(out).not.toMatch(/start the FastAPI server/i);
  });

  it('routes a 422 validation failure to a fix-input message', () => {
    const err = new ApiHttpError(422, 'quantity must be a positive number');
    const out = describeSubmitError(err);
    expect(out).toMatch(/Backend refused \(HTTP 422\)/);
    expect(out).toMatch(/quantity must be a positive number/);
    expect(out).not.toMatch(/offline/i);
  });

  it('routes ApiTokenRequiredError to a token-set message', () => {
    const out = describeSubmitError(new ApiTokenRequiredError(401));
    expect(out).toMatch(/MVP_API_TOKEN/);
    expect(out).not.toMatch(/offline/i);
    // Safety: never claims execution permission was granted.
    expect(out).toMatch(/No broker call was made/);
  });

  it('routes a TypeError (network failure) to the backend-offline message', () => {
    const out = describeSubmitError(new TypeError('Failed to fetch'));
    expect(out).toMatch(/Failed to reach backend/);
    expect(out).toMatch(/127\.0\.0\.1:8000/);
    expect(out).toMatch(/No broker call was made/);
  });

  it('falls through to a safe generic message for unknown errors', () => {
    const out = describeSubmitError({ weird: true });
    expect(out).toMatch(/unexpected error/);
    expect(out).toMatch(/No broker call was made/);
  });

  it('429 rate-limit yields its own copy distinct from offline', () => {
    const out = describeSubmitError(new ApiHttpError(429, 'rate limit'));
    expect(out).toMatch(/HTTP 429/);
    expect(out).not.toMatch(/offline/i);
  });

  it('5xx server error states no broker call was made', () => {
    const out = describeSubmitError(new ApiHttpError(500, 'internal error'));
    expect(out).toMatch(/HTTP 500/);
    expect(out).toMatch(/No broker call was made/);
  });
});
