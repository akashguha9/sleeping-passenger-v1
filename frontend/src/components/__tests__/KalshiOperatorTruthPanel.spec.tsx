/**
 * Vitest spec for KalshiOperatorTruthPanel.
 *
 * Renders the panel with a sanitized source-health fixture and asserts:
 *   - mode / env / status / records / pages / seek-allowed / allowed-found
 *     all surface honest values.
 *   - accepted + quarantined category breakdowns render.
 *   - LIVE_VERIFIED + read-only + execution locked render.
 *   - The honest empty-allowed-scope message renders only when
 *     records_allowed=0 and status=LIVE_VERIFIED_SOURCE_EMPTY_FOR_ALLOWED_SCOPE.
 *   - Auth headers / API Key ID / private-key path never appear in the
 *     rendered DOM, even if the upstream payload accidentally carried them.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;

import { KalshiOperatorTruthPanel } from '@/components/KalshiOperatorTruthPanel';
import type { KalshiSourceHealthResponse } from '@/types';

function baseHealth(
  overrides: Partial<KalshiSourceHealthResponse> = {},
): KalshiSourceHealthResponse {
  return {
    source_name: 'kalshi',
    artifact_kind: 'kalshi_source_health',
    attempted_at_utc: '2026-05-25T15:00:00+00:00',
    completed_at_utc: '2026-05-25T15:00:01+00:00',
    status: 'OK',
    records_seen_total: 100,
    records_allowed: 7,
    records_quarantined: 90,
    records_persisted: 0,
    records_dropped: 3,
    allowed_categories: [
      'commodities',
      'crypto',
      'economics',
      'elections',
      'finance',
      'politics',
      'tech_science',
    ],
    category_allowed_counts: { commodities: 4, finance: 3 },
    category_rejected_counts: { Weather: 70, Sports: 20 },
    quarantine_reason_counts: { category_not_in_allowlist: 90 },
    last_successful_fetch_at_utc: '2026-05-25T15:00:01+00:00',
    freshness_ttl_seconds: 21600,
    source_freshness_status: 'LIVE_VERIFIED',
    is_mock_run: false,
    mode: 'live_read_only',
    env: 'demo',
    auth_used: true,
    api_base_url: 'https://external-api.demo.kalshi.co/trade-api/v2',
    dry_run: true,
    seek_allowed: true,
    min_allowed: 1,
    allowed_found: true,
    pages_scanned: 3,
    cursor_exhausted: false,
    first_allowed_seen_at_page: 2,
    accepted_sample_titles: ['Will WTI crude close above $80?'],
    accepted_sample_categories: ['Commodities', 'Finance'],
    quarantined_sample_categories: ['Weather', 'Sports'],
    raw_payload_stored: false,
    event_enrichment_attempted: 5,
    event_enrichment_succeeded: 4,
    event_enrichment_failed: 1,
    event_enrichment_failure_rate: 0.2,
    advisory_only: true,
    human_review_required: true,
    execution_locked: true,
    broker_api_called: false,
    ai_execution_count: 0,
    ...overrides,
  };
}

describe('KalshiOperatorTruthPanel', () => {
  it('renders the live_read_only operator panel with sanitized fields', () => {
    render(<KalshiOperatorTruthPanel data={baseHealth()} />);
    const panel = screen.getByTestId('kalshi-operator-truth-panel');
    expect(panel.getAttribute('data-mode')).toBe('live_read_only');
    expect(panel.getAttribute('data-env')).toBe('demo');
    expect(panel.getAttribute('data-source-status')).toBe('LIVE_VERIFIED');
    expect(panel.getAttribute('data-auth-used')).toBe('true');
    expect(panel.getAttribute('data-read-only')).toBe('true');
    expect(panel.getAttribute('data-execution-locked')).toBe('true');
    expect(panel.getAttribute('data-broker-api-called')).toBe('false');
    expect(panel.getAttribute('data-ai-execution-count')).toBe('0');
  });

  it('renders records seen / allowed / quarantined and pages scanned', () => {
    render(<KalshiOperatorTruthPanel data={baseHealth()} />);
    expect(screen.getByTestId('kalshi-operator-records-seen').textContent).toMatch(/100/);
    expect(
      screen.getByTestId('kalshi-operator-records-allowed').textContent,
    ).toMatch(/7/);
    expect(
      screen.getByTestId('kalshi-operator-records-quarantined').textContent,
    ).toMatch(/90/);
    expect(screen.getByTestId('kalshi-operator-pages-scanned').textContent).toMatch(/3/);
    expect(screen.getByTestId('kalshi-operator-seek-allowed').textContent).toMatch(/yes/);
    expect(screen.getByTestId('kalshi-operator-allowed-found').textContent).toMatch(/yes/);
  });

  it('renders accepted and quarantined category breakdowns', () => {
    render(<KalshiOperatorTruthPanel data={baseHealth()} />);
    const accepted = screen.getByTestId('kalshi-operator-accepted-categories');
    expect(accepted.textContent).toMatch(/commodities/);
    expect(accepted.textContent).toMatch(/finance/);
    const quarantined = screen.getByTestId('kalshi-operator-quarantined-categories');
    expect(quarantined.textContent).toMatch(/Weather/);
    expect(quarantined.textContent).toMatch(/Sports/);
  });

  it('renders event enrichment metrics', () => {
    render(<KalshiOperatorTruthPanel data={baseHealth()} />);
    expect(
      screen.getByTestId('kalshi-operator-event-enrichment').textContent,
    ).toMatch(/4\/5/);
    expect(
      screen.getByTestId('kalshi-operator-event-enrichment-failed').textContent,
    ).toMatch(/1/);
  });

  it('renders LIVE_VERIFIED + read-only + execution-locked safety block', () => {
    render(<KalshiOperatorTruthPanel data={baseHealth()} />);
    const safety = screen.getByTestId('kalshi-operator-safety-block');
    expect(safety.textContent?.toLowerCase()).toMatch(/advisory only/);
    expect(safety.textContent?.toLowerCase()).toMatch(/human review/);
    expect(safety.textContent?.toLowerCase()).toMatch(/execution.*locked/);
    expect(safety.textContent?.toLowerCase()).toMatch(/broker api called.*false/);
    expect(safety.textContent?.toLowerCase()).toMatch(/ai executions.*0/);
    expect(safety.textContent?.toLowerCase()).toMatch(/auth used.*yes/);
  });

  it('renders the honest empty-allowed-scope message and does NOT mark it as failure', () => {
    render(
      <KalshiOperatorTruthPanel
        data={baseHealth({
          records_allowed: 0,
          allowed_found: false,
          category_allowed_counts: {},
          source_freshness_status: 'LIVE_VERIFIED_SOURCE_EMPTY_FOR_ALLOWED_SCOPE',
        })}
      />,
    );
    const msg = screen.getByTestId('kalshi-operator-empty-scope-message');
    expect(msg.textContent).toMatch(/live source verified/i);
    expect(msg.textContent).toMatch(/no allowed-scope markets/i);
    // Source-status chip must NOT render as an error.
    const chip = screen.getByTestId('kalshi-operator-source-status-chip');
    expect(chip.className).not.toMatch(/sp-chip-rust/);
  });

  it('NEVER renders API key ID / private key path / auth headers / signatures', () => {
    // Construct a "leaky" payload that smuggles forbidden material into
    // string-valued fields.  The panel must redact at render time.
    const leaky = baseHealth({
      error_message:
        'auth failed -- KALSHI-ACCESS-KEY abc Authorization Bearer ZZZ',
      api_base_url: 'https://external-api.demo.kalshi.co/trade-api/v2',
    }) as unknown as Record<string, unknown>;
    leaky.api_key_id = '11111111-2222-3333-4444-555555555555';
    leaky.private_key_path = '/secrets/kalshi_demo_private.key';
    leaky['KALSHI-ACCESS-KEY'] = 'leaked-key';
    leaky['KALSHI-ACCESS-SIGNATURE'] = 'leaked-sig';

    const { container } = render(
      <KalshiOperatorTruthPanel data={leaky as KalshiSourceHealthResponse} />,
    );
    const dom = container.innerHTML;
    expect(dom).not.toContain('11111111-2222-3333-4444-555555555555');
    expect(dom).not.toContain('/secrets/kalshi_demo_private.key');
    expect(dom).not.toContain('leaked-key');
    expect(dom).not.toContain('leaked-sig');
    expect(dom).not.toMatch(/KALSHI-ACCESS-KEY/);
    expect(dom).not.toMatch(/KALSHI-ACCESS-SIGNATURE/);
    expect(dom).not.toMatch(/KALSHI-ACCESS-TIMESTAMP/);
    expect(dom).not.toMatch(/private_key_path/);
    expect(dom).not.toMatch(/BEGIN PRIVATE KEY/);
    expect(dom).not.toMatch(/BEGIN RSA PRIVATE KEY/);
    // Defence-in-depth: the auth-used flag is exposed as yes/no only.
    expect(
      screen.getByTestId('kalshi-operator-auth-used').textContent,
    ).toMatch(/auth used.*(yes|no)/i);
  });

  it('renders a graceful fallback when no source-health payload is available', () => {
    render(<KalshiOperatorTruthPanel data={null} />);
    const panel = screen.getByTestId('kalshi-operator-truth-panel');
    expect(panel.getAttribute('data-mode')).toBe('unknown');
    expect(panel.textContent?.toLowerCase()).toMatch(
      /kalshi source-health artifact not available/,
    );
  });
});
