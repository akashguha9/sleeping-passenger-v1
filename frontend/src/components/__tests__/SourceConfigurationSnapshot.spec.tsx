/**
 * SourceConfigurationSnapshot spec — Identity Collapse sprint, Phase 4.
 *
 * Properties under test
 *   * Renders configured/total + percentage and the per-state counts.
 *   * Renders the "unavailable" state when isMock=true OR status=null.
 *   * Surfaces the watchdog status when provided.
 *   * Never emits execution-style copy.
 *   * computeSnapshotCounts: configured + not_configured == total.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import {
  SourceConfigurationSnapshot,
  computeSnapshotCounts,
} from '@/components/SourceConfigurationSnapshot';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

const FRESHNESS_KEY = 'freshness_state';

function _entry(configured: boolean, state: string) {
  return {
    credential_configured: configured,
    [FRESHNESS_KEY]: state,
  } as unknown as Record<string, unknown>;
}

function _status(entries: Record<string, ReturnType<typeof _entry>>) {
  return {
    operation: 'live_sources_status',
    sources: entries,
    source_count: Object.keys(entries).length,
    freshness_distribution: {},
    advisory_status: 'ADVISORY_ONLY',
    execution_gate: 'LOCKED',
    broker_api_called: false,
    ai_execution_count: 0,
    execution_permission: false,
    can_execute: false,
    human_review_required: true,
  } as any;
}

describe('computeSnapshotCounts', () => {
  it('returns zeros for null status', () => {
    const counts = computeSnapshotCounts(null);
    expect(counts.total).toBe(0);
    expect(counts.configured).toBe(0);
    expect(counts.completeness).toBe(0);
  });

  it('maintains configured + not_configured == total', () => {
    const status = _status({
      polymarket: _entry(true, 'fresh'),
      gdelt: _entry(true, 'stale'),
      sec_edgar: _entry(false, 'skipped'),
      etherscan: _entry(false, 'skipped'),
    });
    const counts = computeSnapshotCounts(status);
    expect(counts.total).toBe(4);
    expect(counts.configured + counts.not_configured).toBe(counts.total);
    expect(counts.configured).toBe(2);
    expect(counts.completeness).toBeCloseTo(0.5);
  });

  it('counts fresh / stale / degraded / failed states', () => {
    const status = _status({
      a: _entry(true, 'fresh'),
      b: _entry(true, 'stale'),
      c: _entry(true, 'degraded_parent_stale'),
      d: _entry(true, 'failed'),
      e: _entry(true, 'overdue'),
      f: _entry(false, 'skipped'),
    });
    const counts = computeSnapshotCounts(status);
    expect(counts.fresh).toBe(1);
    expect(counts.stale).toBe(1);
    expect(counts.degraded).toBe(1);
    expect(counts.failed).toBe(1);
    expect(counts.overdue).toBe(1);
    expect(counts.skipped).toBe(1);
  });
});

describe('SourceConfigurationSnapshot — render', () => {
  it('renders "unavailable" copy when isMock=true', () => {
    render(<SourceConfigurationSnapshot status={null} isMock={true} />);
    const tile = screen.getByTestId('source-configuration-snapshot');
    expect(tile.getAttribute('data-snapshot-state')).toBe('unavailable');
    expect(tile.textContent).toMatch(/unavailable/i);
    expect(tile.textContent).toMatch(/mock UI state active/i);
  });

  it('renders "unavailable" copy when status=null', () => {
    render(<SourceConfigurationSnapshot status={null} isMock={false} />);
    const tile = screen.getByTestId('source-configuration-snapshot');
    expect(tile.getAttribute('data-snapshot-state')).toBe('unavailable');
  });

  it('renders configured/total counts and percentage', () => {
    const status = _status({
      polymarket: _entry(true, 'fresh'),
      gdelt: _entry(true, 'fresh'),
      sec_edgar: _entry(false, 'skipped'),
    });
    render(<SourceConfigurationSnapshot status={status} isMock={false} />);
    const tile = screen.getByTestId('source-configuration-snapshot');
    expect(tile.getAttribute('data-snapshot-state')).toBe('present');
    expect(tile.getAttribute('data-configured')).toBe('2');
    expect(tile.getAttribute('data-total')).toBe('3');
    expect(tile.getAttribute('data-not-configured')).toBe('1');
    expect(tile.textContent).toMatch(/2\/3/);
    expect(tile.textContent).toMatch(/67%/);
  });

  it('renders fresh/stale/degraded/failed counts in the visible string', () => {
    const status = _status({
      a: _entry(true, 'fresh'),
      b: _entry(true, 'stale'),
      c: _entry(true, 'degraded_parent_stale'),
      d: _entry(true, 'failed'),
    });
    render(<SourceConfigurationSnapshot status={status} isMock={false} />);
    expect(screen.getByTestId('snapshot-fresh').textContent).toBe('1');
    expect(screen.getByTestId('snapshot-stale').textContent).toBe('1');
    expect(screen.getByTestId('snapshot-degraded').textContent).toBe('1');
    expect(screen.getByTestId('snapshot-failed').textContent).toBe('1');
  });

  it('surfaces the watchdog status when supplied', () => {
    const status = _status({ a: _entry(true, 'fresh') });
    render(
      <SourceConfigurationSnapshot
        status={status}
        isMock={false}
        watchdogStatus="HEALTHY"
      />,
    );
    expect(screen.getByTestId('snapshot-watchdog').textContent).toMatch(/HEALTHY/i);
  });

  it('does not emit execution-style copy', () => {
    const status = _status({ a: _entry(true, 'fresh') });
    const { container } = render(
      <SourceConfigurationSnapshot status={status} isMock={false} />,
    );
    const text = container.textContent || '';
    expect(text.toLowerCase()).not.toMatch(/\bbuy\b/);
    expect(text.toLowerCase()).not.toMatch(/\bsell\b/);
    expect(text.toLowerCase()).not.toMatch(/\bexecute\b/);
    expect(text.toLowerCase()).not.toMatch(/\bplace order\b/);
  });
});
