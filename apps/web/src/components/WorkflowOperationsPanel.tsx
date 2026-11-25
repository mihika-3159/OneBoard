import React,{useEffect,useState} from 'react';
import {api} from '../services/api';
import {WorkflowDef} from '../types';

export function WorkflowOperationsPanel({selected,onUpdated}:{selected:WorkflowDef|null;onUpdated:(wf:WorkflowDef)=>void}){
 const [runs,setRuns]=useState<any[]>([]),[events,setEvents]=useState<any[]>([]),[versions,setVersions]=useState<any[]>([]);
 const [definition,setDefinition]=useState(''),[editing,setEditing]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
 async function refresh(){try{const [r,e]=await Promise.all([api.getWorkflowRuns(),api.getWorkflowEvents()]);setRuns(r);setEvents(e)}catch(e){setMessage(e instanceof Error?e.message:'History unavailable')}}
 useEffect(()=>{void refresh();const timer=setInterval(()=>void refresh(),15000);return()=>clearInterval(timer)},[]);
 useEffect(()=>{setEditing(false);setVersions([]);if(selected)api.getWorkflowVersions(selected.id).then(setVersions).catch(()=>setMessage('Version history unavailable'))},[selected?.id,selected?.version]);
 function draft(){if(!selected)return;setDefinition(JSON.stringify({name:selected.name,description:selected.description??null,category:selected.category,trigger_type:selected.trigger_type,trigger_config:selected.trigger_config??{},nodes:selected.nodes,edges:selected.edges,is_active:selected.is_active},null,2));setEditing(true)}
 async function act(action:()=>Promise<any>,update=false){setBusy(true);setMessage('');try{const result=await action();if(update){onUpdated(result);setEditing(false)}await refresh();setMessage('Operation recorded')}catch(e){setMessage(e instanceof Error?e.message:'Operation failed')}finally{setBusy(false)}}
 const attention=runs.filter(r=>['failed','paused','awaiting_approval'].includes(r.status)).length+events.filter(e=>e.status==='dead_letter').length;
 return <section className="glass-panel rounded-xl p-4 space-y-3 text-sm">
 <h2 className="font-bold text-white">Workflow control and execution history</h2>
 <p role="status">{attention} run or event records require attention. Refreshes every 15 seconds while open.</p>
 <button onClick={()=>void refresh()}>Refresh execution history</button>
 <button className="ml-3" disabled={busy} onClick={()=>void act(()=>api.reconcileWorkflowRuns())}>Quarantine interrupted runs</button>
 {selected&&<div className="border border-slate-700 rounded p-3 space-y-2">
 <p>{selected.name} · revision {selected.version||1} · {selected.is_active?'active':'inactive'}</p>
 <button onClick={draft}>Edit workflow definition and triggers</button>
 <button className="ml-3" disabled={busy} onClick={()=>void act(()=>api.updateWorkflowDefinition(selected.id,{name:selected.name,description:selected.description??null,category:selected.category,trigger_type:selected.trigger_type,trigger_config:selected.trigger_config??{},nodes:selected.nodes,edges:selected.edges,is_active:!selected.is_active,expected_version:selected.version||1}),true)}>{selected.is_active?'Deactivate workflow':'Activate workflow'}</button>
 {editing&&<div><p className="text-xs text-slate-400">Edit JSON for the executable graph. Supported triggers: manual, schedule, new_customer, invoice_overdue, metric_threshold, webhook. Metric configuration requires metric, operator and threshold. Conditional nodes use operator, left/right, and optional bindings.left with predecessor step and field. Edge branch is true or false. Saving an active definition opts into its event trigger; schedules require separate re-enabling.</p>
 <textarea aria-label="Workflow definition JSON" className="w-full h-64 bg-slate-950 border border-slate-700 rounded p-2 font-mono text-xs" value={definition} onChange={e=>setDefinition(e.target.value)}/>
 <button disabled={busy} onClick={()=>void act(()=>api.updateWorkflowDefinition(selected.id,{...JSON.parse(definition),expected_version:selected.version||1}),true)}>Save new revision</button>
 <button className="ml-3" onClick={()=>setEditing(false)}>Discard changes</button></div>}
 {selected.trigger_type==='webhook'&&<p className="break-all text-xs">POST /api/workflows/{selected.id}/webhook with write-capable X-API-Key and JSON event_id, payload. Reusing an event ID with changed payload is rejected.</p>}
 <details><summary>Revision history ({versions.length})</summary>{versions.map(v=><div key={v.version} className="flex justify-between p-1"><span>Revision {v.version} · {v.created_at}</span><button disabled={busy||v.version===(selected.version||1)} onClick={()=>{if(window.confirm('Restore as a new inactive revision?'))void act(()=>api.rollbackWorkflow(selected.id,selected.version||1,v.version),true)}}>Restore revision {v.version}</button></div>)}</details>
 </div>}
 {message&&<p role="alert">{message}</p>}
 <details open><summary>Recent execution notifications ({runs.length})</summary>{runs.slice(0,50).map(run=><article className="border border-slate-700 rounded p-2 mt-2" key={run.id}>
 <p>{run.workflow_name} · {run.status} · {run.trigger_source}</p><p className="text-xs">{run.error_message||''}</p>
 {['running','pending','paused','awaiting_approval','failed'].includes(run.status)&&<button disabled={busy} onClick={()=>void act(()=>api.cancelWorkflowRun(run.id))}>Cancel run</button>}
 {['paused','failed'].includes(run.status)&&run.verification_details?.checkpoint_protocol===1&&<button className="ml-3" disabled={busy} onClick={()=>void act(()=>api.recoverWorkflowRun(run.id))}>Recover from checkpoint</button>}
 <details><summary>Checkpoint results</summary><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(run.step_results,null,2)}</pre></details>
 </article>)}</details>
 <details><summary>Event queue and dead letters ({events.length})</summary>{events.slice(0,100).map(e=><p key={e.id} className="border-b border-slate-700 py-2">{e.kind} · {e.status} · {e.attempts} attempts {e.error?': '+e.error:''}
 {e.status==='dead_letter'&&!e.run_id&&e.attempts<=3&&<button className="ml-3" disabled={busy} onClick={()=>void act(()=>api.retryWorkflowEvent(e.id))}>Retry event</button>}</p>)}</details>
 </section>
}
