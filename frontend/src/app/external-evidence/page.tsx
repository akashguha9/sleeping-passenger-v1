'use client';

import { useEffect, useState } from 'react';
import {
  ExternalEvidenceReliabilityCard,
  ExternalEvidenceReliabilityView,
} from '@/components/ExternalEvidenceReliabilityCard';
import {
  getExternalEvidenceReliability,
  ExternalEvidenceReliabilityResponse,
} from '@/lib/apiClient';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

// External Evidence Reliability — operator-facing, read-only surface.
//
// Mounts the ExternalEvidenceReliabilityCard against the read-only
// GET /external-evidence/reliability route.  External adapters are disabled
// by default, so the honest default rendered here is the DISABLED state.
//
// Safety contract: nothing on this page sizes real money, calls a broker, or
// authorises any action.  Calibrated weights are a PAPER-ONLY analysis prior;
// they can never override a DIABLO / CHAOS / safety veto.  Human review is
// always required and execution stays LOCKED.

export default function ExternalEvidencePage() {
  const [data, setData] = useState<ExternalEvidenceReliabilityResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [isOffline, setIsOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const resp = await getExternalEvidenceReliability();
      if (cancelled) return;
      if (resp === null) {
        setIsOffline(true);
      } else {
        setData(resp);
      }
      setLoaded(true);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="external-evidence-page">
      <Header />
      <SafetyBanner />
      {!loaded ? (
        <div className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          Loading external-evidence reliability…
        </div>
      ) : isOffline ? (
        <OfflineNotice />
      ) : (
        <ExternalEvidenceReliabilityCard
          bundle={data as ExternalEvidenceReliabilityView | null}
        />
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
            External Evidence Reliability
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--sp-mist)' }}>
            How much historical paper-only evidence sits behind each external
            source, and the calibrated weight learned from closed outcomes.
            Read-only context for the operator — never an action.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>
    </section>
  );
}

function SafetyBanner() {
  return (
    <div
      className="rounded px-3 py-2 text-[11px] font-mono uppercase tracking-widest text-center"
      style={{
        color: 'var(--sp-gold)',
        background: 'rgba(200, 154, 74, 0.06)',
        border: '1px solid rgba(200, 154, 74, 0.22)',
      }}
      data-testid="external-evidence-safety-banner"
    >
      Paper-only reliability · Human review required · Real-money sizing prohibited · No broker action
    </div>
  );
}

function OfflineNotice() {
  return (
    <section
      className="rounded-lg p-5"
      style={{ background: 'rgba(13,16,21,0.55)', border: '1px solid var(--sp-line)' }}
      data-testid="external-evidence-offline"
    >
      <div className="sp-eyebrow mb-1">Backend offline</div>
      <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
        The local API server is not reachable. Start the backend with{' '}
        <code className="font-mono">python scripts/api_server.py</code> and refresh.
        Until then, external-evidence reliability is unavailable — no decision impact.
      </p>
    </section>
  );
}
