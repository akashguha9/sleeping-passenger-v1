/**
 * Vitest spec for WatchdogStatusPanel.
 *
 * Renders the extracted panel with sanitized WatchdogSummaryResponse
 * fixtures and asserts every cockpit state path:
 *
 *   - null  -> renders nothing
 *   - MISSING -> renders missing hint, never-ran copy, advisory footer
 *   - HEALTHY -> renders healthy chip, stale-after=none, advisory footer
 *   - STALE_UNCHANGED -> renders stale-after list, Kalshi/GDELT/PMD chips,
 *                       Etherscan excluded chip, parent-stale parent name,
 *                       Kalshi dep-critical marker, advisory footer
 *   - DEGRADED_PARENT_STALE on PMD -> chip surfaces "parent stale: kalshi"
 *   - ERROR -> renders ERROR chip safely
 *   - IMPROVED_BUT_STALE + parent_recovery_detected -> recompute banner
 *
 * Forbidden-language sweep: the rendered DOM must NEVER contain any
 * trade/order/execute/broker-action verb.  This is the structural
 * guarantee that the cockpit cannot accidentally imply execution.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

import { WatchdogStatusPanel } from '@/components/WatchdogStatusPanel';
import type { WatchdogSummaryResponse } from '@/types';

const SAFETY = {
  advisory_only: true,
  human_execution_required: true,
  execution_gate: 'LOCKED',
  broker_api_called: false,
  can_execute: false,
  ai_execution_count: 0,
  execution_permission: false,
};

function missingPayload(): WatchdogSummaryResponse {
  return {
    present: false,
    status: 'MISSING',
    reason: 'refresh_watchdog_summary.json not found',
    summary_path: 'runtime/refresh_watchdog_summary.json',
    loaded_at_utc: '2026-05-25T17:00:00+00:00',
    age_seconds: null,
    age_minutes: null,
    stale: false,
    summary: null,
    ...SAFETY,
  };
}

function summaryBase(overrides: Partial<WatchdogSummaryResponse['summary']> = {}) {
  return {
    operation: 'refresh_watchdog',
    run_id: 'abc',
    status: 'STALE_UNCHANGED',
    ttl_hours: 6,
    max_retries: 3,
    retries_attempted: 1,
    freshness_improved: false,
    improvement_reasons: [],
    backoff_seconds: [60, 180, 300],
    backoff_jitter_pct: 0.15,
    jitter_enabled: true,
    planned_sleep_seconds_per_retry: [62.4],
    actual_sleep_seconds_per_retry: [62.4],
    stale_sources_before: ['kalshi', 'gdelt', 'prediction_market_disagreement'],
    stale_sources_after: ['kalshi', 'gdelt', 'prediction_market_disagreement'],
    excluded_optional_sources: ['etherscan'],
    parent_stale_derived_sources: ['prediction_market_disagreement'],
    derived_source_dependency_status: {
      prediction_market_disagreement: {
        freshness_state: 'degraded_parent_stale',
        is_stale_active: true,
        degraded_parent_stale_parents: ['kalshi'],
        parents: {
          polymarket: {
            freshness_state: 'fresh',
            is_stale_active: false,
            dependency_critical: false,
          },
          kalshi: {
            freshness_state: 'stale',
            is_stale_active: true,
            dependency_critical: true,
          },
        },
      },
    },
    dependency_critical_sources: ['kalshi'],
    kalshi_freshness_before: 'stale',
    kalshi_freshness_after: 'stale',
    prediction_market_disagreement_freshness_before: 'degraded_parent_stale',
    prediction_market_disagreement_freshness_after: 'degraded_parent_stale',
    kalshi_status_before: {
      freshness_state: 'stale',
      is_stale_active: true,
      dependency_critical: true,
      used_by: ['prediction_market_disagreement'],
      stale_severity: 'dependency_blocking',
    },
    kalshi_status_after: {
      freshness_state: 'stale',
      is_stale_active: true,
      dependency_critical: true,
      used_by: ['prediction_market_disagreement'],
      stale_severity: 'dependency_blocking',
    },
    gdelt_status_before: { freshness_state: 'stale', is_stale_active: true },
    gdelt_status_after: { freshness_state: 'stale', is_stale_active: true },
    started_at_utc: '2026-05-25T17:15:00+00:00',
    finished_at_utc: '2026-05-25T17:16:17+00:00',
    generated_at_utc: '2026-05-25T17:16:17+00:00',
    ...overrides,
  };
}

function payload(
  status: string,
  overrides: Partial<WatchdogSummaryResponse> = {},
): WatchdogSummaryResponse {
  const inner = summaryBase({ status });
  return {
    present: true,
    status,
    reason: null,
    summary_path: 'runtime/refresh_watchdog_summary.json',
    loaded_at_utc: '2026-05-25T17:17:00+00:00',
    age_seconds: 43,
    age_minutes: 0.72,
    stale: false,
    summary_stale_after_minutes: 60,
    summary: inner,
    ...SAFETY,
    ...overrides,
  };
}

// Forbidden verbs/phrases that must never appear in the rendered DOM
// regardless of payload — pins the safety contract structurally.
const FORBIDDEN_LANGUAGE = [
  'place order',
  'submit order',
  'execute trade',
  'place trade',
  'place a trade',
  'broker action',
  'auto trade',
  'trade now',
];

function assertNoExecutionLanguage(container: HTMLElement) {
  const text = (container.textContent ?? '').toLowerCase();
  for (const needle of FORBIDDEN_LANGUAGE) {
    expect(text).not.toContain(needle);
  }
}

describe('WatchdogStatusPanel', () => {
  it('renders nothing when summary is null', () => {
    const { container } = render(<WatchdogStatusPanel summary={null} />);
    expect(container.querySelector('[data-testid="watchdog-status-panel"]')).toBeNull();
  });

  it('MISSING -> shows missing chip, hint, advisory footer; no execution copy', () => {
    const { container } = render(<WatchdogStatusPanel summary={missingPayload()} />);
    const panel = screen.getByTestId('watchdog-status-panel');
    expect(panel.getAttribute('data-watchdog-status')).toBe('MISSING');
    expect(panel.getAttribute('data-watchdog-present')).toBe('false');
    expect(screen.getByTestId('watchdog-status-chip').textContent).toMatch(
      /MISSING/,
    );
    expect(screen.getByTestId('watchdog-missing-hint').textContent).toMatch(
      /watchdog_refresh_stale_sources\.py/,
    );
    expect(screen.getByTestId('watchdog-never-ran').textContent).toMatch(
      /not found|has not produced a summary/i,
    );
    expect(screen.getByTestId('watchdog-advisory-footer').textContent).toMatch(
      /advisory-only/i,
    );
    expect(screen.getByTestId('watchdog-advisory-footer').textContent).toMatch(
      /does not trade/i,
    );
    assertNoExecutionLanguage(container);
  });

  it('HEALTHY -> shows healthy chip, stale-after=none, advisory footer', () => {
    const data = payload('HEALTHY', {
      summary: summaryBase({
        status: 'HEALTHY',
        stale_sources_after: [],
        freshness_improved: true,
      }),
    });
    const { container } = render(<WatchdogStatusPanel summary={data} />);
    expect(screen.getByTestId('watchdog-status-chip').textContent).toMatch(
      /HEALTHY/,
    );
    expect(screen.getByTestId('watchdog-stale-after').textContent).toMatch(
      /none/,
    );
    expect(screen.getByTestId('watchdog-advisory-footer')).toBeTruthy();
    assertNoExecutionLanguage(container);
  });

  it('STALE_UNCHANGED -> renders stale lists, Kalshi/GDELT/PMD chips, Etherscan excluded, dep-critical marker', () => {
    const data = payload('STALE_UNCHANGED');
    const { container } = render(<WatchdogStatusPanel summary={data} />);
    expect(screen.getByTestId('watchdog-status-chip').textContent).toMatch(
      /STALE/,
    );
    expect(screen.getByTestId('watchdog-stale-before').textContent).toMatch(
      /kalshi/,
    );
    expect(screen.getByTestId('watchdog-stale-after').textContent).toMatch(
      /kalshi/,
    );
    expect(screen.getByTestId('watchdog-excluded-optional').textContent).toMatch(
      /etherscan/,
    );
    expect(screen.getByTestId('watchdog-dependency-critical').textContent).toMatch(
      /kalshi/,
    );

    const kalshiChip = screen.getByTestId('watchdog-source-chip-kalshi');
    expect(kalshiChip.getAttribute('data-is-stale-active')).toBe('true');
    expect(kalshiChip.getAttribute('data-dependency-critical')).toBe('true');
    expect(kalshiChip.textContent).toMatch(/dep-critical/);

    const gdeltChip = screen.getByTestId('watchdog-source-chip-gdelt');
    expect(gdeltChip.getAttribute('data-is-stale-active')).toBe('true');

    const pmdChip = screen.getByTestId(
      'watchdog-source-chip-prediction_market_disagreement',
    );
    expect(pmdChip.getAttribute('data-freshness-after')).toBe(
      'degraded_parent_stale',
    );
    expect(pmdChip.textContent).toMatch(/parent stale: kalshi/);

    expect(screen.getByTestId('watchdog-source-chip-etherscan').textContent).toMatch(
      /excluded optional/i,
    );

    expect(screen.getByTestId('watchdog-advisory-footer').textContent).toMatch(
      /advisory-only/i,
    );
    assertNoExecutionLanguage(container);
  });

  it('ERROR -> renders error chip safely without execution language', () => {
    const data = payload('ERROR', {
      summary: summaryBase({ status: 'ERROR' }),
    });
    const { container } = render(<WatchdogStatusPanel summary={data} />);
    expect(screen.getByTestId('watchdog-status-chip').textContent).toMatch(/ERROR/);
    expect(screen.getByTestId('watchdog-advisory-footer')).toBeTruthy();
    assertNoExecutionLanguage(container);
  });

  it('summary stale (> 60m) -> renders stale-summary chip', () => {
    const data = payload('STALE_UNCHANGED', {
      stale: true,
      age_minutes: 92.5,
      summary_stale_after_minutes: 60,
    });
    render(<WatchdogStatusPanel summary={data} />);
    expect(screen.getByTestId('watchdog-summary-stale-chip').textContent).toMatch(
      /Summary stale/,
    );
  });

  it('IMPROVED_BUT_STALE + parent_recovery_detected -> shows recompute banner', () => {
    const data = payload('IMPROVED_BUT_STALE', {
      summary: {
        ...summaryBase({ status: 'IMPROVED_BUT_STALE' }),
        freshness_improved: true,
        improvement_reasons: ['stale_cleared'],
        parent_recovery_detected: true,
        disagreement_recompute_invoked_in_tick: true,
      } as any,
    });
    const { container } = render(<WatchdogStatusPanel summary={data} />);
    const banner = screen.getByTestId('watchdog-parent-recovery');
    expect(banner.textContent).toMatch(/Parent recovery detected/);
    expect(banner.textContent).toMatch(/Disagreement recompute invoked/);
    const panel = screen.getByTestId('watchdog-status-panel');
    expect(panel.getAttribute('data-parent-recovery-detected')).toBe('true');
    expect(panel.getAttribute('data-disagreement-recompute-invoked')).toBe('true');
    assertNoExecutionLanguage(container);
  });

  it('improvement_reasons render when freshness_improved=true', () => {
    const data = payload('IMPROVED_BUT_STALE', {
      summary: summaryBase({
        status: 'IMPROVED_BUT_STALE',
        freshness_improved: true,
        improvement_reasons: ['stale_cleared', 'newer_last_success_at'],
      }),
    });
    render(<WatchdogStatusPanel summary={data} />);
    expect(screen.getByTestId('watchdog-improvement-reasons').textContent).toMatch(
      /stale_cleared/,
    );
  });
});
