import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
test('external integrations remain disabled without operator configuration',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:/Register/}).click();
 await page.getByPlaceholder('e.g. Alex Founder').fill('Batch L Founder');
 await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('Batch L Workspace');
 await page.getByPlaceholder('founder@example.com').fill(randomUUID()+'@example.test');
 await page.locator('input[type=password]').fill('TestPassword123!');
 await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
 await expect(page.getByText('Batch L Founder')).toBeVisible();
 await page.getByRole('complementary').locator('nav button').filter({has:page.locator('span').getByText('Integrations',{exact:true})}).click();
 const panel=page.getByRole('region',{name:'External provider integrations'});
 await expect(panel.getByRole('heading',{name:'External provider integrations'})).toBeVisible();
 const select=panel.getByLabel('Provider',{exact:true});
 await expect(select.locator('option')).toHaveCount(7);
 for(const provider of ['crm','email','calendar','finance','github','notion','google']){
  await select.selectOption(provider);
  await expect(panel.getByText('Authorization: disconnected · Operator setup required')).toBeVisible();
  await panel.getByRole('checkbox').first().check();
  await expect(panel.getByRole('button',{name:'Authorize provider'})).toBeDisabled();
  await expect(panel.getByRole('button',{name:'Queue incremental sync'})).toBeDisabled();
 }
 await panel.getByRole('button',{name:'Refresh provider diagnostics'}).click();
 await expect(panel.getByText('Authorization: disconnected · Operator setup required')).toBeVisible();
});
