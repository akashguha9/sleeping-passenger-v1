/**
 * LockdownBanner — renders only when /health reports lockdown_mode=true,
 * stays silent on normal operation and on fetch failure.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { LockdownBanner } from '@/components/LockdownBanner';

// @ts-ignore vitest globals
declare const describe: any, it: any, expect: any, beforeEach: any, vi: any;

describe('LockdownBanner', () => {
  beforeEach(() => {
    vi.restoreAllMocks?.();
  });

  it('renders the banner when lockdown_mode is true', async () => {
    vi.spyOn(globalThis, 'fetch' as any).mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', lockdown_mode: true }),
    } as any);
    render(<LockdownBanner />);
    await waitFor(() =>
      expect(screen.getByTestId('lockdown-banner')).toBeInTheDocument(),
    );
    expect(screen.getByTestId('lockdown-banner').textContent).toMatch(
      /EMERGENCY LOCKDOWN/,
    );
    // Advisory framing: never execution-flavored language.
    expect(screen.getByTestId('lockdown-banner').textContent).not.toMatch(
      /place order|execute order|trade now/i,
    );
  });

  it('renders nothing when lockdown_mode is false', async () => {
    vi.spyOn(globalThis, 'fetch' as any).mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'ok', lockdown_mode: false }),
    } as any);
    const { container } = render(<LockdownBanner />);
    await waitFor(() => expect(container.innerHTML).toBe(''));
  });

  it('renders nothing when the backend is unreachable', async () => {
    vi.spyOn(globalThis, 'fetch' as any).mockRejectedValue(new Error('offline'));
    const { container } = render(<LockdownBanner />);
    await waitFor(() => expect(container.innerHTML).toBe(''));
  });
});
