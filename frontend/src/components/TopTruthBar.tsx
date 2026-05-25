'use client';

/**
 * TopTruthBar — global top-of-app banner that shows:
 *
 *   * a MOCK MODE / BACKEND OFFLINE chip when the frontend cannot
 *     reach the FastAPI backend, and
 *   * a SourceConfigurationSnapshot tile when the backend IS reachable.
 *
 * The component fetches /health and /live-sources/status with a short
 * timeout.  It never mutates state, never triggers a refresh, and never
 * authorises execution.  Mock mode is detected from the apiClient's
 * isMock flag, which flips when the fetch fails.
 */
import { useEffect, useState } from 'react';
import { checkHealth, getLiveSourcesStatus, getWatchdogSummary } from '@/lib/apiClient';
import type {
  HealthResponse,
} from '@/lib/apiClient';
import type {
  LiveSourcesStatusResponse,
  WatchdogSummaryResponse,
} from '@/types';
import { SourceConfigurationSnapshot } from '@/components/SourceConfigurationSnapshot';

export interface TopTruthBarState {
  isMock: boolean;
  health: HealthResponse | null;
  status: LiveSourcesStatusResponse | null;
  watchdog: WatchdogSummaryResponse | null;
  loaded: boolean;
}

export function TopTruthBar() {
  const [state, setState] = useState<TopTruthBarState>({
    isMock: false,
    health: null,
    status: null,
    watchdog: null,
    loaded: false,
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      checkHealth(),
      getLiveSourcesStatus(),
      getWatchdogSummary(),
    ])
      .then(([health, status, watchdog]) => {
        if (cancelled) return;
        // ``checkHealth`` returns null on backend-offline; ``getLiveSourcesStatus``
        // returns null on backend-offline.  Either condition flips isMock.
        const offline = health === null || status === null;
        setState({
          isMock: offline,
          health: health ?? null,
          status: status ?? null,
          watchdog: watchdog ?? null,
          loaded: true,
        });
      })
      .catch(() => {
        if (cancelled) return;
        setState({
          isMock: true,
          health: null,
          status: null,
          watchdog: null,
          loaded: true,
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!state.loaded) {
    return (
      <div
        data-testid="top-truth-bar"
        data-loaded="false"
        className="px-8 py-2 flex items-center justify-between gap-4"
        style={{
          background: 'rgba(13, 16, 21, 0.6)',
          borderBottom: '1px solid var(--sp-line)',
        }}
      >
        <span
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-mist)' }}
        >
          Loading source truth …
        </span>
      </div>
    );
  }

  return (
    <div
      data-testid="top-truth-bar"
      data-loaded="true"
      data-mock-mode={String(state.isMock)}
      className="px-8 py-2 flex items-center justify-between gap-4 flex-wrap"
      style={{
        background: 'rgba(13, 16, 21, 0.6)',
        borderBottom: '1px solid var(--sp-line)',
      }}
    >
      <div className="flex items-center gap-3 flex-wrap">
        {state.isMock ? (
          <span
            data-testid="top-truth-bar-mock-chip"
            className="sp-chip sp-chip-warn"
            style={{ color: 'var(--sp-gold)' }}
          >
            MOCK MODE · Backend offline · Showing mock data
          </span>
        ) : (
          <span
            data-testid="top-truth-bar-live-chip"
            className="sp-chip sp-chip-cyan"
            style={{ color: 'var(--sp-cyan)' }}
          >
            LIVE BACKEND
          </span>
        )}
        <SourceConfigurationSnapshot
          status={state.status}
          isMock={state.isMock}
          watchdogStatus={state.watchdog?.status ?? null}
        />
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <span
          data-testid="top-truth-bar-advisory-chip"
          className="text-[10px] font-mono uppercase tracking-widest"
          style={{ color: 'var(--sp-gold)' }}
        >
          Advisory only · No execution
        </span>
      </div>
    </div>
  );
}

export default TopTruthBar;
