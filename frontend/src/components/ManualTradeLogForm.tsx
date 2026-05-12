'use client';

import { useState } from 'react';
import { postManualTrade } from '@/lib/apiClient';
import { HumanOnlyBadge } from './HumanOnlyBadge';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

interface FormState {
  event_id: string;
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: string;
  price: string;
  leverage: string;
  thesis: string;
  notes: string;
}

interface Props {
  defaultEventId?: string;
  defaultTicker?: string;
  onLogged?: () => void;
}

// Mirrors backend bounds in scripts/signal_inbox_api.py
const LEVERAGE_MIN = 1.0;
const LEVERAGE_MAX = 25.0;

export function ManualTradeLogForm({ defaultEventId = '', defaultTicker = '', onLogged }: Props) {
  const [form, setForm] = useState<FormState>({
    event_id: defaultEventId,
    ticker: defaultTicker,
    side: 'BUY',
    quantity: '',
    price: '',
    leverage: '1.0',
    thesis: '',
    notes: '',
  });
  const [logged, setLogged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  function set(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError('');
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.ticker.trim()) { setError('Ticker is required.'); return; }
    if (!form.event_id.trim()) { setError('Signal Event ID is required.'); return; }
    const qty = parseFloat(form.quantity);
    const price = parseFloat(form.price);
    if (isNaN(qty) || qty <= 0) { setError('Quantity must be a positive number.'); return; }
    if (isNaN(price) || price <= 0) { setError('Price must be a positive number.'); return; }
    if (!form.thesis.trim()) { setError('Thesis is required.'); return; }
    const leverageRaw = form.leverage.trim();
    const leverage = leverageRaw === '' ? 1.0 : parseFloat(leverageRaw);
    if (isNaN(leverage)) { setError('Leverage must be a number.'); return; }
    if (leverage < LEVERAGE_MIN) { setError(`Leverage must be at least ${LEVERAGE_MIN.toFixed(1)}x.`); return; }
    if (leverage > LEVERAGE_MAX) { setError(`Leverage cannot exceed ${LEVERAGE_MAX.toFixed(1)}x.`); return; }

    setSubmitting(true);
    try {
      await postManualTrade({
        event_id: form.event_id.trim(),
        ticker: form.ticker.trim(),
        side: form.side,
        quantity: qty,
        price,
        leverage,
        thesis: form.thesis.trim(),
        notes: form.notes.trim(),
      });
      setLogged(true);
      onLogged?.();
      setTimeout(() => setLogged(false), 4000);
    } catch {
      setError('Failed to log trade — backend may be offline. Start the FastAPI server and try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (logged) {
    return (
      <div className="sp-card p-6 text-center space-y-3">
        <div
          className="mx-auto w-10 h-10 rounded-full flex items-center justify-center text-lg"
          style={{
            color: 'var(--sp-cyan)',
            border: '1px solid rgba(95, 189, 200, 0.4)',
            background: 'rgba(95, 189, 200, 0.05)',
          }}
        >
          ✓
        </div>
        <div className="text-sm font-semibold" style={{ color: 'var(--sp-bone)' }}>
          Manual Trade Logged
        </div>
        <div className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          Recorded for human review. No broker API was called. AI executions:{' '}
          <span className="font-mono font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>
        </div>
        <div className="flex justify-center gap-2 pt-1">
          <HumanOnlyBadge size="md" />
          <AdvisoryOnlyBadge size="md" />
        </div>
      </div>
    );
  }

  return (
    <div className="sp-card p-6">
      <div className="flex items-center gap-2 mb-1">
        <h3 className="sp-eyebrow">Log Manual Trade</h3>
      </div>
      <div className="flex items-center gap-2 mb-4">
        <HumanOnlyBadge />
        <AdvisoryOnlyBadge />
      </div>

      <div
        className="rounded-md px-3 py-2.5 mb-5 text-[11px] leading-relaxed"
        style={{
          color: 'var(--sp-mist)',
          background: 'rgba(200, 154, 74, 0.04)',
          border: '1px solid rgba(200, 154, 74, 0.18)',
        }}
      >
        Record-keeping only — this form does not submit orders to any broker. Broker API:{' '}
        <span className="font-mono" style={{ color: 'var(--sp-gold)' }}>DISABLED</span>. AI executions:{' '}
        <span className="font-mono font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>.
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Signal Event ID">
            <input
              type="text"
              className="sp-input"
              placeholder="FABRIC_BTC"
              value={form.event_id}
              onChange={(e) => set('event_id', e.target.value)}
            />
          </Field>
          <Field label="Ticker">
            <input
              type="text"
              className="sp-input uppercase"
              placeholder="BTC"
              value={form.ticker}
              onChange={(e) => set('ticker', e.target.value.toUpperCase())}
            />
          </Field>
        </div>

        <div className="grid grid-cols-4 gap-3">
          <Field label="Direction">
            <select
              className="sp-input"
              value={form.side}
              onChange={(e) => set('side', e.target.value as 'BUY' | 'SELL')}
            >
              <option value="BUY">Long (BUY)</option>
              <option value="SELL">Short (SELL)</option>
            </select>
          </Field>
          <Field label="Quantity">
            <input
              type="number"
              min="0"
              step="any"
              className="sp-input"
              placeholder="10"
              value={form.quantity}
              onChange={(e) => set('quantity', e.target.value)}
            />
          </Field>
          <Field label="Price">
            <input
              type="number"
              min="0"
              step="any"
              className="sp-input"
              placeholder="182.50"
              value={form.price}
              onChange={(e) => set('price', e.target.value)}
            />
          </Field>
          <Field label="Leverage" hint="record-only · 1.0–25.0x">
            <div className="relative">
              <input
                type="number"
                min={LEVERAGE_MIN}
                max={LEVERAGE_MAX}
                step="0.1"
                className="sp-input pr-7"
                placeholder="1.0"
                value={form.leverage}
                onChange={(e) => set('leverage', e.target.value)}
              />
              <span
                className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-mono"
                style={{ color: 'var(--sp-mist)' }}
              >
                x
              </span>
            </div>
          </Field>
        </div>

        <Field label="Thesis">
          <textarea
            rows={3}
            className="sp-input resize-none"
            placeholder="Why did you place this trade? What was your human reasoning?"
            value={form.thesis}
            onChange={(e) => set('thesis', e.target.value)}
          />
        </Field>

        <Field label="Notes (optional)">
          <input
            type="text"
            className="sp-input"
            placeholder="Any additional context…"
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
          />
        </Field>

        {error && (
          <div
            className="text-xs rounded px-3 py-2"
            style={{
              color: '#d57b6a',
              background: 'rgba(160, 74, 58, 0.06)',
              border: '1px solid rgba(160, 74, 58, 0.32)',
            }}
          >
            {error}
          </div>
        )}

        <button type="submit" disabled={submitting} className="sp-btn-primary">
          {submitting ? 'Logging…' : 'Log Manual Trade'}
        </button>

        <p className="text-[10px] font-mono uppercase tracking-widest text-center" style={{ color: 'var(--sp-mist)' }}>
          Record-keeping only · No broker call · AI executions = 0
        </p>
      </form>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="flex items-baseline justify-between mb-1">
        <span className="sp-eyebrow">{label}</span>
        {hint && (
          <span className="text-[9px] font-mono uppercase tracking-widest" style={{ color: 'var(--sp-mist)' }}>
            {hint}
          </span>
        )}
      </label>
      {children}
    </div>
  );
}
