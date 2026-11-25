import {test,expect} from '@playwright/test';
import {nvda} from '@guidepup/guidepup';
import {randomUUID} from 'node:crypto';
import {writeFileSync} from 'node:fs';
test('native NVDA announces OneBoard login, navigation and dialog controls',async({page,browser},info)=>{
 const evidence:{screenReader:string;version:unknown;browser:string;checks:{label:string;phrases:string[]}[]}={screenReader:'NVDA',version:null,browser:browser.version(),checks:[]};
 let started=false;
 try{
  await nvda.start();started=true;evidence.version=nvda.version;
  await page.goto('/');
  await expect(page.getByText('Founder Login')).toBeVisible();
  await page.bringToFront();
  async function speech(label:string,control:ReturnType<typeof page.locator>,pattern:RegExp){
   await nvda.clearSpokenPhraseLog();
   // Actual OS accessibility focus, not a DOM accessibility-tree substitute.
   await control.focus();
   await expect(control).toBeFocused();
   await expect.poll(async()=> (await nvda.spokenPhraseLog()).join(' '),{timeout:15000}).toMatch(pattern);
   evidence.checks.push({label,phrases:await nvda.spokenPhraseLog()});
  }
  await speech('email',page.getByLabel('Founder Email'),/Founder Email/i);
  await speech('password',page.getByLabel('Password',{exact:true}),/Password/i);
  await speech('sign in',page.getByRole('button',{name:'Sign In to OneBoard'}),/Sign In to OneBoard/i);
  await page.getByRole('button',{name:/Register/}).click();
  await speech('registration name',page.getByLabel('Your Full Name'),/Your Full Name/i);
  await page.getByLabel('Your Full Name').fill('NVDA Synthetic Founder');
  await page.getByLabel('Workspace / Business Name').fill('NVDA Synthetic Workspace');
  await page.getByLabel('Founder Email').fill(randomUUID()+'@example.test');
  await page.getByLabel('Password',{exact:true}).fill('Synthetic-test-password123!');
  await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
  const nav=page.getByRole('navigation',{name:'Workspace sections'});
  await expect(nav).toBeVisible();
  for(const name of ['Overview','Founder Command','Boardroom','Workflow Studio','Agent Studio','Accountability','Business Memory','Operations & CRM','Finance & Ledger','Integrations','Settings']){
   const control=nav.getByRole('button',{name,exact:true});
   await speech(name,control,new RegExp(name.replace('&','(?:and|&)'),'i'));
   await nvda.press('Enter');
   await expect(page.getByRole('main',{name,exact:true})).toBeVisible();
  }
  const alerts=page.getByRole('button',{name:'Proactive Scheduler Alerts'});
  await speech('alerts',alerts,/Proactive Scheduler Alerts/i);
  await nvda.press('Enter');
  const dialog=page.getByRole('dialog',{name:'Tenant proactive alerts'});
  await expect(dialog).toBeVisible();
  await speech('dialog close',dialog.getByRole('button',{name:'Close'}),/Close/i);
  await nvda.press('Escape');await expect(dialog).toHaveCount(0);await expect(alerts).toBeFocused();
  const logout=page.getByRole('button',{name:'Log out and invalidate session'});
  await speech('logout',logout,/Log out and invalidate session/i);
  await nvda.press('Enter');await expect(page.getByText('Founder Login')).toBeVisible();
 }finally{
  writeFileSync('nvda-speech.json',JSON.stringify(evidence,null,2));
  await info.attach('nvda-speech',{body:JSON.stringify(evidence,null,2),contentType:'application/json'});
  if(started)await nvda.stop();
 }
});
