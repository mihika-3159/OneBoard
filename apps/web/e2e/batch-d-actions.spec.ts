import { test, expect, type Page } from '@playwright/test';
import { randomUUID } from 'node:crypto';

async function register(page: Page) {
  await page.goto('/');
  await page.getByRole('button',{name:/Register/}).click();
  await page.getByPlaceholder('e.g. Alex Founder').fill('Batch D Browser Founder');
  await page.getByPlaceholder('e.g. Apex SaaS Labs').fill('Disposable Button Test');
  await page.getByPlaceholder('founder@example.com').fill(randomUUID()+'@example.test');
  await page.locator('input[type=password]').fill('TestPassword123!');
  await page.getByRole('button',{name:'Create Workspace & Sign In'}).click();
  await expect(page.getByText('Batch D Browser Founder')).toBeVisible();
}
async function tab(page:Page,label:string) {
  await page.getByRole('complementary').locator('nav button').filter({has:page.locator('span').getByText(label,{exact:true})}).click();
  await expect(page.locator('header')).toContainText(label);
}
async function clickRequest(page:Page,button:string,path:string,method='POST') {
  const [response]=await Promise.all([
    page.waitForResponse(r=>new URL(r.url()).pathname===path&&r.request().method()===method),
    page.getByRole('button',{name:button,exact:true}).click()
  ]);
  expect(response.status(),path+': '+await response.text()).toBe(200);
  return response.json();
}
test('real buttons import CSV, search a stored document and refresh financial data',async({page})=>{
  test.setTimeout(120_000);
  await register(page);
  await tab(page,'Integrations');
  await page.getByLabel('Customer CSV file').setInputFiles({name:'synthetic.csv',mimeType:'text/csv',buffer:Buffer.from('name,mrr\nSynthetic Subscriber,123.45\n')});
  const preview=await clickRequest(page,'Validate CSV','/api/integrations/local/customers/import');
  expect(preview.written).toBe(false);
  await expect(page.getByText('1 rows validated. No records written yet.')).toBeVisible();
  const commit=await clickRequest(page,'Confirm Import','/api/integrations/local/customers/import');
  expect(commit.written).toBe(true);
  await tab(page,'Operations & CRM');
  await page.getByRole('tab',{name:'Customers (1)'}).click();
  await expect(page.getByText('Synthetic Subscriber')).toBeVisible();
  await tab(page,'Finance & Ledger');
  await clickRequest(page,'Refresh','/api/business/metrics','GET');
  await tab(page,'Business Memory');
  await page.getByRole('button',{name:'Ingest Document'}).click();
  await page.locator('input[type=file]').setInputFiles({name:'synthetic.txt',mimeType:'text/plain',buffer:Buffer.from('synthetic quarterly pricing evidence')});
  const doc=await clickRequest(page,'Store Document in Business Memory','/api/memory/upload');
  expect(doc.chunks).toBe(1);
  await expect(page.getByText(/chunks stored; semantic embeddings/)).toBeVisible();
  await page.getByRole('button',{name:'Semantic Search'}).click();
  await page.getByPlaceholder(/Query semantic memory/).fill('synthetic quarterly pricing evidence');
  await clickRequest(page,'Hybrid Search','/api/memory/search');
  await expect(page.getByText('Citation Source: synthetic.txt')).toBeVisible();
});

test('real command, workflow, agent, boardroom and settings controls operate on synthetic workspace',async({page})=>{
  test.setTimeout(120_000);
  await register(page);
  await tab(page,'Founder Command');
  await page.getByPlaceholder(/Ask a question or delegate a task/).fill('What business records should I collect?');
  const [stream] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/ai/command/stream'
      && response.request().method() === 'POST'),
    page.getByRole('button', {name: 'Send founder command'}).click(),
  ]);
  expect(stream.status()).toBe(200);
  expect(stream.headers()['content-type']).toContain('application/x-ndjson');
  await expect(page.getByText(/^Offline simulated response: Ollama inference was unavailable/)).toBeVisible();
  await tab(page,'Boardroom');
  await page.getByRole('button',{name:'Convene New Meeting'}).click();
  await expect(page.getByRole('heading',{name:'Convene AI Executive Council'})).toBeVisible();
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Convene AI Executive Council'})).toHaveCount(0);
  await tab(page,'Workflow Studio');
  await page.getByRole('button',{name:'Teach OneBoard a Process'}).click();
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  // Set up a safe trigger-only workflow through the real authenticated API.
  const cookies=await page.context().cookies();
  const csrf=cookies.find(c=>c.name==='oneboard_csrf')?.value;
  expect(csrf).toBeTruthy();
  const created=await page.request.post('/api/workflows',{headers:{'X-CSRF-Token':csrf!,'Origin':'http://127.0.0.1:4173'},data:{name:'Synthetic button workflow',nodes:[{id:'start',type:'trigger',data:{}}],edges:[]}});
  expect(created.status(),await created.text()).toBe(200);
  const workflow=await created.json();
  await tab(page,'Overview');
  await tab(page,'Workflow Studio');
  await page.getByText('Synthetic button workflow',{exact:true}).first().click();
  const run=await clickRequest(page,'Execute Workflow','/api/workflows/'+workflow.id+'/execute');
  expect(run.status).toBe('completed');
  await expect(page.getByText('Execution Status: completed')).toBeVisible();
  await tab(page,'Agent Studio');
  await page.getByRole('button',{name:'Create Custom Agent'}).click();
  await page.getByRole('button',{name:'Visual Form'}).click();
  await page.getByLabel('Agent name').fill('Synthetic Browser Analyst');
  await page.getByLabel('System instruction prompt').fill('Use supplied evidence only.');
  const agent=await clickRequest(page,'Deploy Custom Agent','/api/agents');
  await page.getByLabel('Test simulation input').fill('Synthetic question');
  await clickRequest(page,'Test Agent in Sandbox','/api/agents/'+agent.id+'/test');
  await expect(page.getByText('Agent Output:')).toBeVisible();
  await tab(page,'Accountability');
  await tab(page,'Settings');
  await clickRequest(page,'Refresh Status','/api/ai/status','GET');
  const benchmark=await clickRequest(page,'Test Selected Model Inference','/api/ai/benchmark');
  expect(typeof benchmark.simulated).toBe('boolean');
  await expect(page.getByText(/Simulated: (true|false)/)).toBeVisible();
});
