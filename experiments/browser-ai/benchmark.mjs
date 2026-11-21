// Isolated inference feasibility experiment. Synthetic founder scenarios only.
import { performance } from 'node:perf_hooks';

const modelId = process.env.ONEBOARD_BROWSER_AI_MODEL || 'onnx-community/Qwen3-0.6B-ONNX';
const dtype = process.env.ONEBOARD_BROWSER_AI_DTYPE || 'q4';
const maxTokens = Number(process.env.ONEBOARD_BROWSER_AI_MAX_TOKENS || 64);
const scenarios = [
  { id: 'short-runway', prompt: 'Cash $9000, monthly expenses $6000, monthly revenue $2000. Estimate runway months and suggest one safe action.' },
  { id: 'long-runway', prompt: 'Cash $90000, monthly expenses $6000, monthly revenue $2000. Estimate runway months and suggest one safe action.' },
  { id: 'delivery-risk', prompt: 'A solo founder promised a client delivery tomorrow but a blocker makes that impossible. What should the founder do?' },
];

const loadStart = performance.now();
console.log(JSON.stringify({ stage: 'loading_model', at: new Date().toISOString(), model: modelId, dtype }));
const { pipeline, env } = await import('@huggingface/transformers');
env.allowRemoteModels = true;
const generator = await pipeline('text-generation', modelId, { device: 'cpu', dtype });
const loadSeconds = Number(((performance.now() - loadStart) / 1000).toFixed(2));
console.log(JSON.stringify({ stage: 'loaded', load_seconds: loadSeconds, model: modelId, dtype }));
const outputs = [];
for (const scenario of scenarios) {
  const start = performance.now();
  const generated = await generator([
    { role: 'system', content: 'You are a founder adviser. Answer directly, not with a thinking transcript. Treat inputs as hypothetical. Do not invent company records. Answer concisely.' },
    { role: 'user', content: scenario.prompt },
  ], { max_new_tokens: maxTokens, do_sample: false });
  const raw = generated?.[0]?.generated_text;
  const response = Array.isArray(raw) ? raw.at(-1)?.content : raw;
  if (typeof response !== 'string' || !response.trim()) {
    throw new Error('Real inference returned no text for ' + scenario.id);
  }
  const result = { scenario: scenario.id, seconds: Number(((performance.now() - start) / 1000).toFixed(2)), output: response.slice(0, 1400) };
  outputs.push(result);
  console.log(JSON.stringify({ stage: 'response', model: modelId, dtype, ...result }));
}
console.log(JSON.stringify({
  stage: 'summary', execution: 'real_onnx_wasm_inference', model: modelId, dtype, load_seconds: loadSeconds,
  prompts_executed: outputs.length, outputs_differ: new Set(outputs.map(x => x.output)).size > 1,
  note: 'Neither quality nor WebGPU availability is proven by CPU inference',
}));