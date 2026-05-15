'use client';

import { useEffect, useState } from 'react';
import {
  getStoredApiToken,
  setStoredApiToken,
  clearStoredApiToken,
  hasStoredApiToken,
} from '@/lib/apiClient';

/**
 * Sprint 8.1 — local-only operator-token panel.
 *
 * When the backend has `MVP_API_TOKEN` set, mutating POST routes require
 * a Bearer token.  This panel lets the operator paste that token once
 * per browser session.  The token is stored in `sessionStorage` (NOT
 * `localStorage`, NOT cookies) and is cleared when the tab closes.
 *
 * Hard rules:
 *   * Never committed.  Never sent to a third party.
 *   * Never displayed in full after save.
 *   * Token allows journaling / reconciliation / paper-ledger writes
 *     only.  It does NOT authorize trades, broker calls, or AI
 *     execution.  `execution_gate=LOCKED` stays locked.
 */
interface Props {
  /** Optional callback so the parent can refresh after a token change. */
  onChange?: (hasToken: boolean) => void;
}

export function LocalApiTokenPanel({ onChange }: Props) {
  const [value, setValue] = useState('');
  const [stored, setStored] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    // Compute initial state on the client only (SSR-safe).
    setStored(hasStoredApiToken());
  }, []);

  function handleSave() {
    const trimmed = value.trim();
    if (!trimmed) return;
    setStoredApiToken(trimmed);
    setValue('');
    setStored(true);
    setJustSaved(true);
    if (onChange) onChange(true);
    // The "just saved" badge auto-clears after a few seconds, but the
    // token state remains until the operator clears it explicitly.
    setTimeout(() => setJustSaved(false), 3000);
  }

  function handleClear() {
    clearStoredApiToken();
    setValue('');
    setStored(false);
    setJustSaved(false);
    if (onChange) onChange(false);
  }

  // We deliberately do NOT render the stored token value.  We only
  // indicate that one exists for this session.
  const maskedPreview = stored ? '••• stored for this browser session' : '';

  return (
    <div
      className="rounded border border-slate-800 bg-slate-950/60 p-4 space-y-3"
      data-testid="local-api-token-panel"
      data-token-set={String(stored)}
      data-advisory-only="true"
      data-execution-permission="false"
    >
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-mono uppercase tracking-wider text-slate-300">
          Local API token
        </h2>
        <span
          className={`text-[10px] font-mono uppercase ${
            stored ? 'text-emerald-300' : 'text-slate-500'
          }`}
          data-testid="token-status"
        >
          {stored ? 'set' : 'not set'}
        </span>
      </header>

      <p className="text-[11px] text-slate-400 leading-snug">
        Local-only convenience.  If your backend has{' '}
        <code className="text-slate-200">MVP_API_TOKEN</code> set, paste
        that token here once per browser session so journaling /
        reconciliation / paper-ledger writes succeed.  Stored in{' '}
        <code className="text-slate-200">sessionStorage</code>, cleared
        when the tab closes.  This token does NOT authorize trade
        execution.
      </p>

      {!stored ? (
        <div className="flex gap-2" data-testid="token-input-row">
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste MVP_API_TOKEN…"
            className="flex-1 bg-slate-900 border border-slate-700 rounded px-2 py-1 text-xs font-mono text-slate-100 placeholder:text-slate-600"
            data-testid="token-input"
            autoComplete="off"
            spellCheck={false}
          />
          <button
            type="button"
            onClick={handleSave}
            disabled={!value.trim()}
            className="text-xs font-mono uppercase tracking-wider bg-slate-800 border border-slate-700 hover:border-slate-500 disabled:opacity-40 px-3 py-1 rounded text-slate-100"
            data-testid="token-save-btn"
          >
            Save
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <span
            className="text-[11px] font-mono text-slate-300"
            data-testid="token-preview"
          >
            {maskedPreview}
          </span>
          <button
            type="button"
            onClick={handleClear}
            className="text-xs font-mono uppercase tracking-wider bg-slate-800 border border-slate-700 hover:border-rose-700 px-3 py-1 rounded text-slate-200"
            data-testid="token-clear-btn"
          >
            Clear
          </button>
        </div>
      )}

      {justSaved && (
        <p
          className="text-[10px] text-emerald-300 font-mono"
          data-testid="token-just-saved"
        >
          Token set for this browser session.
        </p>
      )}

      <p className="text-[10px] text-slate-500" data-testid="token-safety-copy">
        Token authorises local writes only; it never authorises trade
        execution and never grants AI execution.
      </p>
    </div>
  );
}
