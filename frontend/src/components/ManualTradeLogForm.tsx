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
  // Operator-discipline / journal-quality fields. Strings on the form;
  // confidence_before is parsed to a number on submit.
  invalidation_level: string;
  expected_horizon: string;
  risk_reason: string;
  entry_reason: string;
  exit_plan: string;
  confidence_before: string;
  emotional_state: string;
  mistake_tags: string;
  lesson: string;
}

interface Props {
  defaultEventId?: string;
  defaultTicker?: string;
  onLogged?: () => void;
}

// Mirrors backend bounds in scripts/signal_inbox_api.py
const LEVERAGE_MIN = 1.0;
const LEVERAGE_MAX = 25.0;

// Allowed emotional-state values. Kept short on purpose — long lists
// produce noise, not discipline. Operator can still type freeform via 'other'.
const EMOTIONAL_STATES = [
  '',
  'calm',
  'focused',
  'curious',
  'fomo',
  'fear',
  'revenge',
  'bored',
  'euphoric',
  'tired',
  'other',
];

const HORIZON_OPTIONS = ['', 'intraday', '1-2d', '2-5d', '1w', '2-4w', '1-3m', '3m+'];

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
    invalidation_level: '',
    expected_horizon: '',
    risk_reason: '',
    entry_reason: '',
    exit_plan: '',
    confidence_before: '',
    emotional_state: '',
    mistake_tags: '',
    lesson: '',
  });
  const [logged, setLogged] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [softWarnings, setSoftWarnings] = useState<string[]>([]);

  function set(field: keyof FormState, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError('');
  }

  function collectSoftWarnings(state: FormState): string[] {
    const w: string[] = [];
    if (!state.invalidation_level.trim()) w.push('No invalidation level — you may not know when the thesis is wrong.');
    if (!state.exit_plan.trim()) w.push('No exit plan — you may freeze on the exit.');
    if (!state.risk_reason.trim()) w.push('No risk reason — size may not be justified.');
    if (!state.confidence_before.trim()) w.push('No confidence-before recorded — calibration check will be missing.');
    if (!state.emotional_state.trim()) w.push('No emotional state — bias check will be missing.');
    return w;
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

    // Soft-warn but allow submit — we'd rather capture an imperfect record
    // than block the operator from logging at all.
    const warnings = collectSoftWarnings(form);
    setSoftWarnings(warnings);

    let confidence: number | null = null;
    const confRaw = form.confidence_before.trim();
    if (confRaw !== '') {
      const c = parseFloat(confRaw);
      if (isNaN(c) || c < 0 || c > 100) {
        setError('Confidence-before must be a number between 0 and 100 (or 0 and 1).');
        return;
      }
      confidence = c;
    }

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
        invalidation_level: form.invalidation_level.trim(),
        expected_horizon: form.expected_horizon.trim(),
        risk_reason: form.risk_reason.trim(),
        entry_reason: form.entry_reason.trim(),
        exit_plan: form.exit_plan.trim(),
        confidence_before: confidence,
        emotional_state: form.emotional_state.trim(),
        mistake_tags: form.mistake_tags.trim(),
        lesson: form.lesson.trim(),
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
          Manual Decision Recorded
        </div>
        <div className="text-xs" style={{ color: 'var(--sp-mist)' }}>
          Logged for human review. No broker API was called. AI executions:{' '}
          <span className="font-mono font-bold" style={{ color: 'var(--sp-cyan)' }}>0</span>
        </div>
        {softWarnings.length > 0 && (
          <div
            className="text-[11px] text-left rounded px-3 py-2 mx-auto max-w-md"
            style={{
              color: 'var(--sp-gold)',
              background: 'rgba(200, 154, 74, 0.06)',
              border: '1px solid rgba(200, 154, 74, 0.32)',
            }}
          >
            <div className="font-semibold mb-1">Journal-quality gaps logged:</div>
            <ul className="list-disc pl-4 space-y-0.5">
              {softWarnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </div>
        )}
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
        This form logs a manual decision/trade you made externally. It does not place trades, call brokers, or execute orders.
        Broker API: <span className="font-mono" style={{ color: 'var(--sp-gold)' }}>DISABLED</span>. AI executions:{' '}
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

        <Section title="Decision Discipline" subtitle="Future-you needs these to attribute outcomes to skill vs. luck.">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Invalidation level" hint="price/level where thesis is wrong">
              <input
                type="text"
                className="sp-input"
                placeholder="e.g. 1450 or break of 50EMA"
                value={form.invalidation_level}
                onChange={(e) => set('invalidation_level', e.target.value)}
              />
            </Field>
            <Field label="Expected horizon">
              <select
                className="sp-input"
                value={form.expected_horizon}
                onChange={(e) => set('expected_horizon', e.target.value)}
              >
                {HORIZON_OPTIONS.map((h) => (
                  <option key={h || 'unset'} value={h}>
                    {h || '(select)'}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Risk reason" hint="why this size is acceptable to lose">
            <input
              type="text"
              className="sp-input"
              placeholder="e.g. <=0.5R, lottery ticket, sized for vol"
              value={form.risk_reason}
              onChange={(e) => set('risk_reason', e.target.value)}
            />
          </Field>
          <Field label="Entry reason" hint="structural / signal-driven reason for entering">
            <input
              type="text"
              className="sp-input"
              placeholder="e.g. break of structure on increasing vol"
              value={form.entry_reason}
              onChange={(e) => set('entry_reason', e.target.value)}
            />
          </Field>
          <Field label="Exit plan" hint="how trade will close">
            <textarea
              rows={2}
              className="sp-input resize-none"
              placeholder="e.g. trim 50% at 1.5R, stop at invalidation, exit after 5 trading days if no follow-through"
              value={form.exit_plan}
              onChange={(e) => set('exit_plan', e.target.value)}
            />
          </Field>
        </Section>

        <Section title="Operator State" subtitle="Calibration over time depends on you recording this honestly.">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Confidence before" hint="0–1 or 0–100; your own estimate">
              <input
                type="number"
                min="0"
                max="100"
                step="0.01"
                className="sp-input"
                placeholder="0.55 or 55"
                value={form.confidence_before}
                onChange={(e) => set('confidence_before', e.target.value)}
              />
            </Field>
            <Field label="Emotional state">
              <select
                className="sp-input"
                value={form.emotional_state}
                onChange={(e) => set('emotional_state', e.target.value)}
              >
                {EMOTIONAL_STATES.map((s) => (
                  <option key={s || 'unset'} value={s}>
                    {s || '(select)'}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        </Section>

        <Section title="Learning" subtitle="Optional at entry — required at reconciliation. Capturing it here gives future-you a baseline.">
          <Field label="Mistake tags" hint="comma-separated; e.g. late_entry, oversized">
            <input
              type="text"
              className="sp-input"
              placeholder="optional — fill at reconciliation if not now"
              value={form.mistake_tags}
              onChange={(e) => set('mistake_tags', e.target.value)}
            />
          </Field>
          <Field label="Lesson / takeaway" hint="one line future-you should re-read">
            <input
              type="text"
              className="sp-input"
              placeholder="e.g. wait for retest next time"
              value={form.lesson}
              onChange={(e) => set('lesson', e.target.value)}
            />
          </Field>
        </Section>

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

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded-md p-3 space-y-3"
      style={{
        background: 'rgba(95, 189, 200, 0.03)',
        border: '1px solid rgba(95, 189, 200, 0.12)',
      }}
    >
      <div>
        <div className="sp-eyebrow" style={{ color: 'var(--sp-cyan)' }}>{title}</div>
        {subtitle && (
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--sp-mist)' }}>
            {subtitle}
          </div>
        )}
      </div>
      {children}
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
