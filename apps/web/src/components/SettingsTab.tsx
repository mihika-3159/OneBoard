import React, { useState, useEffect } from 'react';
import { Cpu, CheckCircle2, AlertTriangle, Zap, Server, ShieldCheck, RefreshCw } from 'lucide-react';
import { api } from '../services/api';
import { GatewayStatus } from '../types';

export const SettingsTab: React.FC = () => {
  const [gatewayStatus, setGatewayStatus] = useState<GatewayStatus | null>(null);
  const [activeProfile, setActiveProfile] = useState('balanced');
  const [benchmarkResult, setBenchmarkResult] = useState<any | null>(null);
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);

  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    try {
      const s = await api.getGatewayStatus();
      setGatewayStatus(s);
      setActiveProfile(s.active_profile || 'balanced');
    } catch (e) {
      console.error('Error loading gateway status', e);
    }
  };

  const handleSwitchProfile = async (p: string) => {
    setIsUpdating(true);
    try {
      await api.switchProfile(p);
      setActiveProfile(p);
      await loadStatus();
    } catch (e) {
      console.error('Failed to switch profile', e);
    } finally {
      setIsUpdating(false);
    }
  };

  const handleBenchmark = async () => {
    setIsBenchmarking(true);
    setBenchmarkResult(null);
    try {
      const res = await api.benchmarkGateway();
      setBenchmarkResult(res);
    } catch (e) {
      console.error('Benchmark failed', e);
    } finally {
      setIsBenchmarking(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Centralized AI Gateway
            </span>
            <span className="text-xs text-slate-400">Zero Cloud Subscriptions • Local Ollama Gateway</span>
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

      {/* Ollama Connection Card */}
      <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2.5">
            <Server className="w-5 h-5 text-indigo-400" />
            <div>
              <span className="text-sm font-bold text-white block">Local Ollama Inference Daemon</span>
              <span className="text-slate-400 font-mono text-[11px]">{gatewayStatus?.base_url || 'http://127.0.0.1:11434'}</span>
            </div>
          </div>
          <span
            className={`px-3 py-1 rounded-full text-xs font-mono font-semibold flex items-center gap-1.5 ${
              gatewayStatus?.status === 'connected'
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
            }`}
          >
            {gatewayStatus?.status === 'connected' ? (
              <>
                <CheckCircle2 className="w-3.5 h-3.5" /> Connected ({gatewayStatus?.latency_ms}ms)
              </>
            ) : (
              <>
                <AlertTriangle className="w-3.5 h-3.5" /> Offline Mode (High-Fidelity Simulation Active)
              </>
            )}
          </span>
        </div>

        {gatewayStatus?.offline_mode && (
          <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-300 leading-relaxed">
            <span className="font-semibold block mb-0.5">Local Daemon Notice:</span>
            Ollama is not running on port 11434. The application is operating seamlessly using the deterministic local reasoning simulator. To enable real open-weight inference, install and launch Ollama:
            <code className="block mt-2 p-2 rounded-lg bg-slate-900 border border-slate-800 font-mono text-[11px] text-white">
              ollama run qwen2.5:7b
            </code>
          </div>
        )}

        <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="text-slate-400">
            Available Local Models: <span className="text-white font-mono">{gatewayStatus?.available_models?.join(', ') || 'None (using local fallback adapter)'}</span>
          </div>
          <button
            onClick={handleBenchmark}
            disabled={isBenchmarking}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl transition shadow-md shadow-indigo-600/20"
          >
            <Zap className="w-3.5 h-3.5" />
            {isBenchmarking ? 'Testing...' : 'Run Compatibility Benchmark'}
          </button>
        </div>

        {benchmarkResult && (
          <div className="p-3.5 rounded-xl bg-slate-900 border border-indigo-500/30 text-slate-300 space-y-1">
            <div className="flex justify-between font-semibold">
              <span className="text-indigo-300">Benchmark Completed:</span>
              <span className="font-mono text-emerald-400">{benchmarkResult.total_latency_ms} ms</span>
            </div>
            <div className="text-[11px] text-slate-400 font-mono">
              Model: {benchmarkResult.model} • Simulated: {String(benchmarkResult.simulated)}
            </div>
          </div>
        )}
      </div>

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
