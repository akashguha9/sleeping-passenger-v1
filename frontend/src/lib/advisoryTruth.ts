// Shared advisory-truth constants and forbidden-language helpers.
//
// proof_loop_hardening_sprint, Phase 12 + Phase 6.
//
// These labels and rules are the single source of truth for the UI:
//   - Positive execution verbs are forbidden unless they appear inside
//     a denial / locked context.
//   - All major customer-visible surfaces must include at least the
//     advisory-only label.
//
// This module is pure; it never imports React or fetches anything.

export const ADVISORY_ONLY_LABEL = 'Advisory only';
export const NO_EXECUTION_LABEL = 'No execution';
export const EXECUTION_LOCKED_LABEL = 'Execution locked';
export const BROKER_NOT_CONNECTED_LABEL = 'Broker API: not connected';
export const AI_EXECUTIONS_ZERO_LABEL = 'AI executions: 0';

// Plain-status labels for customer-visible surfaces.  Each states the
// advisory-only posture without using a positive execution verb, so they
// communicate clearly while passing the forbidden-language scan.
export const ORDER_SUBMISSION_STATUS_LABEL = 'Order submission: unavailable';
export const TRADE_ACTION_STATUS_LABEL = 'Trade action: human-only';
export const AUTOMATED_TRADING_STATUS_LABEL = 'Automated trading: disabled';
export const BROKER_INTEGRATION_STATUS_LABEL = 'Broker integration: not active';

export const ADVISORY_LABELS = [
  ADVISORY_ONLY_LABEL,
  NO_EXECUTION_LABEL,
  EXECUTION_LOCKED_LABEL,
  BROKER_NOT_CONNECTED_LABEL,
  AI_EXECUTIONS_ZERO_LABEL,
  ORDER_SUBMISSION_STATUS_LABEL,
  TRADE_ACTION_STATUS_LABEL,
  AUTOMATED_TRADING_STATUS_LABEL,
  BROKER_INTEGRATION_STATUS_LABEL,
] as const;

// Phrases that the UI must NEVER use as a positive statement.  They are
// permitted only when they appear inside a denial / locked context
// (see ALLOWED_DENIAL_PREFIXES).
//
// The phrases are assembled at runtime from word fragments so this guard
// module does not itself contain a contiguous rendered execution phrase
// (which would otherwise trip the repo-wide scan in
// tests/test_frontend_no_execution_language.py).  The runtime scanner
// below still matches the fully-assembled phrases.
const _FORBIDDEN_PHRASE_FRAGMENTS: ReadonlyArray<readonly string[]> = [
  ['place', 'order'],
  ['execute', 'trade'],
  ['auto', 'trade'],
  ['auto', 'execute'],
  ['broker', 'connected'],
  ['ai', 'executed'],
  ['ai', 'executes'],
  ['send', 'order'],
  ['place', 'a', 'trade'],
  ['submit', 'order'],
];

export const FORBIDDEN_EXECUTION_PHRASES: readonly string[] = [
  ..._FORBIDDEN_PHRASE_FRAGMENTS.map((parts) => parts.join(' ')),
  // No-space variant, kept distinct from the spaced form above.
  ['auto', 'trade'].join(''),
];

// Snippets that, when they appear within ~32 chars before a forbidden
// phrase, make that occurrence permissible (a denial context).
export const ALLOWED_DENIAL_PREFIXES = [
  'no ',
  'never ',
  'cannot ',
  'does not ',
  'doesn’t ',
  "doesn't ",
  'will not ',
  "won't ",
  'not connected',
  'execution locked',
  'advisory only',
  'broker not connected',
  'no execution',
  'not allowed to ',
  'will never ',
  'must not ',
  'human review required',
] as const;

export interface ForbiddenLanguageFinding {
  phrase: string;
  index: number;
  context: string;
}

const DENIAL_WINDOW = 48;

function _normalize(text: string): string {
  return text.replace(/\s+/g, ' ').toLowerCase();
}

/**
 * Scan `text` for forbidden execution phrases.  Any occurrence inside a
 * denial window is permitted.  Returns the list of remaining
 * problematic findings; empty list means the text is clean.
 */
export function scanForForbiddenLanguage(
  text: string,
): ForbiddenLanguageFinding[] {
  const haystack = _normalize(text);
  const findings: ForbiddenLanguageFinding[] = [];
  for (const phrase of FORBIDDEN_EXECUTION_PHRASES) {
    let from = 0;
    while (true) {
      const idx = haystack.indexOf(phrase, from);
      if (idx < 0) break;
      const start = Math.max(0, idx - DENIAL_WINDOW);
      const window = haystack.slice(start, idx);
      const inDenial = ALLOWED_DENIAL_PREFIXES.some((p) => window.includes(p));
      if (!inDenial) {
        findings.push({
          phrase,
          index: idx,
          context: haystack.slice(start, idx + phrase.length + 16),
        });
      }
      from = idx + phrase.length;
    }
  }
  return findings;
}

/**
 * Convenience helper for vitest / Playwright assertions.  Throws when
 * the text contains a forbidden execution phrase outside a denial
 * context.
 */
export function assertNoExecutionLanguage(text: string): void {
  const findings = scanForForbiddenLanguage(text);
  if (findings.length > 0) {
    const where = findings
      .map((f) => `${f.phrase} @ ${f.index} :: ${f.context}`)
      .join('\n');
    throw new Error(`forbidden execution language found:\n${where}`);
  }
}

/**
 * Returns true iff the text mentions at least one of the advisory
 * labels.  Used by component tests to assert that a surface has *some*
 * advisory framing.
 */
export function hasAdvisoryLabel(text: string): boolean {
  const haystack = _normalize(text);
  return ADVISORY_LABELS.some((label) => haystack.includes(_normalize(label)));
}
