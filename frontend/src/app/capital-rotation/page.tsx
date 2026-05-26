'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

// Capital Rotation Engine — operator-facing surface.
//
// Renders, in priority order: Portfolio Regime banner, Capacity Score,
// Exit Review Board (always shown ABOVE buy admission so the operator
// recycles possession before progressing), Theme Slot Board, and Buy
// Admission Board.  Every section is read-only and stamped
// RECORD-KEEPING ONLY · NO BROKER CALL · AI EXECUTIONS = 0.
//
// Safety contract: nothing on this page issues a trade, places an
// order, calls a broker API, or claims to execute on behalf of the
// user.  The backend already enforces this; the UI mirrors the same
// language so the operator can never mistake an advisory cue for an
// execution prompt.

type ExitRow = {
  ticker: string;
  economic_exposure_key: string;
  theme_buckets: string[];
  exit_status: string;
  thesis_status: string;
  live_price: number | null;
  stop_loss: number | null;
  tp_price: number | null;
  pnl_pct: number | null;
  distance_to_stop_pct: number | null;
  distance_to_tp_pct: number | null;
  human_action_required: boolean;
  reason_codes: string[];
};

type ThemeRow = {
  theme: string;
  used_weight: number;
  warning_cap: number;
  hard_cap: number;
  utilization: number;
  status: string;
  holdings: string[];
  weakest_holding_candidates: string[];
  allowed_action: string;
};

type AdmissionRow = {
  ticker: string;
  economic_exposure_key: string;
  theme_buckets: string[];
  candidate_admission_score: number;
  buy_admission_class: string;
  add_or_replace_recommendation: string;
  replace_target_ticker: string | null;
  max_allowed_size: number;
  max_allowed_leverage: number;
  reason_codes: string[];
};

type CapacityComponents = {
  S_live: number;
  S_recon: number;
  S_stop: number;
  S_cash: number;
  S_theme: number;
  S_lev: number;
  P_dup: number;
  P_unreviewed: number;
  P_dirty: number;
  P_tp: number;
  P_stop: number;
};

type RiskBudget = {
  available_new_risk_budget: number;
  cash_budget_unknown: boolean;
  buffers: Record<string, number>;
  allowed_new_entries: number;
  max_size_per_entry: number;
  max_total_new_capital: number;
};

type CapitalRotation = {
  portfolio_regime: 'BUY_ALLOWED' | 'BUY_LIMITED' | 'BUY_BLOCKED';
  portfolio_capacity_score: number;
  allowed_new_entries: number;
  max_size_per_entry: number;
  max_total_new_capital: number;
  leverage_allowed: number;
  capacity_components: CapacityComponents;
  exit_review_board: {
    rows: ExitRow[];
    counts: Record<string, number>;
    duplicate_exposures: { economic_exposure_key: string; ticker_variants: string[] }[];
    open_position_count: number;
  };
  theme_slot_summary: {
    themes: ThemeRow[];
    over_cap_themes: string[];
    near_cap_themes: string[];
    any_hard_cap_exceeded: boolean;
  };
  buy_admission_board: {
    rows: AdmissionRow[];
    counts: Record<string, number>;
    candidate_count: number;
  };
  risk_budget: RiskBudget;
  generated_at_utc: string;
  source_health: string;
};

const REGIME_TEXT: Record<string, { headline: string; body: string }> = {
  BUY_ALLOWED: {
    headline: 'BUY_ALLOWED · capacity available',
    body: 'Portfolio capacity available. New manual entries allowed within risk budget. Record-keeping only — no broker call.',
  },
  BUY_LIMITED: {
    headline: 'BUY_LIMITED · small entries only',
    body: 'New entries limited. Small manual entries only (max €50 each, 3 entries max). Same-theme buys require ADD / REPLACE / DIVERSIFY label.',
  },
  BUY_BLOCKED: {
    headline: 'BUY_BLOCKED · resolve risk first',
    body: 'New entries blocked or require explicit override. Resolve exit / data / risk issues before adding capital.',
  },
};

export default function CapitalRotationPage() {
  const [data, setData] = useState<CapitalRotation | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        // Backend exposes /capital-rotation/snapshot as the unified
        // snapshot — the four sub-boards (exit, theme, admission, risk)
        // are all returned inside this single payload.  Routes live
        // under /capital-rotation/* rather than /portfolio/* because the
        // repo-wide safety guard bans the bare ``portfolio`` path
        // segment (only compound forms like ``portfolio-truth`` pass).
        const resp = await fetch(`${API_BASE}/capital-rotation/snapshot`);
        if (!resp.ok) throw new Error(`status ${resp.status}`);
        const body = await resp.json();
        if (!cancelled) setData(body as CapitalRotation);
      } catch (err) {
        if (!cancelled) {
          setIsOffline(true);
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-6" data-testid="capital-rotation-page">
      <Header />
      <RecordKeepingStamp />
      {isOffline ? (
        <OfflineNotice error={error} />
      ) : data ? (
        <>
          <RegimeBanner regime={data.portfolio_regime} />
          <CapacityCard
            score={data.portfolio_capacity_score}
            components={data.capacity_components}
            generatedAt={data.generated_at_utc}
            sourceHealth={data.source_health}
          />
          <ExitReviewBoard board={data.exit_review_board} />
          <ThemeSlotBoard board={data.theme_slot_summary} />
          <BuyAdmissionBoard
            board={data.buy_admission_board}
            regime={data.portfolio_regime}
            maxSizePerEntry={data.max_size_per_entry}
            maxTotal={data.max_total_new_capital}
          />
          <RiskBudgetCard budget={data.risk_budget} />
          <SafetyFooter />
        </>
      ) : (
        <div className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          Loading capital rotation snapshot…
        </div>
      )}
    </div>
  );
}

function Header() {
  return (
    <section
      className="rounded-lg p-6"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
    >
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <div className="sp-eyebrow mb-2">Operator View</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            Capital Rotation Engine
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--sp-mist)' }}>
            Juego de Posición portfolio operator. Recycle possession before
            progressing. Buy only when the team shape supports it.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
          <Badge label="No Execution" />
        </div>
      </div>
    </section>
  );
}

function RecordKeepingStamp() {
  return (
    <div
      className="rounded px-3 py-2 text-[11px] font-mono uppercase tracking-widest text-center"
      style={{
        color: 'var(--sp-gold)',
        background: 'rgba(200, 154, 74, 0.06)',
        border: '1px solid rgba(200, 154, 74, 0.22)',
      }}
      data-testid="record-keeping-stamp"
    >
      RECORD-KEEPING ONLY · NO BROKER CALL · AI EXECUTIONS = 0
    </div>
  );
}

function RegimeBanner({ regime }: { regime: CapitalRotation['portfolio_regime'] }) {
  const meta = REGIME_TEXT[regime] ?? REGIME_TEXT.BUY_BLOCKED;
  const palette =
    regime === 'BUY_ALLOWED'
      ? { bg: 'rgba(50, 196, 130, 0.10)', border: 'rgba(50, 196, 130, 0.55)', fg: '#7be3a8' }
      : regime === 'BUY_LIMITED'
        ? { bg: 'rgba(220, 168, 50, 0.10)', border: 'rgba(220, 168, 50, 0.55)', fg: '#f0c75a' }
        : { bg: 'rgba(220, 80, 80, 0.10)', border: 'rgba(220, 80, 80, 0.55)', fg: '#ff8a8a' };
  return (
    <section
      className="rounded-lg p-5"
      style={{ background: palette.bg, border: `1px solid ${palette.border}` }}
      data-testid={`regime-banner-${regime}`}
    >
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: palette.fg }}>
          {meta.headline}
        </h2>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: palette.fg }}>
          {regime}
        </span>
      </div>
      <p className="text-sm mt-2" style={{ color: 'var(--sp-bone)' }}>
        {meta.body}
      </p>
    </section>
  );
}

function CapacityCard({
  score,
  components,
  generatedAt,
  sourceHealth,
}: {
  score: number;
  components: CapacityComponents;
  generatedAt: string;
  sourceHealth: string;
}) {
  return (
    <section
      className="rounded-lg p-5 space-y-3"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="capacity-card"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--sp-bone)' }}>
          Portfolio Capacity Score
        </h2>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-mono" style={{ color: 'var(--sp-gold)' }}>
            {score.toFixed(1)}
          </span>
          <span className="text-sm" style={{ color: 'var(--sp-mist)' }}>/ 10</span>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
        <Stat label="Live source" value={components.S_live.toFixed(2)} />
        <Stat label="Reconciliation" value={components.S_recon.toFixed(2)} />
        <Stat label="Stop distance" value={components.S_stop.toFixed(2)} />
        <Stat label="Cash" value={components.S_cash.toFixed(2)} />
        <Stat label="Theme room" value={components.S_theme.toFixed(2)} />
        <Stat label="Leverage safety" value={components.S_lev.toFixed(2)} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs pt-2 border-t" style={{ borderColor: 'var(--sp-line)' }}>
        <Stat label="− dup" value={components.P_dup.toFixed(2)} />
        <Stat label="− unreviewed" value={components.P_unreviewed.toFixed(2)} />
        <Stat label="− dirty" value={components.P_dirty.toFixed(2)} />
        <Stat label="− tp due" value={components.P_tp.toFixed(2)} />
        <Stat label="− stop" value={components.P_stop.toFixed(2)} />
      </div>
      <div className="text-[10px] font-mono uppercase tracking-widest pt-2" style={{ color: 'var(--sp-mist)' }}>
        source: {sourceHealth} · generated {generatedAt}
      </div>
    </section>
  );
}

function ExitReviewBoard({
  board,
}: {
  board: CapitalRotation['exit_review_board'];
}) {
  return (
    <section
      className="rounded-lg p-5 space-y-3"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="exit-review-board"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--sp-bone)' }}>
          Exit Review Board · {board.open_position_count} open
        </h2>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-gold)' }}>
          recycle possession first
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left text-[10px] font-mono uppercase tracking-widest"
              style={{ color: 'var(--sp-mist)' }}
            >
              <th className="py-2 pr-3">Ticker</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Thesis</th>
              <th className="py-2 pr-3">Live</th>
              <th className="py-2 pr-3">Stop</th>
              <th className="py-2 pr-3">TP</th>
              <th className="py-2 pr-3">P/L %</th>
              <th className="py-2 pr-3">Reasons</th>
            </tr>
          </thead>
          <tbody>
            {board.rows.map((r) => (
              <tr key={r.ticker} style={{ borderTop: '1px solid var(--sp-line)' }}>
                <td className="py-2 pr-3 font-mono" style={{ color: 'var(--sp-bone)' }}>{r.ticker}</td>
                <td className="py-2 pr-3"><Pill label={r.exit_status} /></td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>{r.thesis_status}</td>
                <td className="py-2 pr-3 font-mono">{r.live_price ?? '—'}</td>
                <td className="py-2 pr-3 font-mono">{r.stop_loss ?? '—'}</td>
                <td className="py-2 pr-3 font-mono">{r.tp_price ?? '—'}</td>
                <td className="py-2 pr-3 font-mono">
                  {r.pnl_pct === null ? '—' : `${(r.pnl_pct * 100).toFixed(1)}%`}
                </td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                  {r.reason_codes.join(' · ')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {board.duplicate_exposures.length > 0 && (
        <div className="text-xs pt-2" style={{ color: 'var(--sp-gold)' }}>
          Duplicate economic exposure detected:{' '}
          {board.duplicate_exposures
            .map((d) => `${d.economic_exposure_key} (${d.ticker_variants.join(', ')})`)
            .join('; ')}
        </div>
      )}
    </section>
  );
}

function ThemeSlotBoard({
  board,
}: {
  board: CapitalRotation['theme_slot_summary'];
}) {
  return (
    <section
      className="rounded-lg p-5 space-y-3"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="theme-slot-board"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--sp-bone)' }}>
          Theme Slot Board · pitch zones
        </h2>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-gold)' }}>
          Juego de Posición
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left text-[10px] font-mono uppercase tracking-widest"
              style={{ color: 'var(--sp-mist)' }}
            >
              <th className="py-2 pr-3">Theme</th>
              <th className="py-2 pr-3">Used / Cap</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Holdings</th>
              <th className="py-2 pr-3">Weakest / redundant</th>
              <th className="py-2 pr-3">Allowed action</th>
            </tr>
          </thead>
          <tbody>
            {board.themes.map((row) => (
              <tr key={row.theme} style={{ borderTop: '1px solid var(--sp-line)' }}>
                <td className="py-2 pr-3 font-mono text-xs" style={{ color: 'var(--sp-gold)' }}>
                  {row.theme}
                </td>
                <td className="py-2 pr-3 font-mono">
                  {row.used_weight.toFixed(1)} / {row.hard_cap}
                </td>
                <td className="py-2 pr-3"><Pill label={row.status} /></td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                  {row.holdings.join(' · ') || '—'}
                </td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                  {row.weakest_holding_candidates.join(' · ') || '—'}
                </td>
                <td className="py-2 pr-3 text-xs">
                  <Pill label={row.allowed_action} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BuyAdmissionBoard({
  board,
  regime,
  maxSizePerEntry,
  maxTotal,
}: {
  board: CapitalRotation['buy_admission_board'];
  regime: CapitalRotation['portfolio_regime'];
  maxSizePerEntry: number;
  maxTotal: number;
}) {
  return (
    <section
      className="rounded-lg p-5 space-y-3"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="buy-admission-board"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--sp-bone)' }}>
          Buy Admission Board · {board.candidate_count} candidate{board.candidate_count === 1 ? '' : 's'}
        </h2>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-gold)' }}>
          {regime} · max €{maxSizePerEntry.toFixed(0)}/entry · €{maxTotal.toFixed(0)} total
        </span>
      </div>
      {regime === 'BUY_LIMITED' && (
        <div className="text-xs" style={{ color: 'var(--sp-gold)' }}>
          BUY_LIMITED: max 3 entries · max €50 each · same-theme additions require ADD / REPLACE / DIVERSIFY label.
        </div>
      )}
      {board.rows.length === 0 ? (
        <div className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          No candidates supplied. Feed candidates through{' '}
          <code className="font-mono">build_capital_rotation_summary(candidates=…)</code>{' '}
          to populate this board.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr
                className="text-left text-[10px] font-mono uppercase tracking-widest"
                style={{ color: 'var(--sp-mist)' }}
              >
                <th className="py-2 pr-3">Ticker</th>
                <th className="py-2 pr-3">Class</th>
                <th className="py-2 pr-3">ADD / REPLACE</th>
                <th className="py-2 pr-3">Replace target</th>
                <th className="py-2 pr-3">Score</th>
                <th className="py-2 pr-3">Max size €</th>
                <th className="py-2 pr-3">Max leverage</th>
                <th className="py-2 pr-3">Reasons</th>
              </tr>
            </thead>
            <tbody>
              {board.rows.map((r) => (
                <tr key={r.ticker} style={{ borderTop: '1px solid var(--sp-line)' }}>
                  <td className="py-2 pr-3 font-mono" style={{ color: 'var(--sp-bone)' }}>
                    {r.ticker}
                  </td>
                  <td className="py-2 pr-3"><Pill label={r.buy_admission_class} /></td>
                  <td className="py-2 pr-3 font-mono text-xs">
                    {r.add_or_replace_recommendation}
                  </td>
                  <td className="py-2 pr-3 font-mono text-xs" style={{ color: 'var(--sp-mist)' }}>
                    {r.replace_target_ticker ?? '—'}
                  </td>
                  <td className="py-2 pr-3 font-mono">{r.candidate_admission_score.toFixed(2)}</td>
                  <td className="py-2 pr-3 font-mono">{r.max_allowed_size.toFixed(0)}</td>
                  <td className="py-2 pr-3 font-mono">{r.max_allowed_leverage.toFixed(1)}x</td>
                  <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                    {r.reason_codes.join(' · ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RiskBudgetCard({ budget }: { budget: RiskBudget }) {
  return (
    <section
      className="rounded-lg p-5 space-y-3"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="risk-budget-card"
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-lg font-semibold tracking-tight" style={{ color: 'var(--sp-bone)' }}>
          Risk Budget · rest defense
        </h2>
        <span className="text-[10px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
          {budget.cash_budget_unknown ? 'cash unknown · regime cap only' : 'cash + regime cap'}
        </span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <Stat label="Available" value={`€${budget.available_new_risk_budget.toFixed(0)}`} />
        <Stat label="Allowed entries" value={String(budget.allowed_new_entries)} />
        <Stat label="Max / entry" value={`€${budget.max_size_per_entry.toFixed(0)}`} />
        <Stat label="Max total" value={`€${budget.max_total_new_capital.toFixed(0)}`} />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs pt-2 border-t" style={{ borderColor: 'var(--sp-line)', color: 'var(--sp-mist)' }}>
        {Object.entries(budget.buffers).map(([k, v]) => (
          <div key={k}>
            <span className="sp-eyebrow">{k.replace(/_/g, ' ')}</span>
            <div className="font-mono">€{Number(v).toFixed(0)}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function SafetyFooter() {
  return (
    <section
      className="rounded-lg p-5"
      style={{ background: 'rgba(200,154,74,0.04)', border: '1px solid rgba(200,154,74,0.22)' }}
      data-testid="safety-footer"
    >
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <Badge label="Advisory Only" />
        <Badge label="Record-Keeping Only" />
        <Badge label="No Broker Call" />
        <Badge label="AI Executions = 0" />
      </div>
      <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
        Every classification on this page is advisory. The Capital Rotation
        Engine grades the portfolio shape and suggests whether the next move
        should be a recycle, a rotation, or progression — it never places,
        modifies, or cancels an order. Manual decisions are required.
      </p>
    </section>
  );
}

function OfflineNotice({ error }: { error: string | null }) {
  return (
    <section
      className="rounded-lg p-5"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
    >
      <div className="sp-eyebrow mb-1">Backend offline</div>
      <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
        The local API server is not reachable
        {error ? <code className="font-mono ml-1">({error})</code> : null}. Start
        the backend with <code className="font-mono">python scripts/api_server.py</code>{' '}
        and refresh.
      </p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="sp-eyebrow">{label}</div>
      <div className="font-medium mt-0.5" style={{ color: 'var(--sp-bone)' }}>
        {value}
      </div>
    </div>
  );
}

function Badge({ label }: { label: string }) {
  return (
    <span
      className="px-2.5 py-1 inline-flex items-center rounded-full text-[10px] font-mono font-medium uppercase tracking-widest"
      style={{
        color: 'var(--sp-gold)',
        border: '1px solid rgba(200, 154, 74, 0.32)',
        background: 'rgba(200, 154, 74, 0.06)',
      }}
    >
      {label}
    </span>
  );
}

function Pill({ label }: { label: string }) {
  return (
    <span
      className="px-2 py-0.5 inline-flex rounded text-[11px] font-medium"
      style={{
        color: 'var(--sp-bone)',
        background: 'rgba(200, 154, 74, 0.08)',
        border: '1px solid rgba(200, 154, 74, 0.22)',
      }}
    >
      {label}
    </span>
  );
}
