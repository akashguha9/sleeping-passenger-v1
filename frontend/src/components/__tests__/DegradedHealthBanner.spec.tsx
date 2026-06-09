/**
 * Vitest spec for DegradedHealthBanner (F8 audit fix).
 *
 * The backend's db_write_failures_total / degraded flag must actually
 * RENDER for the operator — a buried JSON field is not observability.
 */
// @ts-ignore
import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

const checkFullHealth = vi.fn();
vi.mock('@/lib/apiClient', () => ({
  checkFullHealth: (...args: unknown[]) => checkFullHealth(...args),
}));

import { DegradedHealthBanner } from '@/components/DegradedHealthBanner';

describe('DegradedHealthBanner', () => {
  beforeEach(() => {
    checkFullHealth.mockReset();
  });

  it('renders a red alert with the failure count when degraded', async () => {
    checkFullHealth.mockResolvedValue({
      status: 'ok',
      degraded: true,
      db_write_failures_total: 3,
    });
    render(<DegradedHealthBanner />);
    await waitFor(() => {
      expect(screen.getByTestId('degraded-health-banner')).toBeInTheDocument();
    });
    expect(screen.getByRole('alert').textContent).toContain('3 database writes lost');
    expect(screen.getByRole('alert').textContent).toContain('FAILING');
  });

  it('renders nothing when healthy', async () => {
    checkFullHealth.mockResolvedValue({
      status: 'ok',
      degraded: false,
      db_write_failures_total: 0,
    });
    const { container } = render(<DegradedHealthBanner />);
    await waitFor(() => expect(checkFullHealth).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="degraded-health-banner"]')).toBeNull();
  });

  it('renders nothing when health is unknown (offline / token-gated)', async () => {
    checkFullHealth.mockResolvedValue(null);
    const { container } = render(<DegradedHealthBanner />);
    await waitFor(() => expect(checkFullHealth).toHaveBeenCalled());
    expect(container.querySelector('[data-testid="degraded-health-banner"]')).toBeNull();
  });
});
