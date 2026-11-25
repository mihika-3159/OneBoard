import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// Real disposable local founder, not seeded Northstar demo or production data.
test('new real workspace Operations tab displays zero records, not fictional customers', async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto('/');
  await expect(page.getByText('Founder Login')).toBeVisible();
  await page.getByRole('button', { name: /Register/ }).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('Batch A Founder');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('No Demo Data Business');
  await page.getByPlaceholder('founder@example.com').fill('batch-a-' + randomUUID() + '@example.test');
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Create Workspace & Sign In' }).click();
  await expect(page.getByText('Batch A Founder')).toBeVisible();

  const nav = page.getByRole('complementary').locator('nav button');
  await nav.filter({ has: page.locator('span').getByText('Operations', { exact: true }) }).click();
  await expect(page.getByRole('heading', { name: 'Operations & Customer Deliverables' })).toBeVisible();
  await expect(page.getByText('No customer commitments recorded in this workspace.')).toBeVisible();
  await page.getByRole('tab', { name: 'Customers (0)' }).click();
  await expect(page.getByText('No customer records yet. Import a CSV in Integrations.')).toBeVisible();
  await page.getByRole('tab', { name: 'Sales Pipeline (0)' }).click();
  await expect(page.getByText('No sales leads recorded yet.')).toBeVisible();
  await expect(page.getByText('Custom Webhook Exporter Delivery')).toHaveCount(0);
  await expect(page.getByText('Kavita Rao')).toHaveCount(0);
  await expect(page.getByText('Active Customers (38)')).toHaveCount(0);
});
