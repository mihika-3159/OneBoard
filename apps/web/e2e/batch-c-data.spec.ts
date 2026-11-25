import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';

test('owner export and explicit workspace deletion do not expose another tenant', async ({ browser }) => {
  const a=await browser.newContext(), b=await browser.newContext();
  const base='http://127.0.0.1:4173';
  const register=async(ctx:typeof a,label:string)=>{
    const res=await ctx.request.post(base+'/api/auth/register',{data:{name:label,business_name:label,email:randomUUID()+'@example.test',password:'TestPassword123!'}});
    expect(res.status()).toBe(201);
    const body=await res.json();
    return {headers:{Authorization:'Bearer '+body.token},id:body.business.id};
  };
  try {
    const x=await register(a,'Export owner'), y=await register(b,'Other tenant');
    const ex=await a.request.get(base+'/api/data/export/businesses',{headers:x.headers});
    expect(ex.status()).toBe(200);
    const page=await ex.json();
    expect(page.rows).toHaveLength(1);
    expect(page.rows[0].id).toBe(x.id);
    const users=await a.request.get(base+'/api/data/export/users',{headers:x.headers});
    expect(users.status()).toBe(200);
    expect(await users.text()).not.toContain('hashed_password');
    const wrong=await a.request.post(base+'/api/data/delete-workspace',{headers:x.headers,data:{confirmation:'DELETE '+y.id,password:'TestPassword123!'}});
    expect(wrong.status()).toBe(422);
    const del=await a.request.post(base+'/api/data/delete-workspace',{headers:x.headers,data:{confirmation:'DELETE '+x.id,password:'TestPassword123!'}});
    expect(del.status(),await del.text()).toBe(200);
    expect((await del.json()).backup_copies_deleted).toBe(false);
    expect((await a.request.get(base+'/api/auth/me',{headers:x.headers})).status()).toBe(401);
    expect((await b.request.get(base+'/api/auth/me',{headers:y.headers})).status()).toBe(200);
  } finally {await a.close();await b.close();}
});
