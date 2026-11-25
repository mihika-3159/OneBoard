import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
const tabs=['Overview','Founder Command','Boardroom','Workflow Studio','Agent Studio','Accountability','Business Memory','Operations & CRM','Finance & Ledger','Integrations','Settings'];
async function register(page:import('@playwright/test').Page){
 await page.goto('/');await expect(page.getByText('Founder Login')).toBeVisible();
 await page.getByRole('button',{name:/Register/}).click();await page.getByLabel('Your Full Name').fill('Batch O Founder');await page.getByLabel('Workspace / Business Name').fill('Batch O Workspace');await page.getByLabel('Founder Email').fill('batch-o-'+randomUUID()+'@example.test');await page.getByLabel('Password',{exact:true}).fill('TestPassword123!');await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();await expect(page.getByRole('navigation',{name:'Workspace sections'})).toBeVisible();
}
for(const viewport of [{width:390,height:844},{width:768,height:1024}]){
 test('all eleven sections at '+viewport.width+'px',async({page})=>{
 test.setTimeout(120000);await page.setViewportSize(viewport);await register(page);
 for(const tab of tabs){const nav=page.getByRole('navigation',{name:'Workspace sections'});const button=nav.getByRole('button',{name:new RegExp(tab)});await button.focus();await page.keyboard.press('Enter');await expect(button).toHaveAttribute('aria-current','page');await expect(page.getByRole('main',{name:tab,exact:true})).toBeVisible();await expect(page.getByText('Loading workspace view…')).toHaveCount(0);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}
 await expect(page.getByRole('region',{name:'Workspace deletion'})).toBeVisible();await page.getByRole('button',{name:'Prepare workspace deletion'}).click();await expect(page.getByRole('button',{name:'Permanently delete workspace'})).toBeDisabled();await page.getByRole('button',{name:'Cancel deletion'}).click();
 });
}
test('expired session removes workspace',async({page})=>{await register(page);await expect(page.getByText(/Financial figures are user-recorded and not independently reconciled/)).toBeVisible();await page.route('**/api/business/metrics',route=>route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({detail:'Expired'})}));await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Finance & Ledger'}).click();await expect(page.getByText('Founder Login')).toBeVisible();await expect(page.getByRole('navigation',{name:'Workspace sections'})).toHaveCount(0);await expect(page.getByRole('alert')).toContainText('Your session expired');});
