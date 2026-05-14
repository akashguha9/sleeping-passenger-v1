import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

/**
 * Vitest configuration for the local-advisory frontend.
 *
 * Scope: unit + lightweight component tests using jsdom + React Testing
 * Library. This is NOT an end-to-end runner — no Playwright, no browser
 * launch — keeping the dev dependency footprint small.
 *
 * The runner picks up the three committed spec files under
 *   src/components/__tests__/ and src/lib/__tests__/
 * and intentionally stops there. Adding more is opt-in.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/__tests__/**/*.spec.{ts,tsx}'],
    css: false,
  },
});
