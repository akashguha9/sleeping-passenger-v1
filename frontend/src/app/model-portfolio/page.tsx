'use client';

import { useEffect, useState } from 'react';
import { API_BASE } from '@/lib/config';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

// Customer-facing model portfolio page.
//
// This page is the single understandable-by-a-normal-user surface of
// the product.  It hides the operator/state-machine language and
// presents thematic baskets, target weights, risk bands, and the
// internal-to-customer translation table.  It calls only the
// read-only /api/customer/* endpoints; if the backend is offline it
// falls back to a bundled snapshot so the UI is never a blank page.
//
// Safety contract: nothing on this page issues a trade, places an
// order, calls a broker API, or claims to execute on behalf of the
// user.  Every section carries the advisory-only and no-execution
// badges.

type AllocationRow = {
  basket_id: string;
  basket_name: string;
  target_weight: number;
  min_weight: number;
  max_weight: number;
  current_action_label: string;
  risk_level: string;
  thesis_summary: string;
  invalidation_summary: string;
  rebalance_rule: string;
  representative_tickers: string[];
};

type Basket = {
  basket_id: string;
  basket_name: string;
  plain_english_thesis: string;
  customer_description: string;
  example_tickers: string[];
  risk_level: string;
  default_model_weight_range: string;
  max_drawdown_trigger: string;
  rebalance_rule: string;
  what_would_break_thesis: string;
};

type TranslationRow = {
  internal_state: string;
  customer_label: string;
  meaning: string;
  customer_guidance: string;
};

type CustomerFacingGateState = {
  customer_facing_enabled: boolean;
  env_flag_true: boolean;
  n_real: number;
  n_real_floor: number;
  evidence_status: string;
  calibration_status: string;
  demo_only_label: string | null;
  disabled_message: string | null;
};

type ModelPortfolioResponse = {
  model_portfolio: {
    model_portfolio_id: string;
    model_portfolio_name: string;
    description: string;
    risk_profile: string;
    rebalance_frequency: string;
    drawdown_rules: Record<string, string>;
    total_target_weight: number;
    allocation: AllocationRow[];
  };
  summary: {
    basket_count: number;
    total_target_weight: number;
    advisory_disclaimer: string;
  };
  translation_table: TranslationRow[];
  customer_facing_gate?: CustomerFacingGateState;
  demo_only_label?: string | null;
};

type CustomerFacingDisabledResponse = {
  disabled: true;
  reason: string;
  customer_facing_gate: CustomerFacingGateState;
};

const FALLBACK_DISCLAIMER =
  'This product provides educational research and decision support only. ' +
  'It is not financial advice, not a promise of returns, and not an ' +
  'instruction to trade. Human decision-making is required.';

const TICKER_NARRATIVES: { ticker: string; narrative: string }[] = [
  {
    ticker: 'RHM.DE',
    narrative:
      'belongs to the Defense Sovereignty Basket because the company is exposed to European defense spending, procurement cycles, rearmament demand, and security policy.',
  },
  {
    ticker: 'VALE',
    narrative:
      'belongs to the Commodity Repricing Basket because it is exposed to iron ore, metals demand, commodity cycles, and supply-demand repricing.',
  },
  {
    ticker: 'ZIM',
    narrative:
      'belongs to the Shipping Dislocation Basket because it is exposed to freight rates, route disruptions, shipping supply/demand, and geopolitical trade shocks.',
  },
  {
    ticker: 'NVDA',
    narrative:
      'belongs to the AI Infrastructure Basket because it is exposed to AI chips, accelerators, data center capex, and compute infrastructure.',
  },
  {
    ticker: 'XOM',
    narrative:
      'belongs to the Energy Shock Basket because it is exposed to oil, gas, LNG, energy security, and supply disruption repricing.',
  },
  {
    ticker: 'NSE:BHARTIARTL',
    narrative:
      'belongs to the India Domestic Compounding Basket because it is exposed to Indian telecom demand, digital adoption, domestic consumption, and long-term infrastructure growth.',
  },
];

export default function ModelPortfolioPage() {
  const [data, setData] = useState<ModelPortfolioResponse | null>(null);
  const [disabled, setDisabled] = useState<CustomerFacingDisabledResponse | null>(null);
  const [isOffline, setIsOffline] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const resp = await fetch(`${API_BASE}/api/customer/model-portfolio`);
        if (!resp.ok) throw new Error(`status ${resp.status}`);
        const body = (await resp.json()) as
          | ModelPortfolioResponse
          | CustomerFacingDisabledResponse;
        if (cancelled) return;
        if ((body as CustomerFacingDisabledResponse).disabled) {
          setDisabled(body as CustomerFacingDisabledResponse);
        } else {
          setData(body as ModelPortfolioResponse);
        }
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
    <div className="max-w-6xl mx-auto space-y-8" data-testid="model-portfolio-page">
      <HeroSection />
      {disabled ? (
        <DisabledNotice disabled={disabled} />
      ) : isOffline ? (
        <OfflineNotice error={error} />
      ) : data ? (
        <>
          {data.demo_only_label ? (
            <DemoOnlyBanner
              label={data.demo_only_label}
              gate={data.customer_facing_gate}
            />
          ) : null}
          <ModelSummary data={data} />
          <AllocationTable allocation={data.model_portfolio.allocation} />
          <BasketCards
            baskets={data.model_portfolio.allocation.map(toBasketCardInput)}
          />
          <TickerExplanations />
          <TranslationEducation rows={data.translation_table} />
          <SafetyFooter disclaimer={data.summary.advisory_disclaimer} />
        </>
      ) : (
        <div className="text-sm" style={{ color: 'var(--sp-mist)' }}>
          Loading model portfolio…
        </div>
      )}
    </div>
  );
}

function DisabledNotice({ disabled }: { disabled: CustomerFacingDisabledResponse }) {
  const gate = disabled.customer_facing_gate;
  return (
    <section
      className="rounded-lg p-6 space-y-3"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="customer-facing-disabled-notice"
    >
      <div className="sp-eyebrow">Customer-facing mode</div>
      <h2
        className="text-lg font-semibold tracking-tight"
        style={{ color: 'var(--sp-bone)' }}
      >
        Customer-facing mode is disabled
      </h2>
      <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
        {disabled.reason}
      </p>
      <ul className="text-xs space-y-1" style={{ color: 'var(--sp-mist)' }}>
        <li>N_real: {gate.n_real} (floor: {gate.n_real_floor})</li>
        <li>calibration_status: {gate.calibration_status}</li>
        <li>evidence_status: {gate.evidence_status}</li>
      </ul>
      <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
        Advisory only. No execution. Broker API not connected. AI executions: 0.
      </p>
    </section>
  );
}

function DemoOnlyBanner({
  label,
  gate,
}: {
  label: string;
  gate: CustomerFacingGateState | undefined;
}) {
  return (
    <section
      className="rounded-lg p-4"
      style={{
        background: 'rgba(80, 50, 0, 0.35)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="customer-facing-demo-only-banner"
    >
      <div className="sp-eyebrow">{label}</div>
      <p className="text-xs mt-1" style={{ color: 'var(--sp-mist)' }}>
        This view is shown because the local-dev override is set.  The proof
        loop has not closed: N_real={gate?.n_real ?? 0} (floor:{' '}
        {gate?.n_real_floor ?? 20}); calibration_status=
        {gate?.calibration_status ?? 'INSUFFICIENT_EVIDENCE'}.  Advisory
        only. No execution. Broker API not connected. AI executions: 0.
      </p>
    </section>
  );
}

function HeroSection() {
  return (
    <section
      className="rounded-lg p-6"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="flex items-start justify-between gap-6 flex-wrap">
        <div>
          <div className="sp-eyebrow mb-2">Research View</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            Sleeping Passenger Model Portfolio Research
          </h1>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--sp-mist)' }}>
            AI-assisted thematic basket research for understanding market
            regimes, portfolio exposure, and risk — advisory-only, no
            execution.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
          <Badge label="No Execution" />
          <Badge label="Research View" />
        </div>
      </div>
      <p className="text-xs mt-4" style={{ color: 'var(--sp-mist)' }}>
        {FALLBACK_DISCLAIMER}
      </p>
    </section>
  );
}

function ModelSummary({ data }: { data: ModelPortfolioResponse }) {
  const mp = data.model_portfolio;
  return (
    <section
      className="rounded-lg p-6 space-y-3"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="model-portfolio-summary"
    >
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2
            className="text-lg font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)' }}
          >
            {mp.model_portfolio_name}
          </h2>
          <p className="text-sm mt-1 max-w-3xl" style={{ color: 'var(--sp-mist)' }}>
            {mp.description}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Badge label="Advisory Only" />
          <Badge label="Human Decision Required" />
          <Badge label="No Execution" />
        </div>
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
        <Stat label="Risk profile" value={mp.risk_profile} />
        <Stat label="Rebalance" value={mp.rebalance_frequency} />
        <Stat
          label="Total allocation"
          value={`${mp.total_target_weight.toFixed(0)}%`}
        />
        <Stat label="Baskets" value={String(mp.allocation.length)} />
      </dl>
      <div className="border-t pt-3" style={{ borderColor: 'var(--sp-line)' }}>
        <div className="sp-eyebrow mb-1">Drawdown warnings</div>
        <ul className="text-xs space-y-1" style={{ color: 'var(--sp-mist)' }}>
          {Object.entries(mp.drawdown_rules).map(([key, rule]) => (
            <li key={key}>
              <span style={{ color: 'var(--sp-gold)' }}>•</span> {rule}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function AllocationTable({ allocation }: { allocation: AllocationRow[] }) {
  return (
    <section
      className="rounded-lg p-6"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="allocation-table"
    >
      <h2
        className="text-lg font-semibold tracking-tight mb-3"
        style={{ color: 'var(--sp-bone)' }}
      >
        Basket allocation
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr
              className="text-left text-[10px] font-mono uppercase tracking-widest"
              style={{ color: 'var(--sp-mist)' }}
            >
              <th className="py-2 pr-3">Basket</th>
              <th className="py-2 pr-3">Target weight</th>
              <th className="py-2 pr-3">Weight range</th>
              <th className="py-2 pr-3">Risk level</th>
              <th className="py-2 pr-3">Current status</th>
              <th className="py-2 pr-3">Rebalance rule</th>
              <th className="py-2 pr-3">Thesis summary</th>
            </tr>
          </thead>
          <tbody>
            {allocation.map((row) => (
              <tr
                key={row.basket_id}
                style={{ borderTop: '1px solid var(--sp-line)' }}
              >
                <td className="py-2 pr-3 font-medium" style={{ color: 'var(--sp-bone)' }}>
                  {row.basket_name}
                </td>
                <td className="py-2 pr-3 font-mono">{row.target_weight.toFixed(0)}%</td>
                <td className="py-2 pr-3 font-mono" style={{ color: 'var(--sp-mist)' }}>
                  {row.min_weight.toFixed(0)}–{row.max_weight.toFixed(0)}%
                </td>
                <td className="py-2 pr-3" style={{ color: 'var(--sp-mist)' }}>
                  {row.risk_level}
                </td>
                <td className="py-2 pr-3">
                  <ActionChip label={row.current_action_label} />
                </td>
                <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                  {row.rebalance_rule}
                </td>
                <td
                  className="py-2 pr-3 text-xs max-w-md"
                  style={{ color: 'var(--sp-mist)' }}
                >
                  {row.thesis_summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function BasketCards({ baskets }: { baskets: Basket[] }) {
  return (
    <section data-testid="basket-cards" className="space-y-3">
      <h2
        className="text-lg font-semibold tracking-tight"
        style={{ color: 'var(--sp-bone)' }}
      >
        Basket research notes
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {baskets.map((b) => (
          <div
            key={b.basket_id}
            className="rounded-lg p-5 space-y-2"
            style={{
              background: 'rgba(13, 16, 21, 0.55)',
              border: '1px solid var(--sp-line)',
            }}
          >
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-semibold" style={{ color: 'var(--sp-bone)' }}>
                {b.basket_name}
              </h3>
              <span
                className="text-[10px] font-mono uppercase tracking-widest"
                style={{ color: 'var(--sp-gold)' }}
              >
                Risk · {b.risk_level}
              </span>
            </div>
            <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
              {b.plain_english_thesis}
            </p>
            <div className="grid grid-cols-2 gap-2 text-xs pt-2">
              <Stat label="Target weight" value={b.default_model_weight_range} />
              <Stat label="Drawdown trigger" value={b.max_drawdown_trigger} />
            </div>
            <div className="text-xs pt-2" style={{ color: 'var(--sp-mist)' }}>
              <span className="sp-eyebrow">Representative tickers</span>
              <div className="mt-1 font-mono">
                {b.example_tickers.join(' · ')}
              </div>
            </div>
            <div className="text-xs pt-2" style={{ color: 'var(--sp-mist)' }}>
              <span className="sp-eyebrow">What would break the thesis</span>
              <div className="mt-1">{b.what_would_break_thesis}</div>
            </div>
            <div className="text-xs pt-2" style={{ color: 'var(--sp-mist)' }}>
              <span className="sp-eyebrow">Rebalance rule</span>
              <div className="mt-1">{b.rebalance_rule}</div>
            </div>
            <div
              className="text-[10px] font-mono uppercase tracking-widest pt-2"
              style={{ color: 'var(--sp-gold)' }}
            >
              Advisory only · human decision required · no execution
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TickerExplanations() {
  return (
    <section
      className="rounded-lg p-6"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="ticker-explanations"
    >
      <h2
        className="text-lg font-semibold tracking-tight"
        style={{ color: 'var(--sp-bone)' }}
      >
        Why is this ticker here?
      </h2>
      <p className="text-sm mt-1" style={{ color: 'var(--sp-mist)' }}>
        Each ticker shows up in the model portfolio because it is exposed to
        the thesis of a thematic basket — never as a standalone "buy this
        stock" call.
      </p>
      <dl className="mt-3 space-y-2">
        {TICKER_NARRATIVES.map((row) => (
          <div key={row.ticker} className="text-sm">
            <dt
              className="font-mono text-xs"
              style={{ color: 'var(--sp-gold)' }}
            >
              {row.ticker}
            </dt>
            <dd className="ml-1 mt-0.5" style={{ color: 'var(--sp-mist)' }}>
              {row.ticker} {row.narrative}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function TranslationEducation({ rows }: { rows: TranslationRow[] }) {
  return (
    <section
      className="rounded-lg p-6"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
      data-testid="translation-education"
    >
      <h2
        className="text-lg font-semibold tracking-tight"
        style={{ color: 'var(--sp-bone)' }}
      >
        Internal-to-customer translation
      </h2>
      <p className="text-sm mt-1" style={{ color: 'var(--sp-mist)' }}>
        The engine uses internal diagnostic states. The customer interface
        translates them into simple action labels.
      </p>
      <table className="mt-3 w-full text-sm">
        <thead>
          <tr
            className="text-left text-[10px] font-mono uppercase tracking-widest"
            style={{ color: 'var(--sp-mist)' }}
          >
            <th className="py-2 pr-3">Internal state</th>
            <th className="py-2 pr-3">Customer label</th>
            <th className="py-2 pr-3">Meaning</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.internal_state}
              style={{ borderTop: '1px solid var(--sp-line)' }}
            >
              <td className="py-2 pr-3 font-mono text-xs" style={{ color: 'var(--sp-gold)' }}>
                {r.internal_state}
              </td>
              <td className="py-2 pr-3 font-medium" style={{ color: 'var(--sp-bone)' }}>
                {r.customer_label}
              </td>
              <td className="py-2 pr-3 text-xs" style={{ color: 'var(--sp-mist)' }}>
                {r.meaning}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function SafetyFooter({ disclaimer }: { disclaimer: string }) {
  return (
    <section
      className="rounded-lg p-5"
      style={{
        background: 'rgba(200, 154, 74, 0.04)',
        border: '1px solid rgba(200, 154, 74, 0.22)',
      }}
      data-testid="safety-footer"
    >
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <Badge label="Advisory Only" />
        <Badge label="Human Decision Required" />
        <Badge label="No Execution" />
        <Badge label="Not Financial Advice" />
      </div>
      <p className="text-xs" style={{ color: 'var(--sp-mist)' }}>
        {disclaimer}
      </p>
    </section>
  );
}

function OfflineNotice({ error }: { error: string | null }) {
  return (
    <section
      className="rounded-lg p-5"
      style={{
        background: 'rgba(13, 16, 21, 0.55)',
        border: '1px solid var(--sp-line)',
      }}
    >
      <div className="sp-eyebrow mb-1">Backend offline</div>
      <p className="text-sm" style={{ color: 'var(--sp-mist)' }}>
        The local API server is not reachable
        {error ? <code className="font-mono ml-1">({error})</code> : null}. The
        model portfolio surface is populated by{' '}
        <code className="font-mono">/api/customer/model-portfolio</code>;
        start the backend with{' '}
        <code className="font-mono">python scripts/api_server.py</code>.
      </p>
      <p className="text-xs mt-3" style={{ color: 'var(--sp-mist)' }}>
        {FALLBACK_DISCLAIMER}
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

function ActionChip({ label }: { label: string }) {
  // Customer-facing action labels only — never raw internal states.
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

function toBasketCardInput(row: AllocationRow): Basket {
  return {
    basket_id: row.basket_id,
    basket_name: row.basket_name,
    plain_english_thesis: row.thesis_summary,
    customer_description: row.thesis_summary,
    example_tickers: row.representative_tickers,
    risk_level: row.risk_level,
    default_model_weight_range: `${row.min_weight.toFixed(0)}–${row.max_weight.toFixed(0)}%`,
    max_drawdown_trigger: '',
    rebalance_rule: row.rebalance_rule,
    what_would_break_thesis: row.invalidation_summary,
  };
}
