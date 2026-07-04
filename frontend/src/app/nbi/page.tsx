'use client';

// Narrative Branch Intelligence operator cards — ADVISORY-ONLY surface.
// Renders the JSON artifact served by GET /nbi/cards.  No execution
// controls exist on this page by doctrine: branch probabilities, rumor
// verdicts, hedge suggestions and the edge-claim gate are information for
// a human operator, never instructions.

import { useEffect, useState } from 'react';
import {
  getNbiCards,
  getNbiCockpit,
  type NbiCardsResponse,
  type NbiCockpitResponse,
} from '@/lib/apiClient';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

type LoadState = 'loading' | 'ready' | 'offline';

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? (value.filter((v) => v && typeof v === 'object') as Array<
        Record<string, unknown>
      >)
    : [];
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === 'string')
    : [];
}

// BranchUncertainty_b = 1 - |2P_b - 1|
function branchUncertainty(p: number): number {
  return 1 - Math.abs(2 * p - 1);
}

// Close-the-Loop sprint (2026-07-04): artifact freshness must be visible.
// A dead daily loop previously rendered a stale HEALTHY 10/10 forever.
const STALE_AMBER_MINUTES = 26 * 60;
const STALE_RED_MINUTES = 50 * 60;

function ageMinutesFrom(iso: string): number | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.round((Date.now() - t) / 60000);
}

function formatAge(mins: number): string {
  if (mins < 90) return `${mins}m`;
  return `${(mins / 60).toFixed(1)}h`;
}

function FreshnessBadge({
  ageMinutes,
  testId,
}: {
  ageMinutes: number | null;
  testId: string;
}) {
  if (ageMinutes === null) {
    return (
      <span data-testid={testId} style={{ color: '#f87171', fontWeight: 600 }}>
        AGE UNKNOWN — treat as stale
      </span>
    );
  }
  const stale = ageMinutes > STALE_AMBER_MINUTES;
  const dead = ageMinutes > STALE_RED_MINUTES;
  const color = dead ? '#f87171' : stale ? '#fbbf24' : undefined;
  return (
    <span data-testid={testId} style={{ color, fontWeight: stale ? 600 : 400 }}>
      {formatAge(ageMinutes)} old
      {dead
        ? ' — STALE: daily loop looks dead, investigate the scheduler'
        : stale
          ? ' — STALE: expected a fresh run by now'
          : ''}
    </span>
  );
}

const cardStyle: React.CSSProperties = {
  border: '1px solid rgba(148, 163, 184, 0.35)',
  borderRadius: 8,
  padding: '0.9rem 1.1rem',
  marginBottom: '1rem',
};

const labelStyle: React.CSSProperties = {
  opacity: 0.7,
  fontSize: '0.78rem',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
};

function CockpitPanel({ cockpit }: { cockpit: NbiCockpitResponse | null }) {
  if (!cockpit || cockpit.artifact_present === false) {
    return (
      <section style={cardStyle} data-testid="nbi-cockpit">
        <div style={labelStyle}>Live-ops cockpit</div>
        <p style={{ margin: '0.3rem 0', opacity: 0.85 }}>
          No autopilot run recorded yet — run{' '}
          <code>python -m scripts.nbi_live_ops_cockpit autopilot</code>.
        </p>
      </section>
    );
  }
  const health = cockpit.health ?? {};
  const st = (cockpit.state ?? {}) as Record<string, any>;
  const scheduler = (st.scheduler ?? {}) as Record<string, unknown>;
  const feed = (st.feed ?? {}) as Record<string, unknown>;
  const market = (st.market ?? {}) as Record<string, unknown>;
  const calibration = (st.calibration ?? {}) as Record<string, unknown>;
  const activeEvents = Array.isArray((st.events ?? {}).active)
    ? ((st.events ?? {}).active as string[])
    : [];
  const nextActions = asStringArray(cockpit.next_actions);
  const cockpitAny = cockpit as Record<string, unknown>;
  const serverAge = asNumber(cockpitAny.artifact_age_minutes);
  const generatedAt = asString(cockpitAny.generated_at);
  const cockpitAge =
    serverAge ?? (generatedAt ? ageMinutesFrom(generatedAt) : null);
  return (
    <section style={cardStyle} data-testid="nbi-cockpit">
      <div style={labelStyle}>Live-ops cockpit</div>
      <p style={{ margin: '0.3rem 0' }}>
        Status: <strong>{asString(health.status) || '—'}</strong> · Health:{' '}
        {asNumber(health.LiveOpsHealth10) ?? '—'}/10 · Scheduler installed:{' '}
        <strong>{scheduler.task_installed === true ? 'yes' : 'no'}</strong>
      </p>
      <p style={{ margin: '0.2rem 0' }} data-testid="nbi-cockpit-freshness">
        Cockpit artifact:{' '}
        <FreshnessBadge ageMinutes={cockpitAge} testId="nbi-cockpit-age" />
        {generatedAt ? ` (generated ${generatedAt})` : ''}
      </p>
      <p style={{ margin: '0.2rem 0', opacity: 0.85 }}>
        Active events: {activeEvents.length}{' '}
        {activeEvents.length ? `(${activeEvents.join(', ')})` : ''} · Feed:{' '}
        {asString(feed.status) || '—'} · Market:{' '}
        {asString(market.adapter_health) || '—'} (
        {asNumber(market.live_rows) ?? 0} live rows) · Eligible cases:{' '}
        {asNumber(calibration.n_calibration_eligible) ?? 0}/30
      </p>
      {nextActions.length > 0 && (
        <>
          <div style={labelStyle}>Next operator actions</div>
          <ol style={{ margin: '0.3rem 0 0' }}>
            {nextActions.map((a) => (
              <li key={a} style={{ wordBreak: 'break-word' }}>
                {a}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

export default function NbiOperatorCardsPage() {
  const [state, setState] = useState<LoadState>('loading');
  const [payload, setPayload] = useState<NbiCardsResponse | null>(null);
  const [cockpit, setCockpit] = useState<NbiCockpitResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [data, cockpitData] = await Promise.all([
        getNbiCards(),
        getNbiCockpit(),
      ]);
      if (cancelled) return;
      setPayload(data);
      setCockpit(cockpitData);
      setState(data ? 'ready' : 'offline');
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const edge = payload?.edge_claim ?? {};
  const edgeAllowed = edge.edge_claim_allowed === true;
  const events = asArray(payload?.section?.events);
  const calibration = (payload?.calibration ?? {}) as Record<string, unknown>;
  const lastRun = (payload?.last_scheduler_run ?? null) as Record<
    string,
    unknown
  > | null;

  return (
    <main style={{ maxWidth: 960, margin: '0 auto', padding: '1.5rem 1rem' }}>
      <header style={{ marginBottom: '1rem' }}>
        <h1 style={{ marginBottom: '0.35rem' }}>
          Narrative Branch Intelligence
        </h1>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          <AdvisoryOnlyBadge />
          <HumanOnlyBadge />
        </div>
        <p style={{ marginTop: '0.6rem', opacity: 0.85 }}>
          Branch probabilities, rumor verdicts and hedge suggestions for a
          human operator. Nothing on this page is an instruction.
        </p>
      </header>

      <CockpitPanel cockpit={cockpit} />

      <section style={cardStyle} data-testid="nbi-edge-claim">
        <div style={labelStyle}>Edge claim gate</div>
        <p style={{ margin: '0.3rem 0' }}>
          Edge claim permitted:{' '}
          <strong>{edgeAllowed ? 'true' : 'false'}</strong>{' '}
          ({asNumber(edge.current_case_count) ?? 0}/
          {asNumber(edge.required_case_count) ?? 30} eligible cases)
        </p>
        {!edgeAllowed && (
          <p style={{ margin: 0, opacity: 0.8 }}>
            No performance edge is claimed. Missing:{' '}
            {asStringArray(edge.missing_requirements).join('; ') ||
              'nothing measured yet'}
          </p>
        )}
        <p style={{ margin: '0.3rem 0 0', opacity: 0.8 }}>
          Calibration: {asString(calibration.status) || 'NOT_RUN'} · closed
          real cases: {asNumber(calibration.n_closed_real_cases) ?? 0} · last
          scheduler run:{' '}
          {lastRun ? `${asString(lastRun.status)} @ ${asString(
            lastRun.timestamp,
          )}` : 'none recorded'}
        </p>
        {(asNumber(calibration.n_closed_real_cases) ?? 0) < 50 && (
          <p
            style={{ margin: '0.3rem 0 0', color: '#fbbf24' }}
            data-testid="nbi-uncalibrated-note"
          >
            Scores on this page are uncalibrated model output (
            {asNumber(calibration.n_closed_real_cases) ?? 0} closed real cases
            &lt; 50). Do not read them as probabilities of anything.
          </p>
        )}
      </section>

      {payload?.generated_at &&
        (() => {
          const cardsAge = ageMinutesFrom(asString(payload.generated_at));
          if (cardsAge !== null && cardsAge <= STALE_AMBER_MINUTES) return null;
          return (
            <section
              style={{
                ...cardStyle,
                borderColor: '#f87171',
              }}
              data-testid="nbi-cards-stale-banner"
            >
              <strong style={{ color: '#f87171' }}>
                CARDS ARTIFACT STALE
              </strong>{' '}
              — <FreshnessBadge ageMinutes={cardsAge} testId="nbi-cards-age" />.
              The daily loop may not be running; check{' '}
              <code>python -m scripts.nbi_scheduler status</code>.
            </section>
          );
        })()}

      {state === 'loading' && <p>Loading NBI cards…</p>}
      {state === 'offline' && (
        <p>
          API offline or token required — run{' '}
          <code>python -m scripts.nbi_evidence_factory export-cards</code> and
          start the local API server.
        </p>
      )}
      {state === 'ready' && events.length === 0 && (
        <section style={cardStyle}>
          <strong>NO_ACTIVE_NBI_EVENTS</strong>
          <p style={{ margin: '0.4rem 0 0', opacity: 0.8 }}>
            Activate a watch event and run the daily loop to populate this
            board.
          </p>
        </section>
      )}

      {events.map((event) => {
        const branches = (event.branches ?? {}) as Record<string, unknown>;
        const hedge = (event.hedge ?? {}) as Record<string, unknown>;
        const topTickers = asArray(event.top_tickers);
        const isFixture = event.is_fixture === true;
        return (
          <section key={asString(event.event_id)} style={cardStyle}>
            <h2 style={{ margin: 0 }}>
              {asString(event.event_name) || asString(event.event_id)}{' '}
              {isFixture && (
                <span style={{ fontSize: '0.8rem', opacity: 0.75 }}>
                  [FIXTURE]
                </span>
              )}
            </h2>
            <p style={{ margin: '0.3rem 0', opacity: 0.85 }}>
              State: <strong>{asString(event.state)}</strong> · Action:{' '}
              <strong>{asString(event.action)}</strong> · Rumor risk:{' '}
              {asNumber(event.rumor_risk) ?? '—'} (
              {asString(event.rumor_verdict) || 'n/a'}) · Disagreement:{' '}
              {asNumber(event.source_disagreement) ?? '—'}
            </p>
            <div style={labelStyle}>Branch probabilities (uncertainty)</div>
            <ul style={{ margin: '0.3rem 0 0.6rem' }}>
              {Object.entries(branches).map(([name, p]) => {
                const value = asNumber(p);
                return (
                  <li key={name}>
                    {name}: {value ?? '—'}
                    {value !== null &&
                      ` (u=${branchUncertainty(value).toFixed(2)})`}
                  </li>
                );
              })}
            </ul>
            <p style={{ margin: '0.2rem 0' }}>
              Surviving layer: {asString(event.surviving_layer) || '—'}
            </p>
            <p style={{ margin: '0.2rem 0' }}>
              Top:{' '}
              {topTickers
                .map(
                  (t) =>
                    `${asString(t.ticker)} (${asNumber(t.score) ?? '—'}, ${
                      asString(t.status)
                    })`,
                )
                .join(' · ') || '—'}
            </p>
            <p style={{ margin: '0.2rem 0' }}>
              Downgraded: {asStringArray(event.downgraded_tickers).join(', ') ||
                '—'}
            </p>
            <p style={{ margin: '0.2rem 0' }}>
              Hedge: {asString(hedge.hedge_class) || '—'} (ratio{' '}
              {asNumber(hedge.hedge_ratio) ?? '—'})
            </p>
            {asStringArray(event.verify_next).length > 0 && (
              <>
                <div style={labelStyle}>Verify next</div>
                <ul style={{ margin: '0.3rem 0' }}>
                  {asStringArray(event.verify_next).map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </>
            )}
            {asStringArray(event.evidence_refs).length > 0 && (
              <>
                <div style={labelStyle}>Evidence refs</div>
                <ul style={{ margin: '0.3rem 0' }}>
                  {asStringArray(event.evidence_refs).map((ref) => (
                    <li key={ref} style={{ wordBreak: 'break-all' }}>
                      {ref}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        );
      })}

      <footer style={{ opacity: 0.7, fontSize: '0.85rem' }}>
        Generated: {asString(payload?.generated_at) || '—'} · execution gate
        LOCKED · a human makes every decision.
      </footer>
    </main>
  );
}
