import { defineConfig } from '@playwright/test';

// Requer API (porta 8000) e frontend (porta 3000) rodando com o seed demo. Veja README > Testes E2E.
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH, args: ['--no-sandbox'] } : {},
    locale: 'pt-BR',
    timezoneId: 'America/Fortaleza',
  },
});
