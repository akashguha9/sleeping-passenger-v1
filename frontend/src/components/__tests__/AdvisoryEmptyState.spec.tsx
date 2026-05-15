/**
 * Sprint 9C — Vitest spec for the AdvisoryEmptyState component.
 *
 * The component must:
 *   * render each canonical variant's preset copy
 *   * allow title / message / hint / command overrides
 *   * carry data-advisory-only=true and data-execution-permission=false
 *   * never emit broker/execution/AI-approved copy
 *   * always include a safety-copy footer
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import {
  AdvisoryEmptyState,
  type AdvisoryEmptyStateVariant,
} from '@/components/AdvisoryEmptyState';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const VARIANTS: AdvisoryEmptyStateVariant[] = [
  'no_data',
  'pending_calibration',
  'no_reconciled',
  'no_paper_outcomes',
  'no_refresh_metadata',
  'optional_source_missing',
  'planned_adapter',
  'token_not_set',
  'api_failure',
  'no_template_yet',
];

describe('AdvisoryEmptyState', () => {
  it('renders every canonical variant without crashing and with safety attrs', () => {
    for (const variant of VARIANTS) {
      const { container, unmount } = render(
        <AdvisoryEmptyState variant={variant} />,
      );
      const card = screen.getByTestId('advisory-empty-state');
      expect(card.getAttribute('data-variant')).toBe(variant);
      expect(card.getAttribute('data-advisory-only')).toBe('true');
      expect(card.getAttribute('data-execution-permission')).toBe('false');
      expect(card.getAttribute('data-broker-api-called')).toBe('false');
      expect(screen.getByTestId('empty-title').textContent).toBeTruthy();
      expect(screen.getByTestId('empty-message').textContent).toBeTruthy();
      expect(screen.getByTestId('empty-safety-copy').textContent).toMatch(
        /no execution action/i,
      );
      unmount();
      void container;
    }
  });

  it('honours title/message/hint/command overrides', () => {
    render(
      <AdvisoryEmptyState
        variant="api_failure"
        title="Custom title"
        message="Custom message body"
        hint="Custom hint"
        command="echo hello"
      />,
    );
    expect(screen.getByTestId('empty-title').textContent).toBe('Custom title');
    expect(screen.getByTestId('empty-message').textContent).toBe(
      'Custom message body',
    );
    expect(screen.getByTestId('empty-hint').textContent).toBe('Custom hint');
    expect(screen.getByTestId('empty-command').textContent).toBe('echo hello');
  });

  it('paper-trade variant must NOT imply real money', () => {
    render(<AdvisoryEmptyState variant="no_paper_outcomes" />);
    const blob = (
      screen.getByTestId('advisory-empty-state').textContent ?? ''
    ).toLowerCase();
    expect(blob).not.toMatch(/real money/);
    expect(blob).not.toMatch(/real capital/);
    expect(blob).toMatch(/paper/);
  });

  it('token_not_set variant disclaims trade authorisation', () => {
    render(<AdvisoryEmptyState variant="token_not_set" />);
    const msg = (screen.getByTestId('empty-message').textContent ?? '').toLowerCase();
    expect(msg).toMatch(/does not authorize trade execution/);
  });

  it('never emits forbidden broker / execution / AI-approved copy', () => {
    for (const variant of VARIANTS) {
      const { container, unmount } = render(
        <AdvisoryEmptyState variant={variant} command="example_cmd" hint="hint" />,
      );
      const blob = (container.textContent ?? '').toLowerCase();
      expect(blob).not.toMatch(/place order/);
      expect(blob).not.toMatch(/submit order/);
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
