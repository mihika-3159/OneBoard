import React, { useState, useEffect } from 'react';
import {
  Link2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Folder,
  Mail,
  Calendar,
  Github,
  Database,
  MessageSquare,
  FileSpreadsheet,
} from 'lucide-react';
import { api } from '../services/api';

export const IntegrationsTab: React.FC = () => {
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [outbox, setOutbox] = useState<any[]>([]);
  const [isSyncing, setIsSyncing] = useState<string | null>(null);

  // Chat Import State
  const [chatText, setChatText] = useState(
    "Founder: We decided to keep the Growth tier at $59/mo and require 30% upfront on annual commitments.\nAction item: Audit Acme's proposal document before Friday."
  );
  const [extractedFacts, setExtractedFacts] = useState<any | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [ints, ob] = await Promise.all([api.getIntegrations(), api.getEmailOutbox()]);
      setIntegrations(ints);
      setOutbox(ob);
    } catch (e) {
      console.error('Error loading integrations', e);
    }
  };

  const handleSync = async (id: string) => {
    setIsSyncing(id);
    try {
      await api.syncIntegration(id);
      await loadData();
    } catch (e) {
      console.error('Sync failed', e);
    } finally {
      setIsSyncing(null);
    }
  };

  const handleImportChat = async () => {
    try {
      const res = await api.importChat(chatText);
      setExtractedFacts(res);
    } catch (e) {
      console.error('Chat import failed', e);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Integrations Framework
            </span>
            <span className="text-xs text-slate-400">Zero Paid Spend • Local Adapters & Official OAuth Schemas</span>
          </div>
          <h1 className="text-xl font-bold text-white">Connected Tools & Connectors</h1>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400 font-mono bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
          <span>Local First • No External Credentials Required</span>
        </div>
      </div>

      {/* Connectors Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
        {integrations.map((conn) => (
          <div key={conn.id} className="p-5 rounded-2xl glass-panel flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-bold text-white">{conn.name}</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono flex items-center gap-1 ${
                    conn.status === 'connected'
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                  }`}
                >
                  {conn.status === 'connected' ? <CheckCircle2 className="w-3 h-3" /> : <AlertCircle className="w-3 h-3" />}
                  {conn.status}
                </span>
              </div>
              <p className="text-slate-400 text-[11px]">
                {conn.is_mock ? 'Local zero-spend adapter' : 'Official OAuth schema connector'}
              </p>
            </div>

            <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
              <span className="text-[10px] text-slate-500 font-mono">
                {conn.last_sync ? `Synced: ${new Date(conn.last_sync).toLocaleTimeString()}` : 'Never'}
              </span>
              <button
                onClick={() => handleSync(conn.id)}
                disabled={isSyncing === conn.id}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
                title="Trigger synchronization"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isSyncing === conn.id ? 'animate-spin' : ''}`} />
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Lower Row: Email Outbox + ChatGPT / Claude Importer */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Email Outbox (Simulated Local Email Adapter) */}
        <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="font-bold text-white flex items-center gap-2">
              <Mail className="w-4 h-4 text-indigo-400" />
              Demo Email Outbox (Dispatched Action Audits)
            </span>
            <span className="text-slate-400 font-mono text-[11px]">{outbox.length} emails recorded</span>
          </div>

          <div className="space-y-2.5 max-h-[220px] overflow-y-auto">
            {outbox.length === 0 ? (
              <div className="text-slate-500 text-center py-6">
                No outgoing emails sent yet. Run the Overdue Invoices workflow to trigger authorized reminders.
              </div>
            ) : (
              outbox.map((mail, idx) => (
                <div key={idx} className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="flex justify-between font-semibold">
                    <span className="text-slate-200">To: {mail.recipient}</span>
                    <span className="text-emerald-400 font-mono text-[10px]">{mail.status}</span>
                  </div>
                  <div className="text-indigo-300 text-[11px] font-medium">{mail.subject}</div>
                  <div className="text-slate-400 text-[10px] truncate">{mail.body}</div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* ChatGPT / Claude Conversation Importer */}
        <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
          <div className="border-b border-slate-800 pb-3">
            <span className="font-bold text-white flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-purple-400" />
              Import ChatGPT / Claude Exported Discussions
            </span>
            <p className="text-slate-400 mt-0.5 text-[11px]">
              Extracts decisions, commitments, and tasks without connecting private API keys.
            </p>
          </div>

          <textarea
            rows={3}
            value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            className="w-full p-2.5 bg-slate-900 text-white rounded-xl border border-slate-800 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"
          />

          <div className="flex justify-between items-center">
            <span className="text-[10px] text-slate-500">Requires founder confirmation before indexing into memory</span>
            <button
              onClick={handleImportChat}
              className="px-3.5 py-2 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-xl transition"
            >
              Parse Discussion
            </button>
          </div>

          {extractedFacts && (
            <div className="p-3 rounded-xl bg-slate-900 border border-purple-500/30 space-y-1.5">
              <span className="font-semibold text-purple-300 block">Extracted Structured Facts:</span>
              <div className="text-slate-300 space-y-1">
                <div>Decisions: {extractedFacts.extracted_decisions?.join(' • ') || 'None'}</div>
                <div>Action Items: {extractedFacts.extracted_tasks?.join(' • ') || 'None'}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
