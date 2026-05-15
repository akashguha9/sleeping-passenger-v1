/**
 * Sprint 7D.1 — Vitest spec for the SourceHealthBadge component.
 *
 * The badge renders the per-source health label + score chip.  It must:
 *   * render the canonical label (healthy/watch/degraded/unhealthy/planned/optional_missing)
 *   * render the numeric score when present
 *   * carry data-advisory-only=true and data-execution-permission=false
 *   * never emit broker/execution/AI-approved copy
 *   * optionally render the top reason inline when showReason=true
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { SourceHealthBadge } from '@/components/SourceHealthBadge';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('SourceHealthBadge', () => {
  it('renders the healthy label and score', () => {
    render(
      <SourceHealthBadge
        entry={{
          health_label: 'healthy',
          health_score: 0.95,
          health_reasons: ['recent successful refresh'],
          operator_message: 'Source is healthy — recent successful refresh.',
          tier: 'core',
        }}
      />,
    );
    const badge = screen.getByTestId('source-health-badge');
    expect(badge.getAttribute('data-health-label')).toBe('healthy');
    expect(badge.getAttribute('data-health-score')).toBe('0.95');
    expect(badge.getAttribute('data-advisory-only')).toBe('true');
    expect(badge.getAttribute('data-execution-permission')).toBe('false');
    expect(badge.textContent).toMatch(/healthy/);
    expect(badge.textContent).toMatch(/0\.95/);
  });

  it('renders the planned_not_scored badge with no numeric score', () => {
    render(
      <SourceHealthBadge
        entry={{
          health_label: 'planned_not_scored',
          health_score: null,
          health_reasons: ['adapter_status=planned — not counted as failure'],
          operator_message: 'Planned source adapter — not counted as a failure.',
          tier: 'planned',
        }}
      />,
    );
    const badge = screen.getByTestId('source-health-badge');
    expect(badge.getAttribute('data-health-label')).toBe('planned_not_scored');
    expect(badge.getAttribute('data-health-score')).toBe('');
    expect(badge.textContent).toMatch(/planned_not_scored/);
  });

  it('renders the optional_config_missing badge as soft state', () => {
    render(
      <SourceHealthBadge
        entry={{
          health_label: 'optional_config_missing',
          health_score: null,
          health_reasons: ['optional source missing credential'],
          operator_message: 'Optional source not configured.',
          tier: 'optional',
        }}
      />,
    );
    const badge = screen.getByTestId('source-health-badge');
    expect(badge.getAttribute('data-health-label')).toBe('optional_config_missing');
  });

  it('renders the top reason when showReason=true', () => {
    render(
      <SourceHealthBadge
        showReason
        entry={{
          health_label: 'degraded',
          health_score: 0.5,
          health_reasons: ['freshness_state=stale (tier=core)'],
          operator_message: 'Core source is degraded.',
          tier: 'core',
        }}
      />,
    );
    expect(screen.getByTestId('source-health-reason').textContent).toMatch(
      /freshness_state=stale/,
    );
  });

  it('never emits forbidden broker / execution / AI-approved copy', () => {
    const labels = [
      'healthy',
      'watch',
      'degraded',
      'unhealthy',
      'planned_not_scored',
      'optional_config_missing',
    ] as const;
    for (const label of labels) {
      const { container, unmount } = render(
        <SourceHealthBadge
          showReason
          entry={{
            health_label: label,
            health_score: 0.5,
            health_reasons: ['test reason'],
            operator_message: 'test message',
            tier: 'core',
          }}
        />,
      );
      const blob = (container.textContent ?? '').toLowerCase();
      expect(blob).not.toMatch(/place order/);
      expect(blob).not.toMatch(/execute trade/);
      expect(blob).not.toMatch(/broker (api|order|connected)/);
      expect(blob).not.toMatch(/auto[- ]trade/);
      expect(blob).not.toMatch(/ai[- ]approved/);
      expect(blob).not.toMatch(/permission granted/);
      expect(blob).not.toMatch(/trade now/);
      unmount();
    }
  });
});
