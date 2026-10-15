import React, { useState, useEffect } from 'react';
import {
  Search,
  Share2,
  AlertTriangle,
  Upload,
  CheckCircle2,
  FileText,
  Sparkles,
  Layers,
  ArrowRight,
} from 'lucide-react';
import { api } from '../services/api';
import { MemoryConflict } from '../types';

export const BusinessMemoryTab: React.FC = () => {
  const [activeSubTab, setActiveSubTab] = useState<'search' | 'graph' | 'conflicts' | 'upload'>('conflicts');
  const [searchQuery, setSearchQuery] = useState('pricing for growth tier');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] });
  const [conflicts, setConflicts] = useState<MemoryConflict[]>([]);
  const [isResolving, setIsResolving] = useState<string | null>(null);

  // File Upload State
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    loadMemoryData();
  }, []);

  const loadMemoryData = async () => {
    try {
      const [g, c] = await Promise.all([api.getMemoryGraph(), api.getConflicts()]);
      setGraphData(g);
      setConflicts(c);
    } catch (e) {
      console.error('Error loading memory data', e);
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const res = await api.searchMemory(searchQuery);
      setSearchResults(res.results || []);
    } catch (e) {
      console.error('Search failed', e);
    } finally {
      setIsSearching(false);
    }
  };

  const handleResolveConflict = async (conflictId: string) => {
    setIsResolving(conflictId);
    try {
      await api.resolveConflict(
        conflictId,
        'Confirmed: Public tier remains $59/mo, Acme contract grandfathered at promotional $49/mo.',
        'custom'
      );
      await loadMemoryData();
    } catch (e) {
      console.error('Conflict resolution failed', e);
    } finally {
      setIsResolving(null);
    }
  };

  const handleFileUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) return;

    setIsUploading(true);
    setUploadStatus(null);
    const formData = new FormData();
    formData.append('file', uploadFile);

    try {
      const res = await fetch('/api/memory/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        setUploadStatus(`Document '${data.title}' ingested into memory (${data.chunks} chunks indexed).`);
        setUploadFile(null);
        await loadMemoryData();
      } else {
        setUploadStatus(`Error: ${data.detail}`);
      }
    } catch (err: any) {
      setUploadStatus(`Upload failed: ${err.message}`);
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              3-Tier Memory Engine
            </span>
            <span className="text-xs text-slate-400">Structured Data • Semantic Chunks • Entity Relationship Graph</span>
          </div>
          <h1 className="text-xl font-bold text-white">Business Memory & Conflict Detection</h1>
        </div>

        {/* Sub-tabs switch */}
        <div className="flex rounded-xl bg-slate-900 p-1 border border-slate-800 text-xs font-semibold">
          {[
            { id: 'conflicts', label: 'Conflict Detector', badge: conflicts.filter((c) => c.status === 'unresolved').length },
            { id: 'graph', label: 'Relationship Graph' },
            { id: 'search', label: 'Semantic Search' },
            { id: 'upload', label: 'Ingest Document' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveSubTab(tab.id as any)}
              className={`px-3 py-1.5 rounded-lg transition flex items-center gap-1.5 ${
                activeSubTab === tab.id ? 'bg-indigo-600 text-white shadow-md' : 'text-slate-400 hover:text-white'
              }`}
            >
              {tab.label}
              {tab.badge !== undefined && tab.badge > 0 && (
                <span className="w-4 h-4 rounded-full bg-amber-500 text-slate-950 text-[10px] flex items-center justify-center font-bold">
                  {tab.badge}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 1. Conflict Detection View (Demo Scenario A) */}
      {activeSubTab === 'conflicts' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
            <span className="font-bold block mb-0.5">Automated Discrepancy & Provenance Audit:</span>
            When multiple connected documents disagree, OneBoard prevents silent data overwrites by classifying the discrepancy and requesting founder ratification.
          </div>

          <div className="grid grid-cols-1 gap-4">
            {conflicts.map((conf) => (
              <div
                key={conf.id}
                className="p-6 rounded-2xl glass-panel border border-amber-500/30 space-y-4 text-xs"
              >
                <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    <span className="text-sm font-bold text-white">{conf.entity_name}</span>
                  </div>
                  <span
                    className={`px-2.5 py-0.5 rounded-full text-[10px] font-mono ${
                      conf.status === 'resolved'
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                    }`}
                  >
                    {conf.status}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                    <span className="text-slate-500 text-[10px] uppercase font-mono">Source A (Official Catalog)</span>
                    <div className="font-semibold text-slate-200">{conf.source_a.name}</div>
                    <div className="text-indigo-400 font-mono text-sm">{conf.source_a.value}</div>
                  </div>

                  <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                    <span className="text-slate-500 text-[10px] uppercase font-mono">Source B (Customer Contract)</span>
                    <div className="font-semibold text-slate-200">{conf.source_b.name}</div>
                    <div className="text-amber-400 font-mono text-sm">{conf.source_b.value}</div>
                  </div>
                </div>

                <div className="space-y-1.5 text-slate-300">
                  <span className="font-semibold text-slate-200">Discrepancy Analysis:</span>
                  <p className="text-slate-400 leading-relaxed">{conf.explanation}</p>
                </div>

                <div className="p-3 rounded-xl bg-indigo-950/20 border border-indigo-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div>
                    <span className="font-semibold text-indigo-300 block">Proposed Autonomous Resolution:</span>
                    <span className="text-slate-300">{conf.suggested_resolution}</span>
                  </div>
                  {conf.status === 'unresolved' && (
                    <button
                      onClick={() => handleResolveConflict(conf.id)}
                      disabled={isResolving === conf.id}
                      className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl transition whitespace-nowrap self-start sm:self-auto"
                    >
                      {isResolving === conf.id ? 'Applying...' : 'Approve Resolution'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 2. Relationship Memory Graph View */}
      {activeSubTab === 'graph' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl glass-panel text-xs text-slate-400">
            Graph linkages connecting products, customers, contracts, campaigns, and tasks across memory.
          </div>

          <div className="p-6 rounded-2xl glass-panel space-y-4">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Active Entity Relationships ({graphData.links?.length || 0} Edges)
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-xs">
              {graphData.links?.map((lnk, idx) => (
                <div key={idx} className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-200">{lnk.source}</span>
                    <span className="px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-400 font-mono text-[10px]">
                      {lnk.relationship}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-slate-400 text-[11px]">
                    <ArrowRight className="w-3 h-3 text-slate-500" />
                    <span>{lnk.target}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 3. Semantic Memory Search */}
      {activeSubTab === 'search' && (
        <div className="space-y-4">
          <div className="p-4 rounded-2xl glass-panel flex items-center gap-3">
            <Search className="w-5 h-5 text-indigo-400 shrink-0" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Query semantic memory (e.g. 'pricing for growth tier', 'webhook exporter requirements')..."
              className="flex-1 bg-transparent text-sm text-white focus:outline-none"
            />
            <button
              onClick={handleSearch}
              disabled={isSearching}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition"
            >
              {isSearching ? 'Searching...' : 'Hybrid Search'}
            </button>
          </div>

          <div className="space-y-3">
            {searchResults.map((res, i) => (
              <div key={i} className="p-4 rounded-xl glass-panel space-y-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-indigo-300 flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-indigo-400" />
                    Citation Source: {res.source_title}
                  </span>
                  <span className="font-mono text-slate-500 text-[10px]">Score: {res.score}</span>
                </div>
                <p className="text-slate-300 leading-relaxed whitespace-pre-wrap">{res.content}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 4. Ingest Document View */}
      {activeSubTab === 'upload' && (
        <div className="p-6 rounded-2xl glass-panel max-w-xl space-y-4 text-xs">
          <div>
            <h3 className="text-base font-bold text-white">Ingest Business Documentation</h3>
            <p className="text-slate-400 mt-0.5">
              Supports CSV spreadsheets, Excel (.xlsx), PDF reports, TXT, Markdown, and JSON. Extracted text is chunked and indexed into local semantic memory.
            </p>
          </div>

          <form onSubmit={handleFileUpload} className="space-y-3">
            <div className="border-2 border-dashed border-slate-700 rounded-xl p-6 text-center space-y-2">
              <Upload className="w-8 h-8 text-indigo-400 mx-auto" />
              <input
                type="file"
                accept=".csv,.xlsx,.xls,.pdf,.txt,.md,.json"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                className="text-xs text-slate-400 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-indigo-600 file:text-white hover:file:bg-indigo-500 cursor-pointer"
              />
              <span className="block text-[11px] text-slate-500">Max size 25MB. Local parsing only.</span>
            </div>

            {uploadStatus && (
              <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 text-slate-300">
                {uploadStatus}
              </div>
            )}

            <button
              type="submit"
              disabled={isUploading || !uploadFile}
              className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white font-semibold rounded-xl transition"
            >
              {isUploading ? 'Extracting & Indexing...' : 'Index Document into Business Memory'}
            </button>
          </form>
        </div>
      )}
    </div>
  );
};
