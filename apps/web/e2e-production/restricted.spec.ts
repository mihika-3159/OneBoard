import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
test('restricted PostgreSQL HTTPS browser journey and unauthorized access',async({browser})=>{
 test.setTimeout(180000);
 const contexts=await Promise.all([browser.newContext({ignoreHTTPSErrors:true,baseURL:'https://127.0.0.1:8443'}),browser.newContext({ignoreHTTPSErrors:true,baseURL:'https://127.0.0.1:8443'})]);
 try{
  const pages=await Promise.all(contexts.map(c=>c.newPage()));
  const ids:string[]=[];
  for(const [i,page] of pages.entries()){
   const root=await page.goto('https://127.0.0.1:8443/');
   expect(root?.headers()['content-security-policy']).toContain("script-src 'self'");
   await expect(page.getByText('Founder Login')).toBeVisible();
   const blocked=await page.evaluate(()=>new Promise<boolean>(resolve=>{
    const timer=setTimeout(()=>resolve(false),3000);
    document.addEventListener('securitypolicyviolation',e=>{if(e.violatedDirective.startsWith('script-src')){clearTimeout(timer);resolve(true)}},{once:true});
    const s=document.createElement('script');s.textContent='window.__oneboardInlineProbe = true';document.head.append(s);
   }));
   expect(blocked).toBeTruthy();
   expect(await page.evaluate(()=>Boolean((window as any).__oneboardInlineProbe))).toBeFalsy();
   expect((await page.request.get('/api/business/metrics')).status()).toBe(401);
   await page.getByRole('button',{name:/Register/}).click();
   await page.getByLabel('Your Full Name').fill('Production CI '+i);
   await page.getByLabel('Workspace / Business Name').fill('Disposable CI '+i);
   await page.getByLabel('Founder Email').fill(randomUUID()+'@example.test');
   await page.getByLabel('Password',{exact:true}).fill('Synthetic-test-password123!');
   const [registration]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/auth/register')&&r.request().method()==='POST'),page.getByRole('button',{name:'Create Workspace & Sign In'}).click()]);
   expect(registration.status()).toBe(201);expect(await registration.json()).not.toHaveProperty('token');
   await expect(page.getByRole('navigation',{name:'Workspace sections'})).toBeVisible();
   const me=await page.request.get('/api/auth/me');expect(me.ok()).toBeTruthy();
   ids.push((await me.json()).business.id);
   const cookies=await contexts[i].cookies();expect(cookies.some(c=>c.httpOnly&&c.secure)).toBeTruthy();
   for(const name of ['Overview','Founder Command','Boardroom','Workflow Studio','Agent Studio','Accountability','Business Memory','Operations & CRM','Finance & Ledger','Integrations','Settings']){
    await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name}).click();
    await expect(page.getByRole('main',{name,exact:true})).toBeVisible();
    await expect(page.getByText('Loading workspace view…')).toHaveCount(0);
   }
   expect((await page.request.post('/api/data/delete-workspace',{headers:{Origin:'https://invalid.example'},data:{confirmation:'DELETE '+ids[i],password:'Synthetic-test-password123!'}})).status()).toBe(403);
  }
  expect(ids[0]).not.toBe(ids[1]);
  const page=pages[0];const csrf=(await contexts[0].cookies()).find(c=>c.name==='oneboard_csrf')!.value;
  const created=await page.request.post('/api/workflows',{headers:{Origin:'https://127.0.0.1:8443','X-CSRF-Token':csrf},data:{name:'Production synthetic workflow',nodes:[{id:'start',type:'trigger',data:{}}],edges:[]}});
  expect(created.status(),await created.text()).toBe(200);const workflow=await created.json();
  await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Workflow Studio'}).click();
  await expect(page.getByRole('button',{name:/Production synthetic workflow/})).toBeVisible();
  const other=await pages[1].request.get('/api/workflows');expect((await other.json()).some((w:any)=>w.id===workflow.id)).toBeFalsy();
  await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Finance & Ledger'}).click();
  await expect(page.getByRole('heading',{name:'Accounting journal & reconciliation'})).toBeVisible();
  await page.getByLabel('Accounting month').fill('2020-01');await page.getByLabel('Transaction kind').selectOption('opening_cash');await page.getByLabel('Amount',{exact:true}).fill('100.30');await page.getByLabel('Booking date').fill('2020-01-01');await page.getByLabel('Evidence text',{exact:true}).fill('Disposable production browser evidence');await page.getByRole('button',{name:'Record transaction'}).click();await expect(page.getByText('Journal transaction recorded')).toBeVisible();await expect(page.getByText('Journal cash balance:').locator('strong')).toHaveText('100.30');
  await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name:'Settings'}).click();await expect(page.getByRole('button',{name:'Download workspace snapshot'})).toBeVisible();
  const snapshot=await page.request.get('/api/data/export-snapshot');expect(snapshot.ok()).toBeTruthy();const data=await snapshot.json();expect(data.snapshot_consistent).toBeTruthy();expect(data.tables.businesses).toHaveLength(1);expect(data.tables.users[0]).not.toHaveProperty('hashed_password');
  for(const [i,page] of pages.entries()){
   expect((await (await page.request.get('/api/business/metrics')).json()).tenant_id).toBe(ids[i]);
   await page.getByTitle('Log out and invalidate session').click();
   await expect(page.getByText('Founder Login')).toBeVisible();
   expect((await page.request.get('/api/auth/me')).status()).toBe(401);
  }
 }finally{await Promise.all(contexts.map(c=>c.close()))}
});
