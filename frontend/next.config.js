/** @type {import('next').NextConfig} */

// S8 fix: defense-in-depth security headers on the Next surface.
// Token lives in sessionStorage (intentional — see LocalApiTokenPanel.tsx);
// these headers eliminate the realistic XSS exfil paths.
//
// connect-src is widened to include the backend API base so fetch()
// calls from the bundle still work.  Defaults to localhost:8000 when
// NEXT_PUBLIC_API_BASE_URL is unset (matches lib/config.ts).
const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000';

const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  // Tailwind injects styles via <style> tags in dev; 'unsafe-inline' is
  // required for that.  Acceptable trade-off — we have no third-party
  // script load surface.
  "style-src 'self' 'unsafe-inline'",
  // Next.js App Router bootstraps hydration through inline <script>
  // tags; a bare script-src 'self' blocks them and the entire client
  // becomes static HTML (no hydration, no fetches - the cockpit never
  // loads data). Caught by the Playwright e2e suite the day it entered
  // CI. 'unsafe-inline' is required until a nonce-based CSP middleware
  // is added; third-party script ORIGINS remain blocked, and exfil is
  // still constrained by the pinned connect-src below.
  "script-src 'self' 'unsafe-inline'",
  `connect-src 'self' ${apiBase}`,
].join('; ');

const securityHeaders = [
  { key: 'Content-Security-Policy', value: csp },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'no-referrer' },
  {
    key: 'Permissions-Policy',
    value:
      'accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()',
  },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
  { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
];

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: securityHeaders,
      },
    ];
  },
};

module.exports = nextConfig;
