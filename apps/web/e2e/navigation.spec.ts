import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

// A real browser journey through every sidebar view, using an isolated fresh founder.
// This deliberately avoids demo resets, outbound integrations, and real payments.
test('new founder can open all eleven navigation tabs without a fatal UI error', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByText('Founder Login')).toBeVisible();
  await page.getByRole('button', { name: /Register/ }).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('Navigation Tester');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('Navigation Test Workspace');
  await page.getByPlaceholder('founder@example.com').fill(`navigation-${randomUUID()}@example.test`);
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Create Workspace & Sign In' }).click();
  await expect(page.getByText('Navigation Tester')).toBeVisible();

  const tabs = [
    'Overview', 'Founder Command', 'Boardroom', 'Workflow Studio',
    'Agent Studio', 'Accountability', 'Business Memory', 'Operations & CRM',
    'Finance & Ledger', 'Integrations', 'Settings',
  ];
  const sidebar = page.getByRole('complementary');
  for (const label of tabs) {
    await sidebar.getByRole('button', { name: label, exact: true }).click();
    await expect(page.locator('header')).toContainText(label);
    await expect(page.locator('main')).toBeVisible();
    await page.screenshot({ path: `test-results/tab-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.png`, fullPage: false });
  }
  expect(errors).toEqual([]);
  await page.getByTitle('Log out and invalidate session').click();
  await expect(page.getByText('Founder Login')).toBeVisible();
});
