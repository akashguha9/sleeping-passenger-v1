import { describe, expect, it } from 'vitest';
import {
  ADVISORY_ONLY_LABEL,
  EXECUTION_LOCKED_LABEL,
  assertNoExecutionLanguage,
  hasAdvisoryLabel,
  scanForForbiddenLanguage,
} from '../advisoryTruth';

describe('advisoryTruth: scanForForbiddenLanguage', () => {
  it('returns empty for clean copy', () => {
    expect(scanForForbiddenLanguage('Advisory only. No execution.')).toEqual(
      [],
    );
  });

  it('flags positive execution verbs', () => {
    const findings = scanForForbiddenLanguage('Tap to place order now.');
    expect(findings.length).toBeGreaterThan(0);
    expect(findings[0].phrase).toBe('place order');
  });

  it('allows execution phrase inside a denial context', () => {
    expect(
      scanForForbiddenLanguage('Advisory only — cannot place order.'),
    ).toEqual([]);
    expect(
      scanForForbiddenLanguage('Broker not connected, we never place order.'),
    ).toEqual([]);
  });

  it('catches autotrade, auto execute, and ai executed', () => {
    expect(
      scanForForbiddenLanguage('Autotrade enabled for premium users.').length,
    ).toBeGreaterThan(0);
    expect(
      scanForForbiddenLanguage('The bot will auto execute the trade.').length,
    ).toBeGreaterThan(0);
    expect(
      scanForForbiddenLanguage('AI executed your order at 09:35.').length,
    ).toBeGreaterThan(0);
  });

  it('does not flag the words inside a long denial sentence', () => {
    expect(
      scanForForbiddenLanguage(
        'Advisory only. The system will never place order or auto execute on your behalf.',
      ),
    ).toEqual([]);
  });
});

describe('advisoryTruth: assertNoExecutionLanguage', () => {
  it('throws on a positive execution phrase', () => {
    expect(() => assertNoExecutionLanguage('Place order now.')).toThrow();
  });

  it('does not throw on clean advisory copy', () => {
    expect(() =>
      assertNoExecutionLanguage(
        `${ADVISORY_ONLY_LABEL}. ${EXECUTION_LOCKED_LABEL}.`,
      ),
    ).not.toThrow();
  });
});

describe('advisoryTruth: hasAdvisoryLabel', () => {
  it('detects any of the canonical labels', () => {
    expect(hasAdvisoryLabel('Footer: Advisory only.')).toBe(true);
    expect(hasAdvisoryLabel('No execution path exists.')).toBe(true);
    expect(hasAdvisoryLabel('Broker API: not connected')).toBe(true);
  });

  it('returns false when no label is present', () => {
    expect(hasAdvisoryLabel('hello world')).toBe(false);
  });
});
