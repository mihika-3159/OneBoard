import { defineConfig, devices } from '@playwright/test';
export default defineConfig({
  testDir: './e2e',
  timeout: 30000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: 'python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000', url: 'http://127.0.0.1:8000/health', cwd: '../..', reuseExistingServer: !process.env.CI, timeout: 120000 },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4173', url: 'http://127.0.0.1:4173', reuseExistingServer: !process.env.CI, timeout: 120000 }
  ]
});
