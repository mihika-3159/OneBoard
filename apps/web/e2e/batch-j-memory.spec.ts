import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';

test('memory replacement, source verification and relevance feedback survive reload',async({page})=>{
  await page.goto('/');
  await page.getByRole('button',{name:/Register/}).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('Batch J Founder');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('Batch J Workspace');
  await page.getByPlaceholder('founder@example.com').fill(randomUUID()+'@example.test');
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
  await expect(page.getByText('Batch J Founder')).toBeVisible();
  const memory=()=>page.getByRole('complementary').locator('nav button').filter({has:page.locator('span').getByText('Business Memory',{exact:true})}).click();
  const upload=async(text:string)=>{
    await page.locator('input[type=file]').setInputFiles({name:'fixture.txt',mimeType:'text/plain',buffer:Buffer.from(text)});
    const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/memory/upload')&&r.request().method()==='POST'),page.getByRole('button',{name:'Store Document in Business Memory'}).click()]);
    expect(response.status(),await response.text()).toBe(200);
    return (await response.json()).document_id as string;
  };
  const search=async(query:string)=>{
    await page.getByRole('button',{name:'Semantic Search'}).click();
    await page.getByLabel('Memory search query').fill(query);
    await page.getByRole('button',{name:'Hybrid Search'}).click();
  };
  await memory();
  await page.getByRole('button',{name:'Ingest Document'}).click();
  const id=await upload('olduniqueprice annual plan 39');
  await expect(page.getByText(/fixture.txt · v1 ·/)).toBeVisible();
  await search('olduniqueprice');
  await expect(page.getByText(/Version 1 · Chunk 1 · Extracted characters/)).toBeVisible();
  await page.getByRole('button',{name:'Check citation'}).click();
  await expect(page.getByText(/Source checked: fixture.txt/)).toBeVisible();
  await page.getByRole('button',{name:'Helpful',exact:true}).click();
  await expect(page.getByText('Relevance feedback recorded for this query')).toBeVisible();
  await page.getByRole('button',{name:'Ingest Document'}).click();
  await page.getByLabel('Replace a source (optional)').selectOption(id);
  await upload('newuniqueprice annual plan 59');
  await expect(page.getByText(/fixture.txt · v1 · superseded/)).toBeVisible();
  await page.reload();
  await memory();
  await search('olduniqueprice');
  await expect(page.getByText('No current matching sources.')).toBeVisible();
  await search('newuniqueprice');
  await expect(page.getByText(/Version 2 · Chunk 1 · Extracted characters/)).toBeVisible();
});
