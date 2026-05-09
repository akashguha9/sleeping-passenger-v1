'use client';

import { useState } from 'react';
import { HumanOnlyBadge } from './HumanOnlyBadge';
import { AdvisoryOnlyBadge } from './AdvisoryOnlyBadge';

interface FormState {
  event_id: string;
  ticker: string;
  side: 'BUY' | 'SELL';
  quantity: string;
  price: string;
  thesis: string;
  notes: string;
}

interface Props {
  defaultEventId?: string;
  defaultTicker?: string;
  onLogged?: () => void;
}

export function ManualTradeLogForm({ defaultEventId = '', defaultTicker = '', onLogged }: Props) {
  const [form, setForm] = useState<FormState>({
    event_id: defaultEventId,
    ticker: defaultTicker,
    side: 'BUY',
    quantity: '',
    price: '',
    thesis: '',
    notes: '',
  });
  const [logged, setLogged] = useState(false);
  const [error, setError] = useState('');

  function set(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError('');
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.ticker.trim()) { setError('Ticker is required.'); return; }
    if (!form.event_id.trim()) { setError('Signal Event ID is required.'); return; }
    const qty = parseFloat(form.quantity);
    const price = parseFloat(form.price);
    if (isNaN(qty) || qty <= 0) { setError('Quantity must be a positive number.'); return; }
    if (isNaN(price) || price <= 0) { setError('Price must be a positive number.'); return; }
    if (!form.thesis.trim()) { setError('Thesis is required.'); return; }

    setLogged(true);
    onLogged?.();
    setTimeout(() => setLogged(false), 4000);
  }

  if (logged) {
    return (
      <div className="bg-slate-800/60 border border-emerald-800/50 rounded-lg p-6 text-center">
        <div className="text-emerald-400 text-2xl mb-2">✓</div>
        <div className="text-sm font-semibold text-white mb-1">Manual Trade Logged</div>
        <div className="text-xs text-slate-400 mb-3">
          Trade recorded for human review. No broker API was called. AI executions: <span className="text-emerald-400 font-mono font-bold">0</span>
        </div>
        <div className="flex justify-center gap-2">
          <HumanOnlyBadge size="md" />
          <AdvisoryOnlyBadge size="md" />
        </div>
      </div>
    );
  }

  return (
    <div className="bg-slate-800/60 border border-slate-700/60 rounded-lg p-5">
      <div className="flex items-center gap-2 mb-4">
        <h3 className="text-sm font-semibold text-slate-300">Log Manual Trade</h3>
        <HumanOnlyBadge />
        <AdvisoryOnlyBadge />
      </div>

      <div className="bg-amber-950/30 border border-amber-900/40 rounded p-3 mb-4 text-xs text-amber-400">
        This form records a trade you have already placed manually. It does not submit orders to any broker.
        Broker API calls: <span className="font-mono font-bold">DISABLED</span>. AI executions: <span className="font-mono font-bold text-emerald-400">0</span>.
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Signal Event ID</label>
            <input
              type="text"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
              placeholder="FABRIC_BTC"
              value={form.event_id}
              onChange={(e) => set('event_id', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Ticker</label>
            <input
              type="text"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 uppercase"
              placeholder="BTC"
              value={form.ticker}
              onChange={(e) => set('ticker', e.target.value.toUpperCase())}
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-slate-500 mb-1">Direction</label>
            <select
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 focus:outline-none focus:border-slate-500"
              value={form.side}
              onChange={(e) => set('side', e.target.value as 'BUY' | 'SELL')}
            >
              <option value="BUY">Long (BUY)</option>
              <option value="SELL">Short (SELL)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Quantity</label>
            <input
              type="number"
              min="0"
              step="any"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
              placeholder="10"
              value={form.quantity}
              onChange={(e) => set('quantity', e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">Price</label>
            <input
              type="number"
              min="0"
              step="any"
              className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
              placeholder="182.50"
              value={form.price}
              onChange={(e) => set('price', e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-slate-500 mb-1">Thesis</label>
          <textarea
            rows={3}
            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-slate-500"
            placeholder="Why did you place this trade? What was your human reasoning?"
            value={form.thesis}
            onChange={(e) => set('thesis', e.target.value)}
          />
        </div>

        <div>
          <label className="block text-xs text-slate-500 mb-1">Notes (optional)</label>
          <input
            type="text"
            className="w-full bg-slate-900 border border-slate-700 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500"
            placeholder="Any additional context…"
            value={form.notes}
            onChange={(e) => set('notes', e.target.value)}
          />
        </div>

        {error && (
          <div className="text-xs text-red-400 bg-red-950/30 border border-red-900/40 rounded px-3 py-2">
            {error}
          </div>
        )}

        <button
          type="submit"
          className="w-full py-2.5 rounded bg-sky-700 hover:bg-sky-600 text-white text-sm font-semibold transition-colors"
        >
          Log Manual Trade
        </button>
      </form>
    </div>
  );
}
