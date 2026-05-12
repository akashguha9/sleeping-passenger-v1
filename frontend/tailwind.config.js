/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Obsidian / midnight-navy base — deeper, warmer than default slate.
        // Tuned to read as a dark studio / meditative control room rather than
        // a generic dark-mode dashboard. Existing `slate-*` utility usages keep
        // working but render in the new tonal range.
        slate: {
          50: '#f4f4f3',
          100: '#e8e7e3',
          200: '#cfcec8',
          300: '#9a9b97',
          400: '#6f7378',
          500: '#52575d',
          600: '#363a40',
          700: '#23272d',
          800: '#181b21',
          850: '#13161b',
          900: '#0d1015',
          925: '#090b10',
          950: '#06080b',
        },
        // SleepingPassenger accent palette.
        sp: {
          obsidian: '#06080b',
          ink: '#0d1015',
          slate: '#181b21',
          bone: '#e8e7e3',
          mist: '#9a9b97',
          gold: '#c89a4a',       // warm amber/gold — primary accent
          'gold-deep': '#8a6824',
          ember: '#d97757',      // softer warm highlight
          cyan: '#5fbdc8',       // restrained cool teal/cyan — secondary accent
          'cyan-deep': '#28707a',
          rust: '#a04a3a',       // muted danger
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          'Segoe UI',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'monospace',
        ],
      },
      letterSpacing: {
        widest: '.18em',
      },
      boxShadow: {
        'sp-glow': '0 0 0 1px rgba(200,154,74,0.08), 0 8px 32px -16px rgba(200,154,74,0.18)',
        'sp-card': '0 1px 0 0 rgba(255,255,255,0.02) inset, 0 8px 24px -16px rgba(0,0,0,0.7)',
      },
    },
  },
  plugins: [],
}
