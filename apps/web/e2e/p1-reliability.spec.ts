import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// All requests use disposable founder workspaces. The suite never contacts
// external providers, sends email, resets demo records, or downloads models.
const base = 'http://127.0.0.1:4173';

async function register(request: any, prefix: string) {
  const res = await request.post(base + '/api/auth/register', {
    data: {
      name: 'P1 Browser Founder',
      email: `${prefix}-${randomUUID()}@example.test`,
      password: 'TestPassword123!',
      business_name: 'P1 Disposable Workspace',
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  return res.json();
}

test('real workspace cannot access mock CRM, ledger or repository fixtures', async ({ request }) => {
  const founder = await register(request, 'p1-mock-isolation');
  const headers = { Authorization: `Bearer ${founder.token}` };
  for (const path of [
    '/api/integrations/crm/contacts',
    '/api/integrations/finance/ledger',
    '/api/integrations/github/status',
  ]) {
    const result = await request.get(base + path, { headers });
    expect(result.status(), path + ': ' + (await result.text())).toBe(404);
  }
  const outbox = await request.get(base + '/api/integrations/email/outbox', { headers });
  expect(outbox.status()).toBe(200);
  const body = await outbox.json();
  expect(body.is_simulated).toBe(true);
  expect(body.outbox).toEqual([]);
});

test('server model readiness is scoped to the workspace selected profile', async ({ request }) => {
  const founder = await register(request, 'p1-model-status');
  const headers = { Authorization: `Bearer ${founder.token}` };
  const response = await request.get(base + '/api/ai/status', { headers });
  expect(response.status(), await response.text()).toBe(200);
  const health = await response.json();
  expect(health.requested_model).toBe('qwen2.5:7b');
  expect(health.requested_model_installed).toBe(
    health.status === 'connected' &&
    health.available_models.includes('qwen2.5:7b')
  );
  expect(health.inference_available).toBe(health.requested_model_installed);
});

test('repeating an uncertain workflow request key does not execute twice', async ({ request }) => {
  const founder = await register(request, 'p1-idempotency');
  const headers = { Authorization: `Bearer ${founder.token}` };
  const creation = await request.post(base + '/api/workflows', {
    headers,
    data: {
      name: 'P1 Synthetic Idempotency',
      nodes: [{ id: 'trigger', type: 'trigger', data: { label: 'Synthetic' } }],
      edges: [],
    },
  });
  expect(creation.status(), await creation.text()).toBe(200);
  const workflow = await creation.json();
  const key = 'browser_replay_' + randomUUID();
  const execute = async () => request.post(base + `/api/workflows/${workflow.id}/execute`, {
    headers: { ...headers, 'Idempotency-Key': key },
  });
  const first = await execute();
  expect(first.status(), await first.text()).toBe(200);
  const initial = await first.json();
  const second = await execute();
  expect(second.status(), await second.text()).toBe(200);
  const replay = await second.json();
  expect(replay.id).toBe(initial.id);
  expect(replay.status).toBe(initial.status);
  const runs = await request.get(base + '/api/workflows/runs', { headers });
  expect(runs.status()).toBe(200);
  expect((await runs.json()).filter((run: { id: string }) => run.id === initial.id)).toHaveLength(1);
});

test('integrations screen has empty chat importer and honest sandbox messaging', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await expect(page.getByText('Founder Login')).toBeVisible();
  await page.getByRole('button', { name: /Register/ }).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('P1 UI Founder');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('P1 UI Workspace');
  await page.getByPlaceholder('founder@example.com').fill(`p1-ui-${randomUUID()}@example.test`);
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Create Workspace & Sign In' }).click();
  await expect(page.getByText('P1 UI Founder')).toBeVisible();
  const sidebar = page.getByRole('complementary');
  await sidebar.locator('nav button').filter({
    has: page.locator('span').getByText('Integrations', { exact: true }),
  }).click();
  await expect(page.getByText('Integration Sandbox & Connector Readiness')).toBeVisible();
  await expect(page.locator('textarea')).toHaveValue('');
  await expect(page.getByText('No sandbox messages recorded. This adapter does not deliver emails.')).toBeVisible();
});
