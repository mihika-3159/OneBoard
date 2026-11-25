import React, { useState, useEffect } from 'react';
import { Cpu, CheckCircle2, AlertTriangle, Zap, Server, ShieldCheck, RefreshCw } from 'lucide-react';
import { api } from '../services/api';
import { useInferenceOperation } from './useInferenceOperation';
import { AccountSecurityPanel } from './AccountSecurityPanel';
import { PortableArchivePanel } from './PortableArchivePanel';
import { GatewayStatus } from '../types';

export const SettingsTab: React.FC = () => {
  const inference = useInferenceOperation();
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus | null>(null);
  const [activeProfile, setActiveProfile] = useState('balanced');
  const [benchmarkResult, setBenchmarkResult] = useState<any | null>(null);
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fields=['document_days','resolved_alert_days','expired_session_days','completed_sync_days','resolved_conflict_days','completed_draft_days','performance_sample_days'];
  const [retention,setRetention]=useState<Record<string,string>>({});
  const [dataLoaded,setDataLoaded]=useState(false);
  const [dataBusy,setDataBusy]=useState(false);
  const [dataMessage,setDataMessage]=useState<string|null>(null);
  const [dataError,setDataError]=useState<string|null>(null);
  useEffect(()=>{
    let active=true;
    api.getRetention().then(row=>{
      if(!active)return;
      setRetention(Object.fromEntries(fields.map(k=>[k,row[k] == null?'':String(row[k])])));
      setDataLoaded(true);
    }).catch(e=>{if(active)setDataError(e instanceof Error?e.message:'Owner retention unavailable');});
    return ()=>{active=false;};
  },[]);
  const saveRetention=async()=>{
    setDataBusy(true);setDataError(null);setDataMessage(null);
    try {
      await api.saveRetention(Object.fromEntries(fields.map(k=>[k,retention[k]?.trim()?Number(retention[k]):null])));
      setDataMessage('Retention policy saved.');
    }catch(e){setDataError(e instanceof Error?e.message:'Retention update failed');}
    finally{setDataBusy(false);}
  };
  const downloadSnapshot=async()=>{
    setDataBusy(true);setDataError(null);setDataMessage(null);
    try {
      const payload=await api.exportSnapshot();
      const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
      const a=document.createElement('a');a.href=url;a.download='oneboard-workspace.json';a.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      setDataMessage('Consistent workspace snapshot prepared.');
    }catch(e){setDataError(e instanceof Error?e.message:'Export failed');}
    finally{setDataBusy(false);}
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const s = await api.getGatewayStatus();
      setGatewayStatus(s);
      setActiveProfile(s.active_profile || 'balanced');
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load model status. Please retry.');
    }
  };

  const handleSwitchProfile = async (p: string) => {
    setIsUpdating(true);
    try {
      await api.switchProfile(p);
      setActiveProfile(p);
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update model profile. Please retry.');
    } finally {
      setIsUpdating(false);
    }
  };

  const handleBenchmark = async () => {
    setIsBenchmarking(true);
    setBenchmarkResult(null);
    try {
      const res = await inference.run("/ai/benchmark");
      setBenchmarkResult(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Benchmark failed. Please retry.');
    } finally {
      setIsBenchmarking(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {inference.indicator}
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Centralized AI Gateway
            </span>
            <span className="text-xs text-slate-400">Operator-hosted server-side Ollama • No guaranteed uptime</span>
          </div>
          <h1 className="text-xl font-bold text-white">System Settings & Model Configuration</h1>
        </div>

        <button
          onClick={loadStatus}
          className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl border border-slate-700 transition"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh Status
        </button>
      </div>

      {error && (
        <div role="alert" className="p-3 rounded-xl border border-rose-500/40 bg-rose-500/10 text-rose-300 text-xs flex items-center justify-between gap-3">
          <span>{error}</span>
          <button onClick={loadStatus} className="underline shrink-0">Retry status</button>
        </div>
      )}

      {/* Ollama Connection Card */}
      <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <Server className="w-5 h-5 text-indigo-400" />
            <div>
              <span className="text-sm font-bold text-white block">Server-Side Ollama Inference Daemon</span>
              <span className="text-slate-400 font-mono text-[11px]">{gatewayStatus?.base_url || 'http://127.0.0.1:11434'}</span>
            </div>
          </div>
          <span
            className={`px-3 py-1 rounded-full text-xs font-mono font-semibold flex items-center gap-1.5 ${
              gatewayStatus?.status === 'connected' && gatewayStatus?.inference_available
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
            }`}
          >
            {gatewayStatus?.status === 'connected' && gatewayStatus?.inference_available ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5" /> Ollama ready ({gatewayStatus?.latency_ms}ms)
              </>
            ) : (
              <>
                <AlertTriangle className="w-3.5 h-3.5" />
                {gatewayStatus?.status === 'connected'
                  ? 'Selected model unavailable (fallback only)'
                  : 'Ollama offline (fallback only)'}
              </>
            )}
          </span>
        </div>

        {gatewayStatus?.status === 'connected' && !gatewayStatus?.inference_available && (
          <div role="status" className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300">
            Ollama is reachable, but the selected model ({gatewayStatus?.requested_model || 'unknown'}) is not installed. Other installed models do not make this workspace inference-ready.
          </div>
        )}

        {gatewayStatus?.offline_mode && (
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 leading-relaxed">
            <span className="font-semibold block mb-0.5">Local Daemon Notice:</span>
            Ollama is unavailable on the configured server. Responses may use a labeled deterministic fallback, not real AI inference. An authorized operator must provide server-side Ollama before real inference is available:
            <code className="block mt-2 p-2 rounded-lg bg-slate-900 border border-slate-800 font-mono text-[11px] text-white">
              ollama run qwen2.5:7b
            </code>
          </div>
        )}

        <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="text-slate-400">
            Available Server Models: <span className="text-white font-mono">{gatewayStatus?.available_models?.join(', ') || 'None (using local fallback adapter)'}</span>
          </div>
          <button
            onClick={handleBenchmark}
            disabled={isBenchmarking}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl transition shadow-md shadow-indigo-600/20"
          >
            <Zap className="w-3.5 h-3.5" />
            {isBenchmarking ? 'Testing...' : 'Test Selected Model Inference'}
          </button>
        </div>

        {benchmarkResult && (
          <div className="p-3.5 rounded-xl bg-slate-900 border border-indigo-500/30 text-slate-300 space-y-1">
            <div className="flex justify-between font-semibold">
              <span className={benchmarkResult.simulated ? 'text-amber-300' : 'text-emerald-300'}>
                {benchmarkResult.simulated ? 'Real inference unavailable (fallback used)' : 'Real inference benchmark passed'}
              </span>
              <span className="font-mono">{benchmarkResult.total_latency_ms} ms</span>
            </div>
            <div className="text-[11px] text-slate-400 font-mono">
              Model: {benchmarkResult.model} • Simulated: {String(benchmarkResult.simulated)}
              {benchmarkResult.fallback_reason && <span> • Reason: {benchmarkResult.fallback_reason}</span>}
            </div>
          </div>
        )}
      </div>

      <PortableArchivePanel />
      <section aria-label="Workspace data management" className="p-6 rounded-2xl glass-panel space-y-3 text-xs">
        <h2 className="text-sm font-bold text-white">Workspace data management (owner)</h2>
        <p className="text-slate-400">A consistent bounded JSON snapshot excludes credential fields. It is not an encrypted backup or a guarantee that user-entered text contains no secrets.</p>
        <button disabled={dataBusy||!dataLoaded} onClick={downloadSnapshot} className="px-4 py-2 rounded bg-indigo-600 disabled:opacity-50">Download workspace snapshot</button>
        <p className="text-slate-400">Retention is opt-in. Blank means keep indefinitely; enter 30–3650 days. Active alerts, financial evidence and audit history are not automatically removed.</p>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {fields.map((key,index)=><label key={key} className="space-y-1">
            {['Document retention days','Resolved alert retention days','Expired session retention days','Finished sync diagnostics retention days','Resolved provider conflict payload retention days','Completed draft payload retention days','Performance sample retention days'][index]}
            <input type="number" min="30" max="3650" step="1" value={retention[key]||''} onChange={e=>setRetention(old=>({...old,[key]:e.target.value}))} disabled={!dataLoaded||dataBusy} className="block w-full bg-slate-900 border rounded p-2 text-white"/>
          </label>)}
        </div>
        <button disabled={!dataLoaded||dataBusy||fields.some(key=>retention[key]&&(Number(retention[key])<30||Number(retention[key])>3650||!Number.isInteger(Number(retention[key]))))} onClick={saveRetention} className="px-4 py-2 rounded bg-indigo-600 disabled:opacity-50">Save retention policy</button>
        {dataError&&<p role="alert" className="text-rose-300">{dataError}</p>}
        {dataMessage&&<p role="status" className="text-emerald-300">{dataMessage}</p>}
      </section>

      <AccountSecurityPanel />
      {/* Hardware Profile Presets */}
      <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
        <h2 className="text-sm font-bold text-white">Model Hardware Profiles</h2>
        <p className="text-slate-400 leading-relaxed">
          Switch models to match your machine's hardware capabilities. All requests route through the centralized model gateway.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            {
              id: 'lightweight',
              title: 'Lightweight Profile',
              desc: 'Optimized for CPU laptops & low memory (<8GB RAM).',
              chat: 'qwen2.5:1.5b',
              embed: 'all-minilm',
            },
            {
              id: 'balanced',
              title: 'Balanced Profile (Default)',
              desc: 'Balanced precision and speed for standard 16GB RAM machines.',
              chat: 'qwen2.5:7b',
              embed: 'nomic-embed-text',
            },
            {
              id: 'high_quality',
              title: 'High-Quality Profile',
              desc: 'For 32GB+ RAM or dedicated GPU acceleration.',
              chat: 'qwen2.5:14b',
              embed: 'nomic-embed-text',
            },
          ].map((prof) => (
            <div
              key={prof.id}
              onClick={() => handleSwitchProfile(prof.id)}
              className={`p-4 rounded-xl border cursor-pointer transition space-y-2 flex flex-col justify-between ${
                activeProfile === prof.id
                  ? 'bg-indigo-600/10 border-indigo-500 text-white shadow-lg shadow-indigo-600/10'
                  : 'bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700'
              }`}
            >
              <div>
                <div className="flex items-center justify-between font-bold text-slate-200">
                  <span>{prof.title}</span>
                  {activeProfile === prof.id && <CheckCircle2 className="w-4 h-4 text-indigo-400" />}
                </div>
                <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">{prof.desc}</p>
              </div>

              <div className="pt-2 border-t border-slate-800 text-[10px] font-mono space-y-0.5 text-slate-500">
                <div>Chat: {prof.chat}</div>
                <div>Embed: {prof.embed}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
