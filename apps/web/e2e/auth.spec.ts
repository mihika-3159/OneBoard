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
