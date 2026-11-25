import {defineConfig,devices} from '@playwright/test';
export default defineConfig({testDir:'./e2e-production',timeout:60000,retries:0,workers:1,use:{baseURL:'https://127.0.0.1:8443',ignoreHTTPSErrors:true,trace:'retain-on-failure'},projects:[{name:'chromium',use:{...devices['Desktop Chrome']}}]});
