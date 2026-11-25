import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const axePath=require.resolve('axe-core/axe.min.js');
const tabs=['Overview','Founder Command','Boardroom','Workflow Studio','Agent Studio','Accountability','Business Memory','Operations & CRM','Finance & Ledger','Integrations','Settings'];
async function register(page:import('@playwright/test').Page){
 await page.goto('/');await expect(page.getByText('Founder Login')).toBeVisible();
 await page.getByRole('button',{name:/Register/}).click();
 await page.getByLabel('Your Full Name').fill('Acceptance Founder');
 await page.getByLabel('Workspace / Business Name').fill('Acceptance Workspace');
 await page.getByLabel('Founder Email').fill(randomUUID()+'@example.test');
 await page.getByLabel('Password',{exact:true}).fill('TestPassword123!');
 await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
 await expect(page.getByRole('navigation',{name:'Workspace sections'})).toBeVisible();
}
test('accessibility tree, keyboard navigation and automated WCAG checks for all tabs',async({page},info)=>{
 test.setTimeout(180000);await register(page);
 const violations:unknown[]=[];
 for(const tab of tabs){
  const b=page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:new RegExp(tab)});
  await b.focus();await page.keyboard.press('Enter');
  const main=page.getByRole('main',{name:tab,exact:true});await expect(main).toBeVisible();
  await expect(page.getByText('Loading workspace view…')).toHaveCount(0);
  await page.addScriptTag({path:axePath});
  const result=await page.evaluate(async()=>{const axe=(window as any).axe;return axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}})});
  violations.push(...result.violations.map((v:any)=>({tab,id:v.id,impact:v.impact,targets:v.nodes.map((n:any)=>n.target)})));
  const tree=await main.ariaSnapshot();expect(tree.length).toBeGreaterThan(0);
 }
 // Real keyboard focus/escape behavior is verified separately from axe.
 const alerts=page.getByRole('button',{name:'Proactive Scheduler Alerts'});await alerts.focus();await page.keyboard.press('Enter');
 const alertDialog=page.getByRole('dialog',{name:'Tenant proactive alerts'});await expect(alertDialog).toBeVisible();await expect(alertDialog.getByRole('button',{name:'Close'})).toBeFocused();
 await page.keyboard.press('Escape');await expect(alertDialog).toHaveCount(0);await expect(alerts).toBeFocused();
 const workflowNav=page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Workflow Studio'});await workflowNav.focus();await page.keyboard.press('Enter');
 const teach=page.getByRole('button',{name:'Teach OneBoard a Process'});await teach.focus();await page.keyboard.press('Enter');
 const teachDialog=page.getByRole('dialog',{name:'Teach OneBoard a Repetitive Process'});await expect(teachDialog).toBeVisible();await expect(teachDialog.getByRole('textbox',{name:'Describe manual process'})).toBeFocused();
 await page.keyboard.press('Tab');await expect(teachDialog.getByRole('button',{name:'Cancel',exact:true})).toBeFocused();await page.keyboard.press('Escape');await expect(teachDialog).toHaveCount(0);await expect(teach).toBeFocused();
 await info.attach('accessibility-audit.json',{body:JSON.stringify(violations,null,2),contentType:'application/json'});
 expect(violations).toEqual([]);
});
test('large workflow inventory remains bounded and keyboard-selectable',async({page})=>{
 await register(page);
 const records=Array.from({length:250},(_,i)=>({id:'synthetic-'+i,name:'Synthetic workflow '+i,description:'Synthetic bounded list',trigger_type:'manual',nodes:[{id:'start',type:'trigger',data:{label:'Start'}}],edges:[],version:1,is_active:true}));
 await page.route('**/api/workflows',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(records)}));
 const start=Date.now();
 await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Workflow Studio'}).click();
 await expect(page.getByRole('button',{name:/Synthetic workflow 0 /})).toBeVisible();
 await expect(page.getByRole('group',{name:'List pagination'})).toContainText('1–25 of 250');
 await expect(page.getByRole('button',{name:/Synthetic workflow \d+ /})).toHaveCount(25);
 await page.getByRole('button',{name:'Next page'}).click();
 await expect(page.getByRole('group',{name:'List pagination'})).toContainText('26–50 of 250');
 const row=page.getByRole('button',{name:/Synthetic workflow 25 /});await row.focus();await page.keyboard.press('Enter');await expect(row).toHaveAttribute('aria-pressed','true');
 const alternative=page.getByText('Workflow text alternative',{exact:true});await alternative.focus();await page.keyboard.press('Enter');const structure=page.getByRole('region',{name:'Workflow structure'});await expect(structure).toBeVisible();await expect(structure.getByText('Start',{exact:true})).toBeVisible();
 expect(Date.now()-start).toBeLessThan(15000);
});
