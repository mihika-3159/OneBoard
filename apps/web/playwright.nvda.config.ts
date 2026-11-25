import {defineConfig,devices} from '@playwright/test';
export default defineConfig({
 testDir:'./e2e-nvda',workers:1,retries:0,timeout:180000,
 use:{baseURL:'http://127.0.0.1:4173',...devices['Desktop Chrome'],headless:false,launchOptions:{args:['--force-renderer-accessibility']},trace:'retain-on-failure'},
 webServer:[
 {command:'python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000',url:'http://127.0.0.1:8000/health',cwd:'../..',timeout:120000},
 {command:'npm run dev -- --host 127.0.0.1 --port 4173',url:'http://127.0.0.1:4173',timeout:120000}
 ]
});
