// Chromium hardware-capability check, not a model inference test.
import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  await page.goto('about:blank');
  const report = await page.evaluate(async () => {
    if (!navigator.gpu) return { webgpu_available: false, reason: 'navigator.gpu absent' };
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (!adapter) return { webgpu_available: false, reason: 'no GPU adapter' };
      const device = await adapter.requestDevice();
      const report = {
        webgpu_available: true,
        shader_f16: device.features.has('shader-f16'),
        max_storage_buffer_binding_size: device.limits.maxStorageBufferBindingSize
      };
      device.destroy();
      return report;
    } catch (error) {
      return { webgpu_available: false, reason: String(error) };
    }
  });
  console.log(JSON.stringify({ stage: 'browser_capability', browser: 'Chromium headless Linux', ...report }));
} finally {
  await browser.close();
}