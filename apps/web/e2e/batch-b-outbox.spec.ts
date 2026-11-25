import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

test('local workflow draft is durable and invisible to another browser tenant', async ({ browser }) => {
  const a = await browser.newContext();
  const b = await browser.newContext();
  const base = 'http://127.0.0.1:4173';
  const register = async (ctx: typeof a, label: string) => {
    const res = await ctx.request.post(base + '/api/auth/register', { data: {
      name: label, business_name: label, email: randomUUID() + '@example.test',
      password: 'TestPassword123!'
    } });
    expect(res.status()).toBe(201);
    const body = await res.json();
    return { Authorization: 'Bearer ' + body.token };
  };
  try {
    const ha = await register(a, 'Draft owner');
    const hb = await register(b, 'Other workspace');
    const created = await a.request.post(base + '/api/workflows', { headers: ha, data: {
      name: 'Local draft only', nodes: [
        { id: 'start', type: 'trigger', data: {} },
        { id: 'draft', type: 'action', data: { connector: 'demo_email', operation: 'draft_invoice_reminders' } }
      ], edges: [{ source: 'start', target: 'draft' }]
    } });
    expect(created.status()).toBe(200);
    const workflow = await created.json();
    const executed = await a.request.post(base + '/api/workflows/' + workflow.id + '/execute', {
      headers: { ...ha, 'Idempotency-Key': randomUUID() }
    });
    expect(executed.status(), await executed.text()).toBe(200);
    const run = await executed.json();
    expect(run.status).toBe('completed');
    const owner = await a.request.get(base + '/api/workflows/outbox', { headers: ha });
    expect(owner.status()).toBe(200);
    const rows = await owner.json();
    expect(rows).toHaveLength(1);
    expect(rows[0].run_id).toBe(run.id);
    expect(rows[0].delivered).toBe(false);
    const stranger = await b.request.get(base + '/api/workflows/outbox', { headers: hb });
    expect(stranger.status()).toBe(200);
    expect(await stranger.json()).toEqual([]);
  } finally { await a.close(); await b.close(); }
});
