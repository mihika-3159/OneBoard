import React,{useEffect,useState} from 'react';
import {api} from '../services/api';
import {CustomAgent} from '../types';
type Step={agent_id:string;tool:string;document_id?:string};
export function AgentRuntimePanel({agents,selectedAgent}:{agents:CustomAgent[];selectedAgent:CustomAgent|null}){
  const [goal,setGoal]=useState('');
  const [steps,setSteps]=useState<Step[]>([]);
  const [runs,setRuns]=useState<any[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [key,setKey]=useState(()=>crypto.randomUUID());
  async function refresh(){try{setRuns(await api.getAgentRuns())}catch(e){setError(e instanceof Error?e.message:'Unable to load runs')}}
  useEffect(()=>{void refresh()},[]);
  useEffect(()=>{setSteps(selectedAgent?[{agent_id:selectedAgent.id,tool:'analyze'}]:[]);setKey(crypto.randomUUID())},[selectedAgent?.id]);
  function edit(i:number,patch:Partial<Step>){setSteps(old=>old.map((s,j)=>j===i?{...s,...patch}:s));setKey(crypto.randomUUID())}
  async function act(operation:()=>Promise<any>){setBusy(true);setError('');try{await operation();await refresh()}catch(e){setError(e instanceof Error?e.message:'Run operation failed')}finally{setBusy(false)}}
  return <section className="glass-panel p-4 rounded-xl space-y-3 text-sm">
    <h2 className="font-semibold text-white">Durable read-only agent execution</h2>
    <p className="text-slate-400">Founder-defined ordered steps; checkpoints survive reloads. Only explicitly granted tools run. No external actions or recursive delegation.</p>
    <label className="block">Run goal<input className="block w-full bg-slate-900 border rounded p-2" value={goal} maxLength={2000} onChange={e=>{setGoal(e.target.value);setKey(crypto.randomUUID())}}/></label>
    {steps.map((step,i)=>{const agent=agents.find(a=>a.id===step.agent_id);const tools=['analyze',...['read_crm','calculate_metrics','read_memory'].filter(t=>agent?.allowed_tools?.includes(t)&&!agent.requires_approval_for?.includes(t))];
      return <div key={i} className="flex flex-wrap gap-2 items-center">
        <span>Step {i+1}</span><select aria-label={'Step '+(i+1)+' agent'} className="bg-slate-900 border rounded p-2" disabled={i===0} value={step.agent_id} onChange={e=>edit(i,{agent_id:e.target.value,tool:'analyze',document_id:undefined})}>{agents.filter(a=>a.status==='active').map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <select aria-label={'Step '+(i+1)+' tool'} className="bg-slate-900 border rounded p-2" value={step.tool} onChange={e=>edit(i,{tool:e.target.value,document_id:undefined})}>{tools.map(t=><option key={t}>{t}</option>)}</select>
        {step.tool==='read_memory'&&<select aria-label="Memory document" className="bg-slate-900 border rounded p-2" value={step.document_id||''} onChange={e=>edit(i,{document_id:e.target.value})}><option value="">Select granted document</option>{agent?.allowed_memory_collections?.map(id=><option key={id}>{id}</option>)}</select>}
        {i>0&&<button type="button" onClick={()=>{setSteps(old=>old.filter((_,j)=>j!==i));setKey(crypto.randomUUID())}}>Remove</button>}
      </div>})}
    <div className="flex gap-3">
      <button disabled={!selectedAgent||steps.length>=12||busy} onClick={()=>{setSteps(old=>[...old,{agent_id:selectedAgent!.id,tool:'analyze'}]);setKey(crypto.randomUUID())}}>Add handoff step</button>
      <button className="bg-indigo-600 rounded px-3 py-2 disabled:opacity-50" disabled={!selectedAgent||!goal.trim()||!steps.length||busy} onClick={()=>void act(()=>api.startAgentRun(selectedAgent!.id,{goal,steps,idempotency_key:key}))}>Create durable run</button>
      <button onClick={()=>void refresh()}>Refresh runs</button>
    </div>
    {error&&<p role="alert" className="text-rose-400">{error}</p>}
    {runs.map(run=><article key={run.id} className="border border-slate-700 rounded p-3 space-y-2">
      <div>{run.goal} · <strong>{run.status}</strong> · {run.next_step}/{run.steps} steps</div>
      <div className="flex gap-3">{['ready','running','recoverable'].includes(run.status)&&<>
        <button disabled={busy} onClick={()=>void act(()=>api.advanceAgentRun(run.id))}>Advance or recover checkpoint</button>
        <button onClick={()=>void act(()=>api.cancelAgentRun(run.id))}>Cancel run</button></>}</div>
      <details><summary>Recorded checkpoint results</summary><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify({results:run.results,errors:run.errors},null,2)}</pre></details>
    </article>)}
  </section>
}
