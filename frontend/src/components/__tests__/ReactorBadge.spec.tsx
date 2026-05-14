/**
 * Vitest-ready specs for `ReactorBadge` and `ReactorDiagnosticsPanel`.
 *
 * These follow the same convention as
 * `frontend/src/lib/__tests__/nextBestAction.spec.ts`:
 * the file is committed so that the next operator who wires Vitest +
 * React Testing Library can run `npm test` and immediately have meaningful
 * coverage. They do NOT run today — `frontend/package.json` does not yet
 * ship Vitest. See docs/E2E_TEST_PLAN.md or
 * docs/recovery/FRONTEND_TEST_PLAN.md for the install plan.
 *
 * To run, after the FRONTEND_TEST_PLAN install commands:
 *
 *   cd frontend
 *   npx vitest run src/components/__tests__/ReactorBadge.spec.tsx
 *
 * Until then the imports below intentionally rely on test-time globals.
 */
// @ts-ignore - @testing-library/react is added by the FRONTEND_TEST_PLAN
// install step.  Until then this import is stubbed at type-check time.
import { render, screen } from '@testing-library/react';
import { ReactorBadge } from '@/components/ReactorBadge';
import { ReactorDiagnosticsPanel } from '@/components/ReactorDiagnosticsPanel';

// @ts-ignore - vitest globals exist at test time, not at lint time today.
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

describe('ReactorBadge', () => {
  it('renders the canonical reactor state label', () => {
    render(<ReactorBadge state="WARM_WATCH" />);
    const badge = screen.getByTestId('reactor-badge');
    expect(badge.textContent).toMatch(/WARM_WATCH/);
    expect(badge.getAttribute('data-execution-permission')).toBe('false');
  });

  it('renders an UNKNOWN label when state is missing', () => {
    render(<ReactorBadge />);
    const badge = screen.getByTestId('reactor-badge');
    expect(badge.textContent).toMatch(/UNKNOWN/);
  });

  it('renders an UNKNOWN label when state is unrecognised', () => {
    render(<ReactorBadge state="some-future-state" />);
    const badge = screen.getByTestId('reactor-badge');
    expect(badge.textContent).toMatch(/UNKNOWN/);
  });

  it('renders a visible GALLARDO_BLOCK pill when gallardoBlock=true', () => {
    render(<ReactorBadge state="OPERATOR_CONTROL_RODS" gallardoBlock />);
    const block = screen.getByTestId('gallardo-block-badge');
    expect(block.textContent).toMatch(/GALLARDO_BLOCK/);
  });

  it('does NOT render the gallardo block pill when false', () => {
    render(<ReactorBadge state="COLD_OBSERVE" gallardoBlock={false} />);
    expect(screen.queryByTestId('gallardo-block-badge')).toBeNull();
  });

  it('renders REACTOR_UNAVAILABLE pill when reactorAvailable=false', () => {
    render(<ReactorBadge state="INSUFFICIENT_DATA" reactorAvailable={false} />);
    expect(screen.getByTestId('reactor-unavailable-badge').textContent).toMatch(
      /REACTOR_UNAVAILABLE/,
    );
  });

  it('never emits execution / broker / AI-approved copy in any state', () => {
    const states = [
      'COLD_OBSERVE',
      'WARM_WATCH',
      'FUSION_REVIEW_CANDIDATE',
      'FISSION_MAP_ONLY',
      'HOT_CONTAINMENT_REQUIRED',
      'WASTE_DECAY',
      'ECHO_SUPPRESSED',
      'OPERATOR_CONTROL_RODS',
      'INSUFFICIENT_DATA',
    ];
    for (const s of states) {
      const { container, unmount } = render(<ReactorBadge state={s} gallardoBlock />);
      const blob = (container.textContent ?? '').toLowerCase();
      expect(blob).not.toMatch(/place order/);
      expect(blob).not.toMatch(/execute trade/);
      expect(blob).not.toMatch(/broker (api|order)/);
      expect(blob).not.toMatch(/auto[- ]trade/);
      expect(blob).not.toMatch(/permission granted/);
      expect(blob).not.toMatch(/ai[- ]approved/);
      expect(blob).not.toMatch(/trade now/);
      unmount();
    }
  });
});

describe('ReactorDiagnosticsPanel', () => {
  it('renders all eight reactor fields with valid values', () => {
    render(
      <ReactorDiagnosticsPanel
        diagnostics={{
          reactor_state: 'WARM_WATCH',
          decision_grade_energy: 0.42,
          echo_risk_score: 0.18,
          meltdown_risk_score: 0.21,
          fusion_validity: 'weak_fusion',
          fission_branch_clarity: 0.6,
          operator_heat_score: 0.15,
          gallardo_block: false,
          reactor_recommendation: 'watch',
          reactor_available: true,
        }}
      />,
    );
    expect(screen.getByTestId('diag-reactor-state').textContent).toMatch(/WARM_WATCH/);
    expect(screen.getByTestId('diag-recommendation').textContent).toMatch(/watch/);
    expect(screen.getByTestId('diag-decision-grade-energy').textContent).toMatch(/0\.420/);
    expect(screen.getByTestId('diag-echo-risk').textContent).toMatch(/0\.180/);
    expect(screen.getByTestId('diag-meltdown-risk').textContent).toMatch(/0\.210/);
    expect(screen.getByTestId('diag-operator-heat').textContent).toMatch(/0\.150/);
    expect(screen.getByTestId('diag-fusion-validity').textContent).toMatch(/weak_fusion/);
    expect(screen.getByTestId('diag-fission-clarity').textContent).toMatch(/0\.600/);
  });

  it('degrades safely to n/a / unknown when fields are missing', () => {
    render(<ReactorDiagnosticsPanel diagnostics={{}} />);
    expect(screen.getByTestId('diag-reactor-state').textContent).toMatch(/unknown/);
    expect(screen.getByTestId('diag-decision-grade-energy').textContent).toMatch(/n\/a/);
    expect(screen.getByTestId('diag-echo-risk').textContent).toMatch(/n\/a/);
    expect(screen.getByTestId('diag-meltdown-risk').textContent).toMatch(/n\/a/);
    expect(screen.getByTestId('diag-fusion-validity').textContent).toMatch(/unknown/);
    expect(screen.getByTestId('diag-fission-clarity').textContent).toMatch(/n\/a/);
    expect(screen.getByTestId('diag-operator-heat').textContent).toMatch(/n\/a/);
    expect(screen.getByTestId('diag-recommendation').textContent).toMatch(/unknown/);
  });

  it('renders the gallardo block warning callout when gallardo_block=true', () => {
    render(
      <ReactorDiagnosticsPanel
        diagnostics={{
          reactor_state: 'OPERATOR_CONTROL_RODS',
          gallardo_block: true,
        }}
      />,
    );
    const warn = screen.getByTestId('gallardo-block-warning');
    expect(warn.textContent).toMatch(/GALLARDO_BLOCK active/);
    // The warning must explicitly disclaim execution.
    expect(warn.textContent?.toLowerCase()).toMatch(/does not close/);
  });

  it('always shows the ADVISORY_ONLY / HUMAN_EXECUTION_REQUIRED copy', () => {
    render(<ReactorDiagnosticsPanel diagnostics={{}} />);
    expect(screen.getByTestId('copy-advisory-only').textContent).toMatch(/ADVISORY_ONLY/);
    expect(screen.getByTestId('copy-human-execution-required').textContent).toMatch(
      /HUMAN_EXECUTION_REQUIRED/,
    );
    expect(screen.getByTestId('copy-no-authorisation').textContent?.toLowerCase()).toMatch(
      /do not authorise/,
    );
  });

  it('never grants execution permission in DOM data attributes', () => {
    const { container } = render(
      <ReactorDiagnosticsPanel
        diagnostics={{
          reactor_state: 'FUSION_REVIEW_CANDIDATE',
          decision_grade_energy: 0.99,
          gallardo_block: false,
          reactor_available: true,
        }}
      />,
    );
    const panel = screen.getByTestId('reactor-diagnostics-panel');
    expect(panel.getAttribute('data-execution-permission')).toBe('false');
    expect(panel.getAttribute('data-advisory-only')).toBe('true');
    // A high decision-grade-energy must not magically unlock anything.
    expect(container.querySelector('[data-execution-permission="true"]')).toBeNull();
  });

  it('never emits forbidden execution / broker / AI-approved copy', () => {
    const { container } = render(
      <ReactorDiagnosticsPanel
        diagnostics={{
          reactor_state: 'FUSION_REVIEW_CANDIDATE',
          decision_grade_energy: 0.92,
          echo_risk_score: 0.1,
          meltdown_risk_score: 0.1,
          fusion_validity: 'valid_fusion',
          fission_branch_clarity: 0.9,
          operator_heat_score: 0.1,
          gallardo_block: false,
          reactor_recommendation: 'review_candidate',
          reactor_available: true,
        }}
      />,
    );
    const blob = (container.textContent ?? '').toLowerCase();
    expect(blob).not.toMatch(/place order/);
    expect(blob).not.toMatch(/execute trade/);
    expect(blob).not.toMatch(/broker (api|order|connected)/);
    expect(blob).not.toMatch(/auto[- ]trade/);
    expect(blob).not.toMatch(/permission granted/);
    expect(blob).not.toMatch(/ai[- ]approved/);
    expect(blob).not.toMatch(/trade now/);
  });
});
