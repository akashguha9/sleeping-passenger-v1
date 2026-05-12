/**
 * Deterministic next-human-action classifier for Signal Inbox cards.
 *
 * This is an ADVISORY-ONLY heuristic. It interprets existing signal fields into
 * a single recommended human action so the operator no longer stares at raw
 * priority/persistence/kill-rate numbers. It does NOT authorize execution,
 * place orders, sign transactions, or talk to a broker. Every action keeps the
 * advisory contract intact.
 *
 * Pure function — no I/O, no side effects, no time-dependent randomness.
 * Easy to unit test if a frontend test framework is added later.
 */

import type { InboxItem, BullState } from '@/types';

export type NextHumanAction =
  | 'IGNORE'
  | 'HAVE_A_LOOK'
  | 'WATCHLIST'
  | 'HUMAN_REVIEW'
  | 'MANUAL_CANDIDATE';

export type GateVerdict = 'OK' | 'WEAK' | 'BLOCK' | 'UNKNOWN' | 'NEUTRAL';

export interface GateDetails {
  source_quality: GateVerdict;
  source_quality_label: string;
  priority_gate: GateVerdict;
  priority_label: string;
  persistence_gate: GateVerdict;
  persistence_label: string;
  kill_rate_gate: GateVerdict;
  kill_rate_label: string;
  blocker_gate: GateVerdict;
  blocker_label: string;
  rejection_gate: GateVerdict;
  rejection_label: string;
  freshness_gate: GateVerdict;
  freshness_label: string;
}

export interface NextHumanActionResult {
  action: NextHumanAction;
  label: string;
  reason: string;
  severity_rank: number;
  gate_details: GateDetails;
}

export const ACTION_LABELS: Record<NextHumanAction, string> = {
  IGNORE: 'Ignore',
  HAVE_A_LOOK: 'Have a Look',
  WATCHLIST: 'Watchlist',
  HUMAN_REVIEW: 'Human Review',
  MANUAL_CANDIDATE: 'Manual Review Candidate',
};

export const ACTION_SEVERITY: Record<NextHumanAction, number> = {
  IGNORE: 0,
  HAVE_A_LOOK: 1,
  WATCHLIST: 2,
  HUMAN_REVIEW: 3,
  MANUAL_CANDIDATE: 4,
};

/**
 * Tailwind class strings for the action badge — kept in this module so the
 * styling stays in lockstep with the action set.
 */
export const ACTION_BADGE_CLASS: Record<NextHumanAction, string> = {
  IGNORE: 'text-red-300 bg-red-950/40 border-red-900/60',
  HAVE_A_LOOK: 'text-sky-300 bg-sky-950/40 border-sky-900/60',
  WATCHLIST: 'text-amber-300 bg-amber-950/40 border-amber-900/60',
  HUMAN_REVIEW: 'text-orange-300 bg-orange-950/40 border-orange-900/60',
  MANUAL_CANDIDATE: 'text-emerald-300 bg-emerald-950/40 border-emerald-900/60',
};

const STRONG_STATES: Set<BullState> = new Set<BullState>([
  'HURACÁN',
  'AVENTADOR',
  'MURCIÉLAGO',
  'GALLARDO',
]);

const CHAOS_STATES: Set<BullState> = new Set<BullState>(['DIABLO', 'ISLERO']);

const PLACEHOLDER_SOURCE_HINTS = [
  'unknown',
  'placeholder',
  'mock',
  'todo',
  'fake',
  'stub',
];

const FRESH_HOURS = 24;
const STALE_HOURS = 72;

function classifySourceQuality(item: InboxItem): {
  verdict: GateVerdict;
  label: string;
} {
  const raw = (item.source_file || '').toLowerCase().trim();
  if (!raw) {
    return { verdict: 'UNKNOWN', label: 'source missing' };
  }
  for (const hint of PLACEHOLDER_SOURCE_HINTS) {
    if (raw.includes(hint)) {
      return { verdict: 'UNKNOWN', label: `source flagged as ${hint}` };
    }
  }
  const files = raw
    .split(',')
    .map((f) => f.trim())
    .filter(Boolean);
  if (files.length === 0) {
    return { verdict: 'UNKNOWN', label: 'source missing' };
  }
  // Treat single bare source with no extension as weak
  if (files.length === 1 && !files[0].includes('.') && !files[0].includes('_')) {
    return { verdict: 'WEAK', label: `single bare source: ${files[0]}` };
  }
  if (files.length === 1) {
    // One named file with extension or underscore (e.g., crypto_signals.jsonl)
    return { verdict: 'OK', label: `1 source: ${files[0]}` };
  }
  return { verdict: 'OK', label: `${files.length} sources` };
}

function classifyFreshness(item: InboxItem): {
  verdict: GateVerdict;
  label: string;
} {
  const ts = item.observed_at;
  if (!ts) {
    return { verdict: 'UNKNOWN', label: 'no observed_at' };
  }
  const parsed = Date.parse(ts);
  if (Number.isNaN(parsed)) {
    return { verdict: 'UNKNOWN', label: 'unparseable observed_at' };
  }
  const ageHours = (Date.now() - parsed) / 3_600_000;
  if (ageHours < 0) {
    // Future timestamp (mock data with fixed dates often is) — treat as neutral
    return { verdict: 'NEUTRAL', label: 'observed_at in future (mock data)' };
  }
  if (ageHours <= FRESH_HOURS) {
    return { verdict: 'OK', label: `${Math.round(ageHours)}h old` };
  }
  if (ageHours <= STALE_HOURS) {
    return { verdict: 'WEAK', label: `${Math.round(ageHours)}h old` };
  }
  return { verdict: 'BLOCK', label: `${Math.round(ageHours)}h old (stale)` };
}

function gateForPriority(score: number): {
  verdict: GateVerdict;
  label: string;
} {
  if (score >= 0.75) return { verdict: 'OK', label: `${score.toFixed(2)} (high)` };
  if (score >= 0.4) return { verdict: 'WEAK', label: `${score.toFixed(2)} (mid)` };
  return { verdict: 'BLOCK', label: `${score.toFixed(2)} (low)` };
}

function gateForPersistence(score: number): {
  verdict: GateVerdict;
  label: string;
} {
  if (score >= 0.7) return { verdict: 'OK', label: `${score.toFixed(2)} (high)` };
  if (score >= 0.3) return { verdict: 'WEAK', label: `${score.toFixed(2)} (mid)` };
  return { verdict: 'BLOCK', label: `${score.toFixed(2)} (low)` };
}

function gateForKillRate(score: number): {
  verdict: GateVerdict;
  label: string;
} {
  if (score >= 0.8) return { verdict: 'BLOCK', label: `${score.toFixed(2)} (high)` };
  if (score >= 0.5) return { verdict: 'WEAK', label: `${score.toFixed(2)} (elevated)` };
  if (score >= 0.3) return { verdict: 'WEAK', label: `${score.toFixed(2)} (moderate)` };
  return { verdict: 'OK', label: `${score.toFixed(2)} (low)` };
}

function gateForBlocker(score: number): {
  verdict: GateVerdict;
  label: string;
} {
  if (score >= 0.7) return { verdict: 'BLOCK', label: `${score.toFixed(2)} (high)` };
  if (score >= 0.5) return { verdict: 'WEAK', label: `${score.toFixed(2)} (elevated)` };
  if (score >= 0.3) return { verdict: 'WEAK', label: `${score.toFixed(2)} (moderate)` };
  return { verdict: 'OK', label: `${score.toFixed(2)} (low)` };
}

function gateForRejections(dims: string[]): {
  verdict: GateVerdict;
  label: string;
} {
  if (!dims || dims.length === 0) {
    return { verdict: 'OK', label: 'no rejection dimensions' };
  }
  if (dims.length >= 2) {
    return { verdict: 'BLOCK', label: `${dims.length} rejection dimensions` };
  }
  return { verdict: 'WEAK', label: `1 rejection dimension` };
}

function buildGateDetails(item: InboxItem): GateDetails {
  const source = classifySourceQuality(item);
  const priority = gateForPriority(item.priority_score);
  const persistence = gateForPersistence(item.persistence_score);
  const killRate = gateForKillRate(item.kill_rate_score);
  const blocker = gateForBlocker(item.blocker_pressure_score);
  const rejection = gateForRejections(item.rejection_dimensions || []);
  const freshness = classifyFreshness(item);
  return {
    source_quality: source.verdict,
    source_quality_label: source.label,
    priority_gate: priority.verdict,
    priority_label: priority.label,
    persistence_gate: persistence.verdict,
    persistence_label: persistence.label,
    kill_rate_gate: killRate.verdict,
    kill_rate_label: killRate.label,
    blocker_gate: blocker.verdict,
    blocker_label: blocker.label,
    rejection_gate: rejection.verdict,
    rejection_label: rejection.label,
    freshness_gate: freshness.verdict,
    freshness_label: freshness.label,
  };
}

function hasSeriousRejection(dims: string[]): boolean {
  return (dims || []).length >= 2;
}

/**
 * Pure, deterministic classifier. See module docstring for advisory contract.
 *
 * Rules — first match wins:
 *   1. IGNORE — hard blockers (rejected, DIABLO, UNKNOWN source, very high
 *      kill_rate/blocker, very low priority/persistence).
 *   2. MANUAL_CANDIDATE — strong-state + very high priority/persistence,
 *      very low kill/blocker, known source, no rejections, supporting context.
 *   3. HUMAN_REVIEW — high priority/persistence, low kill/blocker, known
 *      source, no serious rejections, not in chaos state.
 *   4. WATCHLIST — solid priority/persistence with acceptable friction.
 *   5. HAVE_A_LOOK — non-trivial but weak evidence.
 *   6. Fallback — IGNORE with "below threshold" reason.
 */
export function deriveNextHumanAction(item: InboxItem): NextHumanActionResult {
  const gates = buildGateDetails(item);
  const source = gates.source_quality;
  const state = item.signal_state as BullState;
  const priority = item.priority_score;
  const persistence = item.persistence_score;
  const killRate = item.kill_rate_score;
  const blocker = item.blocker_pressure_score;
  const dims = item.rejection_dimensions || [];
  const userStatus = item.user_status;
  const hasContext = item.has_reflection || item.has_ai_summary;

  // ----- Rule A: IGNORE -----
  if (userStatus === 'rejected') {
    return makeResult('IGNORE', 'Signal is already rejected.', gates);
  }
  if (source === 'UNKNOWN') {
    return makeResult(
      'IGNORE',
      'Source is UNKNOWN, so this signal cannot be trusted yet.',
      gates,
    );
  }
  if (state === 'DIABLO') {
    return makeResult(
      'IGNORE',
      'Signal state is DIABLO (chaos shock). Do not act without explicit override.',
      gates,
    );
  }
  if (killRate >= 0.8) {
    return makeResult(
      'IGNORE',
      `Kill rate ${killRate.toFixed(2)} is too high for review.`,
      gates,
    );
  }
  if (blocker >= 0.7) {
    return makeResult(
      'IGNORE',
      `Blocker pressure ${blocker.toFixed(2)} is too high.`,
      gates,
    );
  }
  if (priority <= 0.2) {
    return makeResult(
      'IGNORE',
      `Priority ${priority.toFixed(2)} below review floor.`,
      gates,
    );
  }
  if (persistence <= 0.2) {
    return makeResult(
      'IGNORE',
      `Persistence ${persistence.toFixed(2)} below review floor.`,
      gates,
    );
  }
  if (hasSeriousRejection(dims) && blocker >= 0.5) {
    return makeResult(
      'IGNORE',
      `${dims.length} rejection dimensions with blocker pressure ${blocker.toFixed(
        2,
      )} — combined block.`,
      gates,
    );
  }

  // ----- Rule E: MANUAL_CANDIDATE (strict gate) -----
  // UNKNOWN source was already filtered above; require OK (not WEAK).
  if (
    STRONG_STATES.has(state) &&
    priority >= 0.8 &&
    persistence >= 0.75 &&
    killRate <= 0.25 &&
    blocker <= 0.25 &&
    source === 'OK' &&
    dims.length === 0 &&
    hasContext
  ) {
    return makeResult(
      'MANUAL_CANDIDATE',
      'High-priority, persistent, low-kill signal with known source and supporting context. Still advisory-only and requires human decision.',
      gates,
    );
  }

  // ----- Rule D: HUMAN_REVIEW -----
  if (
    priority >= 0.75 &&
    persistence >= 0.7 &&
    killRate <= 0.3 &&
    blocker <= 0.3 &&
    source === 'OK' &&
    !hasSeriousRejection(dims) &&
    !CHAOS_STATES.has(state)
  ) {
    return makeResult(
      'HUMAN_REVIEW',
      'Strong priority, persistence, and low kill rate. Human review required before any manual decision.',
      gates,
    );
  }

  // ----- Rule C: WATCHLIST -----
  // UNKNOWN source was already filtered above.
  if (
    priority >= 0.6 &&
    persistence >= 0.55 &&
    killRate < 0.5 &&
    blocker < 0.5 &&
    !hasSeriousRejection(dims)
  ) {
    return makeResult(
      'WATCHLIST',
      'Signal has enough structure to monitor, but still needs confirmation before human review.',
      gates,
    );
  }

  // ----- Rule B: HAVE_A_LOOK -----
  if (
    priority >= 0.4 &&
    persistence >= 0.3 &&
    killRate < 0.8 &&
    blocker < 0.7
  ) {
    let why =
      'Priority and persistence are non-trivial, but evidence is not strong enough to promote beyond a look.';
    if (source === 'WEAK') {
      why =
        'Priority and persistence are non-trivial, but source quality is weak — cannot promote to watchlist.';
    } else if (dims.length === 1) {
      why = `Priority and persistence are non-trivial, but rejection dimension "${dims[0]}" blocks promotion.`;
    } else if (CHAOS_STATES.has(state)) {
      why = `Priority and persistence are non-trivial, but signal state ${state} indicates chaos — cannot promote.`;
    }
    return makeResult('HAVE_A_LOOK', why, gates);
  }

  // ----- Fallback: IGNORE -----
  return makeResult(
    'IGNORE',
    'Scores below review thresholds across priority/persistence/kill/blocker gates.',
    gates,
  );
}

function makeResult(
  action: NextHumanAction,
  reason: string,
  gates: GateDetails,
): NextHumanActionResult {
  return {
    action,
    label: ACTION_LABELS[action],
    reason,
    severity_rank: ACTION_SEVERITY[action],
    gate_details: gates,
  };
}

/**
 * Convenience: list every supported action in display order. Useful for
 * rendering filter chips without hardcoding the list at the call site.
 */
export const ALL_ACTIONS: NextHumanAction[] = [
  'IGNORE',
  'HAVE_A_LOOK',
  'WATCHLIST',
  'HUMAN_REVIEW',
  'MANUAL_CANDIDATE',
];
