import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

test('founder registers, sees workspace, logs out and cannot reuse session', async ({ page, request }) => {
  const email = `e2e-${randomUUID()}@example.test`;
  await page.goto('/');
  await expect(page.getByText('Founder Login')).toBeVisible();
  await page.getByRole('button', { name: /Register/ }).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('CI Founder');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('CI Workspace');
  await page.getByPlaceholder('founder@example.com').fill(email);
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Create Workspace & Sign In' }).click();
  await expect(page.getByText('CI Founder')).toBeVisible();
  await expect(page.getByRole('complementary').getByText('CI Workspace')).toBeVisible();
  const me = await page.request.get('/api/auth/me');
  expect(me.status()).toBe(200);
  await page.getByTitle('Log out and invalidate session').click();
  await expect(page.getByText('Founder Login')).toBeVisible();
  expect((await page.request.get('/api/auth/me')).status()).toBe(401);
});

test('two registered founders cannot read each other business records', async ({ browser }) => {
  const a = await browser.newContext();
  const b = await browser.newContext();
  try {
    const register = async (ctx: typeof a, name: string) => {
      const response = await ctx.request.post('http://127.0.0.1:4173/api/auth/register', {
        data: { name, email: `e2e-${randomUUID()}@example.test`, password: 'TestPassword123!', business_name: name + ' Workspace' }
      });
      expect(response.status()).toBe(201);
      return response.json();
    };
    const userA = await register(a, 'Founder A');
    const userB = await register(b, 'Founder B');
    expect(userA.business.id).not.toBe(userB.business.id);
    const aMe = await a.request.get('http://127.0.0.1:4173/api/auth/me');
    const bMe = await b.request.get('http://127.0.0.1:4173/api/auth/me');
    expect((await aMe.json()).business.id).toBe(userA.business.id);
    expect((await bMe.json()).business.id).toBe(userB.business.id);
    const aBusiness = await a.request.get('http://127.0.0.1:4173/api/business');
    const bBusiness = await b.request.get('http://127.0.0.1:4173/api/business');
    expect(aBusiness.ok()).toBeTruthy();
    expect(bBusiness.ok()).toBeTruthy();
    expect((await aBusiness.json()).id).toBe(userA.business.id);
    expect((await bBusiness.json()).id).toBe(userB.business.id);
  } finally { await a.close(); await b.close(); }
});


test('tenant B cannot execute tenant A workflow or see its definition', async ({ browser }) => {
  const a = await browser.newContext();
  const b = await browser.newContext();
  const base = 'http://127.0.0.1:4173';
  try {
    const register = async (ctx: typeof a, label: string) => {
      const res = await ctx.request.post(base + '/api/auth/register', {
        data: { name: label, email: `e2e-${randomUUID()}@example.test`, password: 'TestPassword123!', business_name: label }
      });
      expect(res.status()).toBe(201);
      return res.json();
    };
    const userA = await register(a, 'Workflow Owner');
    const userB = await register(b, 'Other Tenant');
    const headersA = { Authorization: `Bearer ${userA.token}` };
    const headersB = { Authorization: `Bearer ${userB.token}` };
    const created = await a.request.post(base + '/api/workflows', {
      headers: headersA,
      data: { name: 'Tenant A private workflow', nodes: [{ id: 'start', type: 'trigger', data: { label: 'Start' } }], edges: [] }
    });
    expect(created.status(), await created.text()).toBe(200);
    const workflow = await created.json();
    expect(workflow.business_id).toBe(userA.business.id);
    const listB = await b.request.get(base + '/api/workflows', { headers: headersB });
    expect(listB.status()).toBe(200);
    expect((await listB.json()).some((w: { id: string }) => w.id === workflow.id)).toBe(false);
    const forbidden = await b.request.post(base + `/api/workflows/${workflow.id}/execute?dry_run=true`, {
      headers: headersB
    });
    expect(forbidden.status()).toBe(403);
    const listA = await a.request.get(base + '/api/workflows', { headers: headersA });
    expect((await listA.json()).some((w: { id: string }) => w.id === workflow.id)).toBe(true);
  } finally {
    await a.close();
    await b.close();
  }
});


test('founder workflow dry-run is simulated and approval rejection prevents downstream execution', async ({ browser }) => {
  const ctx = await browser.newContext();
  const base = 'http://127.0.0.1:4173';
  try {
    const registered = await ctx.request.post(base + '/api/auth/register', {
      data: {
        name: 'Workflow Safety Tester',
        email: `workflow-safety-${randomUUID()}@example.test`,
        password: 'TestPassword123!',
        business_name: 'Workflow Safety Test Workspace',
      },
    });
    expect(registered.status(), await registered.text()).toBe(201);
    const founder = await registered.json();
    const headers = { Authorization: `Bearer ${founder.token}` };
    const created = await ctx.request.post(base + '/api/workflows', {
      headers,
      data: {
        name: 'Approval gate regression',
        nodes: [
          { id: 'after', type: 'calculate', data: { label: 'After approval', connector: 'demo_finance' } },
          { id: 'gate', type: 'approval', data: { label: 'Founder must approve' } },
          { id: 'start', type: 'trigger', data: { label: 'Start' } },
        ],
        edges: [{ source: 'start', target: 'gate' }, { source: 'gate', target: 'after' }],
      },
    });
    expect(created.status(), await created.text()).toBe(200);
    const workflow = await created.json();

    const simulated = await ctx.request.post(base + `/api/workflows/${workflow.id}/execute?dry_run=true`, { headers });
    expect(simulated.status(), await simulated.text()).toBe(200);
    const dryRun = await simulated.json();
    expect(dryRun.status).toBe('completed');
    expect(dryRun.verification_details.dry_run).toBe(true);
    expect(dryRun.verification_details.node_order).toEqual(['start', 'gate', 'after']);
    expect(dryRun.verified_success).toBe(false);
    expect(dryRun.step_results.gate.status).toBe('simulated');
    expect(dryRun.step_results.after.status).toBe('simulated');
    expect((await (await ctx.request.get(base + '/api/workflows/approvals', { headers })).json())).toHaveLength(0);

    const started = await ctx.request.post(base + `/api/workflows/${workflow.id}/execute`, { headers });
    expect(started.status(), await started.text()).toBe(200);
    const run = await started.json();
    expect(run.status).toBe('awaiting_approval');
    expect(run.step_results.after).toBeUndefined();
    const approvals = await (await ctx.request.get(base + '/api/workflows/approvals', { headers })).json();
    expect(approvals).toHaveLength(1);
    const rejected = await ctx.request.post(base + `/api/workflows/approvals/${approvals[0].id}/action`, {
      headers,
      data: { action: 'reject', notes: 'Automated isolated safety test' },
    });
    expect(rejected.status(), await rejected.text()).toBe(200);
    expect((await rejected.json()).status).toBe('rejected');
    const runs = await (await ctx.request.get(base + '/api/workflows/runs', { headers })).json();
    const stopped = runs.find((item: { id: string }) => item.id === run.id);
    expect(stopped.status).toBe('failed');
    expect(stopped.step_results.after).toBeUndefined();
    const replay = await ctx.request.post(base + `/api/workflows/approvals/${approvals[0].id}/action`, {
      headers,
      data: { action: 'approve' },
    });
    expect(replay.status()).toBe(409);
  } finally {
    await ctx.close();
  }
});


test('routine auth responses never expose persistent API keys', async ({ browser }) => {
  const ctx = await browser.newContext();
  const base = 'http://127.0.0.1:4173';
  const email = `secret-redaction-${randomUUID()}@example.test`;
  try {
    const registered = await ctx.request.post(base + '/api/auth/register', {
      data: { name: 'Secret Redaction', email, password: 'TestPassword123!', business_name: 'Secret Redaction Workspace' },
    });
    expect(registered.status(), await registered.text()).toBe(201);
    const registration = await registered.json();
    expect(registration.user).not.toHaveProperty('api_key');
    const headers = { Authorization: `Bearer ${registration.token}` };
    const me = await ctx.request.get(base + '/api/auth/me', { headers });
    expect(me.status()).toBe(200);
    expect((await me.json()).user).not.toHaveProperty('api_key');

    const login = await ctx.request.post(base + '/api/auth/login', {
      data: { email, password: 'TestPassword123!' },
    });
    expect(login.status(), await login.text()).toBe(200);
    expect((await login.json()).user).not.toHaveProperty('api_key');

    // The explicit key rotation endpoint remains the only intentional reveal.
    const rotation = await ctx.request.post(base + '/api/auth/regenerate-api-key', { headers });
    expect(rotation.status(), await rotation.text()).toBe(200);
    expect((await rotation.json()).api_key).toMatch(/^obk_[a-f0-9]+$/);
  } finally {
    await ctx.close();
  }
});


test('founder approval resumes only the remaining DAG steps and cannot be replayed', async ({ browser }) => {
  const ctx = await browser.newContext();
  const base = 'http://127.0.0.1:4173';
  try {
    const registration = await ctx.request.post(base + '/api/auth/register', {
      data: {
        name: 'Approval Resume Tester',
        email: `approval-resume-${randomUUID()}@example.test`,
        password: 'TestPassword123!',
        business_name: 'Approval Resume Workspace',
      },
    });
    expect(registration.status(), await registration.text()).toBe(201);
    const founder = await registration.json();
    const headers = { Authorization: `Bearer ${founder.token}` };
    const creation = await ctx.request.post(base + '/api/workflows', {
      headers,
      data: {
        name: 'Resumable founder approval',
        nodes: [
          { id: 'after', type: 'calculate', data: { label: 'Calculate overdue totals', connector: 'demo_finance' } },
          { id: 'gate', type: 'approval', data: { label: 'Founder approval' } },
          { id: 'start', type: 'trigger', data: { label: 'Start' } },
        ],
        edges: [{ source: 'start', target: 'gate' }, { source: 'gate', target: 'after' }],
      },
    });
    expect(creation.status(), await creation.text()).toBe(200);
    const workflow = await creation.json();
    const start = await ctx.request.post(base + `/api/workflows/${workflow.id}/execute`, { headers });
    expect(start.status(), await start.text()).toBe(200);
    const pending = await start.json();
    expect(pending.status).toBe('awaiting_approval');
    expect(pending.step_results.start.status).toBe('success');
    expect(pending.step_results.after).toBeUndefined();

    const approvalsResponse = await ctx.request.get(base + '/api/workflows/approvals', { headers });
    expect(approvalsResponse.status()).toBe(200);
    const approvals = await approvalsResponse.json();
    expect(approvals).toHaveLength(1);
    const approvalId = approvals[0].id;
    const approved = await ctx.request.post(base + `/api/workflows/approvals/${approvalId}/action`, {
      headers,
      data: { action: 'approve' },
    });
    expect(approved.status(), await approved.text()).toBe(200);
    const result = await approved.json();
    expect(result.status).toBe('approved');
    expect(result.run.id).toBe(pending.id);
    expect(result.run.status).toBe('completed');
    expect(result.run.step_results.start.status).toBe('success');
    expect(result.run.step_results.gate.status).toBe('approved');
    expect(result.run.step_results.after.status).toBe('success');
    expect(result.run.verification_details.node_order).toEqual(['start', 'gate', 'after']);
    expect(result.run.verified_success).toBe(false);

    const replay = await ctx.request.post(base + `/api/workflows/approvals/${approvalId}/action`, {
      headers,
      data: { action: 'approve' },
    });
    expect(replay.status()).toBe(409);
    const runs = await (await ctx.request.get(base + '/api/workflows/runs', { headers })).json();
    expect(runs.filter((item: { id: string }) => item.id === pending.id)).toHaveLength(1);
    expect(runs.find((item: { id: string }) => item.id === pending.id).step_results.after.status).toBe('success');
  } finally {
    await ctx.close();
  }
});
