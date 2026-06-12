// THROWAWAY sandbox config: drives the pre-provisioned chromium binary
// because cdn.playwright.dev is egress-blocked here. Not used by CI.
import { defineConfig } from '@playwright/test';
import base from './playwright.config';

export default defineConfig({
  ...base,
  projects: [{
    name: 'chromium-sandbox',
    use: {
      launchOptions: { executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' },
    },
  }],
});
