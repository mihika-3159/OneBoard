import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
test('restricted PostgreSQL HTTPS browser journey and unauthorized access',async({browser})=>{
 const contexts=await Promise.all([browser.newContext({ignoreHTTPSErrors:true}),browser.newContext({ignoreHTTPSErrors:true})]);
 try{
  const pages=await Promise.all(contexts.map(c=>c.newPage()));
  const ids:string[]=[];
  for(const [i,page] of pages.entries()){
   await page.goto('https://127.0.0.1:8443/');
   await expect(page.getByText('Founder Login')).toBeVisible();
   expect((await page.request.get('/api/business/metrics')).status()).toBe(401);
   await page.getByRole('button',{name:/Register/}).click();
   await page.getByLabel('Your Full Name').fill('Production CI '+i);
   await page.getByLabel('Workspace / Business Name').fill('Disposable CI '+i);
   await page.getByLabel('Founder Email').fill(randomUUID()+'@example.test');
   await page.getByLabel('Password',{exact:true}).fill('Synthetic-test-password123!');
   await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
   await expect(page.getByRole('navigation',{name:'Workspace sections'})).toBeVisible();
   const me=await page.request.get('/api/auth/me');expect(me.ok()).toBeTruthy();
   ids.push((await me.json()).business.id);
   const cookies=await contexts[i].cookies();expect(cookies.some(c=>c.httpOnly&&c.secure)).toBeTruthy();
   for(const name of ['Finance & Ledger','Workflow Studio','Settings']){
    await page.getByRole('navigation',{name:'Workspace sections'}).getByRole('button',{name}).click();
    await expect(page.getByRole('main',{name})).toBeVisible();
   }
   expect((await page.request.post('/api/data/delete-workspace',{headers:{Origin:'https://invalid.example'},data:{confirmation:'DELETE '+ids[i],password:'Synthetic-test-password123!'}})).status()).toBe(403);
  }
  expect(ids[0]).not.toBe(ids[1]);
  for(const [i,page] of pages.entries()){
   expect((await (await page.request.get('/api/business/metrics')).json()).tenant_id).toBe(ids[i]);
   await page.getByTitle('Log out and invalidate session').click();
   await expect(page.getByText('Founder Login')).toBeVisible();
   expect((await page.request.get('/api/auth/me')).status()).toBe(401);
  }
 }finally{await Promise.all(contexts.map(c=>c.close()))}
});
