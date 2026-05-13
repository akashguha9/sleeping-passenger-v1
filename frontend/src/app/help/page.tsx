'use client';

import Link from 'next/link';
import { AdvisoryOnlyBadge } from '@/components/AdvisoryOnlyBadge';
import { HumanOnlyBadge } from '@/components/HumanOnlyBadge';

export default function HelpPage() {
  return (
    <div className="max-w-3xl mx-auto space-y-6" data-testid="help-page">
      <div className="flex items-start justify-between">
        <div>
          <div className="sp-eyebrow mb-1">Onboarding</div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            style={{ color: 'var(--sp-bone)', letterSpacing: '-0.01em' }}
          >
            How this works
          </h1>
          <p className="text-sm mt-1" style={{ color: 'var(--sp-mist)' }}>
            Read this before you act on anything you see in this app.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <AdvisoryOnlyBadge size="md" />
          <HumanOnlyBadge size="md" />
        </div>
      </div>

      <Section title="What this is">
        <p>
          SleepingPassenger is a <strong>local-first advisory journal</strong>.
          It surfaces candidate trading signals from public sources and
          gives you somewhere to record your <em>own</em> manual decisions,
          your reasoning, your trades, and the outcomes.
        </p>
        <p>
          It is meant for one human, on one laptop, reviewing one inbox at a
          time. Everything visible on screen is a <strong>suggestion</strong>.
        </p>
      </Section>

      <Section title="What this is not">
        <ul className="list-disc pl-5 space-y-1">
          <li>
            <strong>It is not a broker.</strong> No button on any screen
            places, cancels, or modifies an order with any exchange or
            brokerage. There is no broker API connection.
          </li>
          <li>
            <strong>It is not an execution engine.</strong> No code path
            in this app can decide to trade for you. The AI execution count
            is always <code className="font-mono">0</code>.
          </li>
          <li>
            <strong>It is not financial advice.</strong> Signals are
            heuristics over public data. Treat them like a conversation
            partner, not a verdict.
          </li>
          <li>
            <strong>It is not a multi-user platform.</strong> One operator,
            one DB file on disk.
          </li>
        </ul>
      </Section>

      <Section title="Canonical workflow">
        <ol className="list-decimal pl-5 space-y-1.5">
          <li>
            <strong>Review.</strong> Open the{' '}
            <Link href="/signal-inbox" className="text-sky-400 underline">
              Signal Inbox
            </Link>
            . Scan the highest-priority items.
          </li>
          <li>
            <strong>Reflect.</strong> Use the{' '}
            <Link href="/reflection-desk" className="text-sky-400 underline">
              Reflection Desk
            </Link>{' '}
            to write your own thesis or counter-thesis. Disagree with the
            signal in writing — that is the point.
          </li>
          <li>
            <strong>Decide manually.</strong> If you do place a trade with
            your real broker (outside this app), record it in the{' '}
            <Link href="/manual-trade-log" className="text-sky-400 underline">
              Manual Trade Log
            </Link>
            .
          </li>
          <li>
            <strong>Reconcile.</strong> When the trade closes, fill in the
            outcome in{' '}
            <Link href="/reconciliation" className="text-sky-400 underline">
              Reconciliation
            </Link>
            .
          </li>
          <li>
            <strong>Learn.</strong> If you made a mistake, write a moltbook
            entry in the{' '}
            <Link href="/moltbook" className="text-sky-400 underline">
              Moltbook
            </Link>
            . If you want to take the data outside the app, use{' '}
            <Link href="/exports" className="text-sky-400 underline">
              Exports
            </Link>
            .
          </li>
        </ol>
      </Section>

      <Section title="Words you will see">
        <Glossary
          rows={[
            {
              term: 'ADVISORY_ONLY',
              meaning:
                'Every response from the backend is stamped with this. It means: the app is not authorized to trade on your behalf.',
            },
            {
              term: 'HUMAN_ONLY / execution_gate=LOCKED',
              meaning:
                'Execution requires a human. The gate cannot be unlocked from the UI, from a config flag, or by an AI prompt.',
            },
            {
              term: 'MOCK_FALLBACK / BACKEND OFFLINE',
              meaning:
                'When the API server is not reachable, the dashboard falls back to a small bundled mock dataset so you can still see the UI. This is always labelled. Mock data is never claimed to be canonical.',
            },
            {
              term: 'Bull state (MIURA, MURCIÉLAGO, etc.)',
              meaning:
                'A taxonomy label assigned to each signal by the fabric. Hover a badge to read the plain-English meaning.',
            },
            {
              term: 'manual_trades.broker_api_called',
              meaning:
                'Always false. The field exists so any downstream consumer can verify the contract.',
            },
          ]}
        />
      </Section>

      <Section title="Running the system">
        <ul className="list-disc pl-5 space-y-1.5">
          <li>
            <strong>Start the backend:</strong>{' '}
            <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded text-xs">
              python scripts/api_server.py
            </code>
          </li>
          <li>
            <strong>Run the smoke check before a demo:</strong>{' '}
            <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded text-xs">
              python scripts/smoke_check.py --api http://127.0.0.1:8000
            </code>
          </li>
          <li>
            <strong>Back up the DB:</strong>{' '}
            <code className="font-mono bg-slate-800 px-1.5 py-0.5 rounded text-xs">
              python scripts/backup_db.py
            </code>{' '}
            (or use the PowerShell wrapper at{' '}
            <code className="font-mono">scripts/windows/backup_sleepingpassenger_db.ps1</code>).
            See <code className="font-mono">docs/WINDOWS_BACKUP_TASK.md</code> for daily automation.
          </li>
          <li>
            <strong>Where the data lives:</strong>{' '}
            <code className="font-mono">runtime/mvp_local.db</code>. Backups
            live in <code className="font-mono">runtime/backups/</code>.
            Neither directory is checked into git.
          </li>
        </ul>
      </Section>

      <Section title="Honest limits">
        <ul className="list-disc pl-5 space-y-1.5">
          <li>The signal sources are public-data heuristics, not proprietary alpha.</li>
          <li>Live data sources can rate-limit or go down. Source health is on the dashboard.</li>
          <li>There is no production-grade authentication. The optional <code className="font-mono">MVP_API_TOKEN</code> is a single shared secret for mutating routes.</li>
          <li>The MVP is not legally reviewed. Do not use it to advise other humans.</li>
        </ul>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-slate-900/60 border border-slate-700/60 rounded-lg p-5">
      <h2 className="text-sm font-semibold text-slate-200 mb-3">{title}</h2>
      <div className="text-sm text-slate-400 space-y-2 leading-relaxed">{children}</div>
    </section>
  );
}

function Glossary({ rows }: { rows: { term: string; meaning: string }[] }) {
  return (
    <dl className="space-y-2.5">
      {rows.map((r) => (
        <div key={r.term}>
          <dt className="font-mono text-xs text-amber-300">{r.term}</dt>
          <dd className="text-sm text-slate-400 ml-1 mt-0.5">{r.meaning}</dd>
        </div>
      ))}
    </dl>
  );
}
