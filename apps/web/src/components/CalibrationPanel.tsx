import React,{useEffect,useState} from 'react';
import {api} from '../services/api';
import {DecisionRecord} from '../types';
export function CalibrationPanel({decisions}:{decisions:DecisionRecord[]}){
 const [rows,setRows]=useState<any[]>([]);const [decision,setDecision]=useState('');const [adviser,setAdviser]=useState('');
 const [metric,setMetric]=useState('');const [point,setPoint]=useState('');const [lower,setLower]=useState('');const [upper,setUpper]=useState('');
 const [confidence,setConfidence]=useState('0.8');const [days,setDays]=useState('30');const [message,setMessage]=useState('');
 const [busy,setBusy]=useState(false);
 async function refresh(){try{setRows((await api.getCalibration()).rows)}catch(e){setMessage('Unable to load calibration')}}
 useEffect(()=>{void refresh()},[]);
 async function save(){setBusy(true);try{await api.recordForecast(decision,{adviser,metric,point:Number(point),lower:Number(lower),upper:Number(upper),confidence:Number(confidence),days:Number(days)});setMessage('Prospective forecast recorded');await refresh()}catch(e){setMessage(e instanceof Error?e.message:'Forecast failed')}finally{setBusy(false)}}
 return <section className="glass-panel p-4 rounded-xl space-y-3 text-sm">
 <h2 className="font-semibold text-white">Historical adviser calibration</h2>
 <p className="text-slate-400">Founder-recorded prospective forecasts versus later tenant-recorded observations. Not independent verification. Small samples are explicitly flagged.</p>
 <div className="grid gap-2 sm:grid-cols-2"><label>Decision<select className="block w-full bg-slate-900 border rounded p-2" value={decision} onChange={e=>{setDecision(e.target.value);setAdviser('')}}><option value="">Select decision</option>{decisions.map(d=><option value={d.id} key={d.id}>{d.title}</option>)}</select></label>
 <label>Adviser<select className="block w-full bg-slate-900 border rounded p-2" value={adviser} onChange={e=>setAdviser(e.target.value)}><option value="">Select participating adviser</option>{decisions.find(d=>d.id===decision)?.advisers_consulted?.map(a=><option key={a}>{a}</option>)}</select></label>
 {[[metric,setMetric,'Metric'],[point,setPoint,'Point forecast'],[lower,setLower,'Lower bound'],[upper,setUpper,'Upper bound'],[confidence,setConfidence,'Interval confidence (0–1)'],[days,setDays,'Days until observation']] .map(([value,setter,label]:any)=><label key={label}>{label}<input className="block w-full bg-slate-900 border rounded p-2" value={value} onChange={e=>setter(e.target.value)}/></label>)}</div>
 <button disabled={busy||!decision||!adviser||!metric||!point||!lower||!upper||!confidence||!days} className="bg-indigo-600 px-3 py-2 rounded disabled:opacity-50" onClick={()=>void save()}>Record prospective forecast</button>
 {message&&<p role="status">{message}</p>}
 {!rows.length&&<p>No eligible historical observations yet.</p>}
 {rows.map(row=><article className="border border-slate-700 rounded p-3" key={row.adviser}><strong>{row.adviser}</strong><p>{row.observed}/{row.due} due forecasts observed. {row.low_sample?'Low sample; do not rank advisers.':''}</p><p>Interval coverage: {row.interval_coverage===null?'Unavailable':(row.interval_coverage*100).toFixed(1)+'%'} · Brier score: {row.brier_score===null?'Unavailable':row.brier_score.toFixed(3)}</p><p>95% Wilson interval: {row.coverage_95pct_wilson?.map((x:number)=>(x*100).toFixed(1)+'%').join(' to ')||'Unavailable'}</p><p>Tasks marked done: {row.tasks_marked_done}/{row.tasks}</p><pre className="text-xs whitespace-pre-wrap">{JSON.stringify(row.errors_by_metric,null,2)}</pre></article>)}
 </section>
}
