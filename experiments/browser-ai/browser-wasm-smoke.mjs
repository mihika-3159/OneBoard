// Actual Chromium execution of a small quantized LLM, no vendor inference API.
import { createServer } from 'vite';
import { chromium } from 'playwright';
const server = await createServer({ root: process.cwd(), server: { host: '127.0.0.1', port: 4311, strictPort: true } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:4311/inference.html');
  await page.waitForFunction(() => window.__inference && window.__inference.status !== 'loading', null, { timeout: 12 * 60 * 1000 });
  const result = await page.evaluate(() => window.__inference);
  console.log(JSON.stringify({ stage: 'browser_wasm_inference', ...result, js_errors: errors }));
  if (result.status !== 'passed' || errors.length) throw new Error('Real browser CPU inference failed');
} finally {
  if (browser) await browser.close();
  await server.close();
}