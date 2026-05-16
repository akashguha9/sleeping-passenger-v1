// Manual Trade Log native-currency catalogue.
//
// Single source of truth on the frontend.  Mirrors scripts/supported_currencies.py
// — a cross-side test in tests/test_manual_trade_currency.py and
// src/__tests__/supported-currencies.spec.ts asserts the two lists stay in
// sync.  Duplication is intentional so the dropdown renders without a
// blocking backend call on first paint.

export interface SupportedCurrency {
  code: string;
  name: string;
  countries: string[];
}

export const UNKNOWN_CURRENCY = 'UNKNOWN';

export const SUPPORTED_CURRENCIES: SupportedCurrency[] = [
  { code: 'USD', name: 'United States dollar', countries: ['United States'] },
  { code: 'CNY', name: 'Chinese yuan',         countries: ['China'] },
  {
    code: 'EUR',
    name: 'Euro',
    countries: [
      'Germany', 'France', 'Italy', 'Spain',
      'Netherlands', 'Ireland', 'Belgium', 'Austria',
    ],
  },
  { code: 'JPY', name: 'Japanese yen',         countries: ['Japan'] },
  { code: 'GBP', name: 'British pound',        countries: ['United Kingdom'] },
  { code: 'INR', name: 'Indian rupee',         countries: ['India'] },
  { code: 'RUB', name: 'Russian ruble',        countries: ['Russia'] },
  { code: 'BRL', name: 'Brazilian real',       countries: ['Brazil'] },
  { code: 'CAD', name: 'Canadian dollar',      countries: ['Canada'] },
  { code: 'AUD', name: 'Australian dollar',    countries: ['Australia'] },
  { code: 'MXN', name: 'Mexican peso',         countries: ['Mexico'] },
  { code: 'KRW', name: 'South Korean won',     countries: ['South Korea'] },
  { code: 'TRY', name: 'Turkish lira',         countries: ['Turkey'] },
  { code: 'IDR', name: 'Indonesian rupiah',    countries: ['Indonesia'] },
  { code: 'SAR', name: 'Saudi riyal',          countries: ['Saudi Arabia'] },
  { code: 'CHF', name: 'Swiss franc',          countries: ['Switzerland'] },
  { code: 'PLN', name: 'Polish zloty',         countries: ['Poland'] },
  { code: 'TWD', name: 'New Taiwan dollar',    countries: ['Taiwan'] },
  { code: 'SEK', name: 'Swedish krona',        countries: ['Sweden'] },
  { code: 'ILS', name: 'Israeli new shekel',   countries: ['Israel'] },
  { code: 'ARS', name: 'Argentine peso',       countries: ['Argentina'] },
  { code: 'SGD', name: 'Singapore dollar',     countries: ['Singapore'] },
  { code: 'AED', name: 'UAE dirham',           countries: ['United Arab Emirates'] },
];

export const SUPPORTED_CURRENCY_CODES: ReadonlySet<string> = new Set(
  SUPPORTED_CURRENCIES.map((c) => c.code),
);

// Suffix → currency suggestion.  Matches the chart-structure suffix
// map.  Used to *propose* a default on ticker entry; the operator
// must still confirm before submit.
const SYMBOL_SUFFIX_CURRENCY: Record<string, string> = {
  '.NS': 'INR', '.BO': 'INR',
  '.DE': 'EUR', '.PA': 'EUR', '.AS': 'EUR', '.MI': 'EUR',
  '.MC': 'EUR', '.BR': 'EUR', '.LS': 'EUR', '.HE': 'EUR',
  '.VI': 'EUR', '.IR': 'EUR', '.F': 'EUR', '.BE': 'EUR',
  '.HM': 'EUR', '.MU': 'EUR', '.SG': 'EUR',
  '.L': 'GBP', '.IL': 'GBP',
  '.TO': 'CAD', '.V': 'CAD',
  '.AX': 'AUD',
  '.T': 'JPY',
  '.KS': 'KRW', '.KQ': 'KRW',
  '.SW': 'CHF', '.ST': 'SEK',
  '.SS': 'CNY', '.SZ': 'CNY',
  '.TW': 'TWD', '.TWO': 'TWD',
  '.SI': 'SGD',
  '.JK': 'IDR',
  '.MX': 'MXN', '.SA': 'BRL', '.BA': 'ARS',
  '.TA': 'ILS',
};

export function suggestCurrencyForSymbol(symbol: string | null | undefined): string | null {
  if (!symbol) return null;
  const sym = symbol.trim().toUpperCase();
  if (!sym) return null;
  for (const [suffix, currency] of Object.entries(SYMBOL_SUFFIX_CURRENCY)) {
    if (sym.endsWith(suffix)) {
      return SUPPORTED_CURRENCY_CODES.has(currency) ? currency : null;
    }
  }
  if (sym.includes('-')) {
    const parts = sym.split('-');
    if (parts.length === 2 && parts[1].length === 3 && /^[A-Z]+$/.test(parts[1])) {
      return SUPPORTED_CURRENCY_CODES.has(parts[1]) ? parts[1] : null;
    }
  }
  if (!sym.includes('.') && !sym.includes('-')) {
    return 'USD';
  }
  return null;
}

export function formatCurrencyLabel(c: SupportedCurrency): string {
  const countryStr = c.countries.length > 1
    ? c.countries.join(' / ')
    : c.countries[0];
  return `${c.code} — ${c.name} — ${countryStr}`;
}
