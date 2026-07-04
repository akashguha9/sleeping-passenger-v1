/**
 * Vitest spec for the NBI page (Close-the-Loop sprint, 2026-07-04).
 *
 * Pins the forensic-audit fixes:
 *   * /nbi is reachable from the sidebar navigation (orphan-route fix);
 *   * the cockpit panel renders artifact age and flags stale artifacts —
 *     a dead scheduler must never render an ageless HEALTHY 10/10;
 *   * a stale cards artifact renders a red CARDS ARTIFACT STALE banner;
 *   * below 50 closed real cases the page says scores are UNCALIBRATED.
 */
// @ts-ignore
import { render, screen } from '@testing-library/react';
import { vi } from 'vitest';

// @ts-ignore
declare const describe: any;
// @ts-ignore
declare const it: any;
// @ts-ignore
declare const expect: any;
// @ts-ignore
declare const beforeEach: any;

vi.mock('@/lib/apiClient', () => ({
  getNbiCards: vi.fn(),
  getNbiCockpit: vi.fn(),
}));
vi.mock('next/navigation', () => ({
  usePathname: () => '/nbi',
}));

import { getNbiCards, getNbiCockpit } from '@/lib/apiClient';
import NbiOperatorCardsPage from '@/app/nbi/page';
import { Sidebar } from '@/components/layout/Sidebar';

const mockCards = getNbiCards as unknown as ReturnType<typeof vi.fn>;
const mockCockpit = getNbiCockpit as unknown as ReturnType<typeof vi.fn>;

function isoMinutesAgo(mins: number): string {
  return new Date(Date.now() - mins * 60000).toISOString();
}

function cardsPayload(over: Record<string, unknown> = {}) {
  return {
    generated_at: isoMinutesAgo(30),
    calibration: { status: 'CASE_ACCUMULATION', n_closed_real_cases: 2 },
    edge_claim: {
      edge_claim_allowed: false,
      current_case_count: 2,
      required_case_count: 30,
      missing_requirements: ['n_closed_real_cases>=30'],
    },
    section: { events: [] },
    ...over,
  };
}

function cockpitPayload(over: Record<string, unknown> = {}) {
  return {
    artifact_present: true,
    generated_at: isoMinutesAgo(30),
    artifact_age_minutes: 30,
    artifact_stale: false,
    health: { status: 'HEALTHY', LiveOpsHealth10: 10 },
    state: { scheduler: { task_installed: true } },
    next_actions: [],
    ...over,
  };
}

describe('sidebar navigation', () => {
  it('links to /nbi so the page is not an orphan route', () => {
    render(<Sidebar />);
    const link = screen.getByRole('link', { name: /Narrative Branches/i });
    expect(link.getAttribute('href')).toBe('/nbi');
  });
});

describe('NBI page freshness and honesty', () => {
  beforeEach(() => {
    mockCards.mockReset();
    mockCockpit.mockReset();
  });

  it('renders cockpit artifact age when fresh', async () => {
    mockCards.mockResolvedValue(cardsPayload());
    mockCockpit.mockResolvedValue(cockpitPayload());
    render(<NbiOperatorCardsPage />);
    const age = await screen.findByTestId('nbi-cockpit-age');
    expect(age.textContent).toContain('old');
    expect(age.textContent).not.toContain('STALE');
  });

  it('flags a stale cockpit artifact instead of trusting old HEALTHY', async () => {
    mockCards.mockResolvedValue(cardsPayload());
    mockCockpit.mockResolvedValue(
      cockpitPayload({
        artifact_age_minutes: 51 * 60,
        artifact_stale: true,
        generated_at: isoMinutesAgo(51 * 60),
      }),
    );
    render(<NbiOperatorCardsPage />);
    const age = await screen.findByTestId('nbi-cockpit-age');
    expect(age.textContent).toContain('STALE');
  });

  it('renders a red banner when the cards artifact is stale', async () => {
    mockCards.mockResolvedValue(
      cardsPayload({ generated_at: isoMinutesAgo(60 * 60) }),
    );
    mockCockpit.mockResolvedValue(cockpitPayload());
    render(<NbiOperatorCardsPage />);
    const banner = await screen.findByTestId('nbi-cards-stale-banner');
    expect(banner.textContent).toContain('CARDS ARTIFACT STALE');
  });

  it('says scores are uncalibrated below 50 closed real cases', async () => {
    mockCards.mockResolvedValue(cardsPayload());
    mockCockpit.mockResolvedValue(cockpitPayload());
    render(<NbiOperatorCardsPage />);
    const note = await screen.findByTestId('nbi-uncalibrated-note');
    expect(note.textContent).toContain('uncalibrated');
    expect(note.textContent).toContain('2');
  });

  it('shows the offline state when the API is unreachable', async () => {
    mockCards.mockResolvedValue(null);
    mockCockpit.mockResolvedValue(null);
    render(<NbiOperatorCardsPage />);
    expect(
      await screen.findByText(/API offline or token required/i),
    ).toBeTruthy();
  });
});
