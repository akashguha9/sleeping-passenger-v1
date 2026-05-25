/**
 * Pure helpers extracted from frontend/src/app/live-signals/page.tsx
 * during the Identity Collapse sprint (Phase 10).
 *
 * Behaviour preserved verbatim — these are presentational utilities, not
 * data-fetching code.  Tests in src/app/__tests__/live-signals.*.spec.tsx
 * exercise them via the page component; this module's API surface stays
 * compatible.
 */
import type { LiveSignalEvent, LiveSignalSource } from '@/types';

export const SOURCE_OPTIONS: { value: '' | LiveSignalSource; label: string }[] = [
  { value: '', label: 'All Sources' },
  { value: 'polymarket', label: 'Polymarket' },
  { value: 'kalshi', label: 'Kalshi' },
  { value: 'prediction_market_disagreement', label: 'Disagreements' },
  { value: 'gdelt', label: 'GDELT' },
  { value: 'sec_edgar', label: 'SEC EDGAR' },
  { value: 'newsapi', label: 'NewsAPI' },
  { value: 'event_registry', label: 'Event Registry' },
  { value: 'etherscan', label: 'Etherscan' },
  { value: 'grok_xai', label: 'Grok/xAI' },
  { value: 'market_data', label: 'Market Data' },
  { value: 'india', label: 'India' },
  { value: 'global_filings', label: 'Global Filings' },
  { value: 'asia_disclosure', label: 'Asia Disclosure' },
];

export const SOURCE_ACCENT: Record<string, string> = {
  polymarket: 'rgba(167, 139, 250, 0.9)',
  kalshi: 'rgba(142, 196, 168, 0.9)',
  prediction_market_disagreement: 'rgba(214, 168, 90, 0.9)',
  gdelt: 'rgba(125, 211, 252, 0.9)',
  sec_edgar: 'rgba(200, 154, 74, 0.9)',
  newsapi: 'rgba(95, 189, 200, 0.9)',
  event_registry: 'rgba(110, 200, 196, 0.9)',
  etherscan: 'rgba(217, 119, 87, 0.9)',
  grok_xai: 'rgba(165, 158, 230, 0.9)',
  market_data: 'rgba(122, 175, 232, 0.9)',
  india: 'rgba(216, 168, 96, 0.9)',
  global_filings: 'rgba(214, 142, 158, 0.9)',
  asia_disclosure: 'rgba(213, 123, 106, 0.9)',
};

export const SOURCE_LABELS: Record<string, string> = {
  polymarket: 'Polymarket',
  kalshi: 'Kalshi',
  prediction_market_disagreement: 'Prediction Market Disagreement',
  gdelt: 'GDELT',
  sec_edgar: 'SEC EDGAR',
  newsapi: 'NewsAPI',
  event_registry: 'Event Registry',
  etherscan: 'Etherscan',
  grok_xai: 'Grok/xAI',
  market_data: 'Market Data',
  india: 'India (NSE/RBI/SEBI)',
  global_filings: 'Global Filings',
  asia_disclosure: 'Asia Disclosure',
};

export const KALSHI_DISPLAY_LABEL_BY_SLUG: Record<string, string> = {
  elections: 'Elections',
  politics: 'Politics',
  crypto: 'Crypto',
  commodities: 'Commodities',
  economics: 'Economics',
  finance: 'Finance',
  tech_science: 'Tech & Science',
};

export const KALSHI_FRESHNESS_LABEL: Record<string, string> = {
  LIVE_VERIFIED: 'Source · LIVE_VERIFIED',
  SOURCE_STALE: 'Source · SOURCE_STALE',
  UNVERIFIED: 'Source · UNVERIFIED',
  SOURCE_ERROR: 'Source · SOURCE_ERROR',
};

export const KALSHI_ACTIVITY_LABEL: Record<string, string> = {
  MARKET_OPEN: 'Market · OPEN',
  MARKET_CLOSED: 'Market · CLOSED',
  MARKET_EXPIRED: 'Market · EXPIRED',
  MARKET_UNKNOWN: 'Market · UNKNOWN',
};

export function getTitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (ev.source_name === 'prediction_market_disagreement') {
    return (p.customer_label as string) || 'Prediction Market Disagreement Alert';
  }
  if (ev.source_name === 'kalshi') {
    return (
      (p.display_title as string) ||
      (p.primary_title as string) ||
      (p.title as string) ||
      ev.event_id
    );
  }
  return p.title || (p.question as string) || ev.event_id;
}

export function isKalshiQuarantined(ev: LiveSignalEvent): boolean {
  if (ev.source_name !== 'kalshi') return false;
  const p = ev.raw_payload;
  if (p.visible_in_kalshi_feed === false) return true;
  if (p.category_allowed === false) return true;
  return false;
}

export function kalshiDisplayCategory(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (typeof p.display_category === 'string' && p.display_category.trim()) {
    return p.display_category;
  }
  if (typeof p.mvp_category === 'string' && KALSHI_DISPLAY_LABEL_BY_SLUG[p.mvp_category]) {
    return KALSHI_DISPLAY_LABEL_BY_SLUG[p.mvp_category];
  }
  return String(p.category || '');
}

export function getSubtitle(ev: LiveSignalEvent): string {
  const p = ev.raw_payload;
  if (ev.source_name === 'polymarket') {
    const parts: string[] = [];
    if (p.market_id) parts.push(`Market ${p.market_id}`);
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.liquidity != null) parts.push(`Liq: ${Number(p.liquidity).toLocaleString()}`);
    if (p.end_date) parts.push(`Ends: ${p.end_date}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'prediction_market_disagreement') {
    const parts: string[] = [];
    if (p.pair_type) parts.push(String(p.pair_type));
    if (p.probability_gap != null) {
      parts.push(`Gap: ${(Number(p.probability_gap) * 100).toFixed(1)} percentage points`);
    }
    if (p.status) parts.push(`Status: ${String(p.status)}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'kalshi') {
    const parts: string[] = [];
    const cat = kalshiDisplayCategory(ev);
    if (cat) parts.push(cat.toUpperCase());
    if (p.source_market_id) parts.push(`Market ${p.source_market_id}`);
    if (p.implied_probability != null) {
      parts.push(`Implied: ${(Number(p.implied_probability) * 100).toFixed(1)}%`);
    } else if (p.yes_price != null) {
      parts.push(`YES: ${Number(p.yes_price).toFixed(2)}`);
    }
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.open_interest != null) parts.push(`OI: ${Number(p.open_interest).toLocaleString()}`);
    if (p.close_time_utc) parts.push(`Closes: ${p.close_time_utc}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'gdelt') {
    const parts: string[] = [];
    if (p.domain) parts.push(p.domain as string);
    if (p.sourcecountry) parts.push(p.sourcecountry as string);
    if (p.seendate) parts.push(`Seen: ${p.seendate}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'sec_edgar') {
    const parts: string[] = [];
    if (p.form_type) parts.push(p.form_type as string);
    if (p.cik) parts.push(`CIK ${p.cik}`);
    if (p.filing_date) parts.push(`Filed: ${p.filing_date}`);
    if (p.accession_number) parts.push(p.accession_number as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'newsapi') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.published_at) parts.push(`Published: ${p.published_at}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'event_registry') {
    const parts: string[] = [];
    if (p.publisher) parts.push(p.publisher as string);
    if (p.date_time) parts.push(`Date: ${p.date_time}`);
    if (p.url) parts.push(p.url as string);
    return parts.join(' · ');
  }
  if (ev.source_name === 'etherscan') {
    const parts: string[] = [];
    if (p.hash) parts.push(`Hash: ${(p.hash as string).slice(0, 14)}…`);
    if (p.from_address) parts.push(`From: ${(p.from_address as string).slice(0, 10)}…`);
    if (p.to_address) parts.push(`To: ${(p.to_address as string).slice(0, 10)}…`);
    if (p.block_number) parts.push(`Block: ${p.block_number}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'grok_xai') {
    const parts: string[] = [];
    if (p.narrative_frame) parts.push(`Frame: ${p.narrative_frame as string}`);
    if (p.confidence_score != null) parts.push(`Confidence: ${Number(p.confidence_score).toFixed(2)}`);
    if (p.model_name) parts.push(`Model: ${p.model_name as string}`);
    if (p.created_at) parts.push(`At: ${p.created_at as string}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'market_data') {
    const parts: string[] = [];
    if (p.symbol) parts.push(String(p.symbol));
    if (p.latest_price != null) parts.push(`$${Number(p.latest_price).toFixed(2)}`);
    if (p.price_change_pct != null) {
      const pct = Number(p.price_change_pct);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.volume != null) parts.push(`Vol: ${Number(p.volume).toLocaleString()}`);
    if (p.market_confirmation_score != null) parts.push(`Score: ${Number(p.market_confirmation_score).toFixed(2)}`);
    if (p.provider) parts.push(`(${p.provider as string})`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'india') {
    const parts: string[] = [];
    if (p.regulatory_source) parts.push(String(p.regulatory_source).toUpperCase());
    if (p.index_name) parts.push(String(p.index_name));
    if (p.last_price != null) parts.push(`₹${Number(p.last_price).toLocaleString()}`);
    if (p.percent_change != null) {
      const pct = Number(p.percent_change);
      parts.push(`${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`);
    }
    if (p.regulatory_note) parts.push(String(p.regulatory_note));
    return parts.join(' · ');
  }
  if (ev.source_name === 'global_filings') {
    const parts: string[] = [];
    if (p.jurisdiction) parts.push(String(p.jurisdiction));
    if (p.exchange_or_regulator) parts.push(String(p.exchange_or_regulator));
    if (p.disclosure_type) parts.push(String(p.disclosure_type).replace(/_/g, ' '));
    if (p.issuer_name) parts.push(String(p.issuer_name));
    if (p.ticker_or_identifier) parts.push(`[${String(p.ticker_or_identifier)}]`);
    if (p.published_at) parts.push(`Filed: ${String(p.published_at)}`);
    return parts.join(' · ');
  }
  if (ev.source_name === 'asia_disclosure') {
    const parts: string[] = [];
    if (p.jurisdiction) parts.push(String(p.jurisdiction));
    if (p.exchange_or_regulator) parts.push(String(p.exchange_or_regulator));
    if (p.disclosure_type) parts.push(String(p.disclosure_type).replace(/_/g, ' '));
    if (p.issuer_name) parts.push(String(p.issuer_name));
    if (p.ticker_or_identifier) parts.push(`[${String(p.ticker_or_identifier)}]`);
    if (p.published_at) parts.push(`Filed: ${String(p.published_at)}`);
    if (p.language) parts.push(`Lang: ${String(p.language)}`);
    return parts.join(' · ');
  }
  return ev.event_id;
}

export function matchesSearch(ev: LiveSignalEvent, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const p = ev.raw_payload;
  return [
    ev.event_id,
    ev.source_name,
    p.title,
    p.market_id,
    p.domain,
    p.cik,
    p.form_type,
    p.accession_number,
    p.sourcecountry,
    p.language,
    p.publisher,
    p.description,
    p.url,
    p.body,
    p.date_time,
    p.hash,
    p.from_address,
    p.to_address,
    p.block_number,
    p.interpreted_topic,
    p.narrative_frame,
    p.summary_text,
    p.source_prompt,
    p.model_name,
    p.symbol,
    p.provider,
    p.period,
    p.interval,
    p.index_name,
    p.regulatory_source,
    p.regulatory_url,
    p.regulatory_note,
    p.issuer_name,
    p.ticker_or_identifier,
    p.jurisdiction,
    p.exchange_or_regulator,
    p.disclosure_type,
    p.summary,
    // kalshi-specific fields
    p.category,
    p.source_label,
    p.source_market_id,
    p.market_url,
    p.semantic_text,
    ...((p.asset_tags as string[] | undefined) ?? []),
    ...((p.event_tags as string[] | undefined) ?? []),
  ]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(q));
}

export function formatTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts;
  }
}
