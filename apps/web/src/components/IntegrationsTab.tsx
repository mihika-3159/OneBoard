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
import { ProviderLifecyclePanel } from './ProviderLifecyclePanel';

export const IntegrationsTab: React.FC = () => {
  const [integrations, setIntegrations] = useState<any[]>([]);
  const [outbox, setOutbox] = useState<any[]>([]);
  const [isSyncing, setIsSyncing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading,setLoading]=useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<any | null>(null);
  const [csvBusy, setCsvBusy] = useState(false);
  const [csvKey, setCsvKey] = useState<string>(crypto.randomUUID().replace(/-/g, '_'));

  // Chat Import State
  const [chatText, setChatText] = useState('');
  const [extractedFacts, setExtractedFacts] = useState<any | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [ints, ob] = await Promise.all([api.getIntegrations(), api.getEmailOutbox()]);
      // The API returns an envelope { is_simulated, channel, outbox }, not an array.
      setIntegrations(Array.isArray(ints) ? ints : []);
      setOutbox(Array.isArray(ob?.outbox) ? ob.outbox : []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Integrations are unavailable. Please retry.');
      setIntegrations([]);
      setOutbox([]);
    } finally {setLoading(false)}
  };

  const handleSync = async (id: string) => {
    setIsSyncing(id);
    try {
      const result = await api.syncIntegration(id);
      await loadData();
      if (result.is_simulated) {
        setNotice('Sandbox refresh only. No external provider was contacted and no live records were synced.');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Sandbox sync failed. Please retry.');
    } finally {
      setIsSyncing(null);
    }
  };

  const handleImportChat = async () => {
    try {
      const res = await api.importChat(chatText);
      setExtractedFacts(res);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Chat import failed. Please retry.');
    }
  };

  const handleCustomerCSV = async (dryRun: boolean) => {
    if (!csvFile || (!dryRun && !csvPreview)) return;
    setCsvBusy(true);
    try {
      if (csvFile.size > 1024 * 1024) {
        throw new Error('CSV exceeds the 1 MiB limit');
      }
      const result = await api.importLocalCustomers(
        await csvFile.text(), csvKey, csvFile.name, dryRun
      );
      if (dryRun) {
        setCsvPreview(result);
        setNotice(`Validated ${result.rows_validated} customer rows. Nothing has been imported yet.`);
      } else {
        setNotice(`${result.rows_imported} user-supplied customers ${result.status}. Not independently CRM-verified.`);
        setCsvPreview(null);
        setCsvFile(null);
        setCsvKey(crypto.randomUUID().replace(/-/g, '_'));
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'CSV validation or import failed');
    } finally {
      setCsvBusy(false);
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
            <span className="text-xs text-slate-400">Local sandbox adapters and optional configured external adapters</span>
          </div>
          <h1 className="text-xl font-bold text-white">Integration Sandbox & Connector Readiness</h1>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-400 font-mono bg-slate-900/60 px-3 py-1.5 rounded-lg border border-slate-800">
          <span>Local First • No External Credentials Required</span>
        </div>
      </div>

      {loading&&<p role="status" aria-live="polite">Loading integrations and outbox…</p>}
      {!loading&&!error&&!integrations.length&&<p role="status">No sandbox connector records.</p>}
      {error && (
        <div role="alert" className="p-3 border border-rose-500/40 rounded-xl text-rose-300 text-sm flex justify-between items-center">
          <span>{error}</span>
          <button onClick={() => { void loadData(); }} className="underline">Retry</button>
        </div>
      )}
      {notice && <div role="status" className="p-3 border border-amber-500/30 rounded-xl text-amber-200 text-xs">{notice}</div>}
      <section className="p-5 rounded-2xl glass-panel space-y-3" aria-label="Import customer CSV">
        <h2 className="text-sm font-bold text-white">Import user-supplied customer CSV</h2>
        <p className="text-xs text-slate-400">
          Actual tenant-owned import, not a CRM connection. Required columns: name,mrr.
          Optional: company,email,status. Maximum 250 rows or 1 MiB. Validate first,
          then explicitly confirm the write. No external provider is contacted.
        </p>
        <input
          type="file" accept=".csv,text/csv" aria-label="Customer CSV file"
          className="text-xs text-slate-300"
          onChange={event => {
            setCsvFile(event.target.files?.[0] || null);
            setCsvPreview(null);
            setCsvKey(crypto.randomUUID().replace(/-/g, '_'));
          }}
        />
        <div className="flex gap-2">
          <button
            disabled={!csvFile || csvBusy}
            onClick={() => void handleCustomerCSV(true)}
            className="rounded-lg bg-indigo-600 px-3 py-2 text-xs text-white disabled:opacity-50"
          >Validate CSV</button>
          <button
            disabled={!csvPreview || csvBusy}
            onClick={() => void handleCustomerCSV(false)}
            className="rounded-lg bg-slate-700 px-3 py-2 text-xs text-white disabled:opacity-50"
          >Confirm Import</button>
        </div>
        {csvPreview && <p role="status" className="text-xs text-emerald-300">
          {csvPreview.rows_validated} rows validated. No records written yet.
        </p>}
      </section>
      <ProviderLifecyclePanel />
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
                {conn.is_mock ? 'Sandbox only: no live provider connection' : 'Use the external provider panel to inspect live authorization'}
              </p>
            </div>

            <div className="pt-2 border-t border-slate-800 flex items-center justify-between">
              <span className="text-[10px] text-slate-500 font-mono">
                {conn.last_sync ? `Sandbox refresh: ${new Date(conn.last_sync).toLocaleTimeString()}` : 'No provider sync'}
              </span>
              <button
                onClick={() => handleSync(conn.id)}
                disabled={isSyncing === conn.id || !conn.is_mock}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition"
                title={conn.is_mock ? 'Refresh synthetic sandbox only' : 'Use the external provider panel to inspect synchronization'}
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
              Sandbox Email Outbox (No External Delivery)
            </span>
            <span className="text-slate-400 font-mono text-[11px]">{outbox.length} simulated messages recorded</span>
          </div>

          <div className="space-y-2.5 max-h-[220px] overflow-y-auto">
            {outbox.length === 0 ? (
              <div className="text-slate-500 text-center py-6">
                No sandbox messages recorded. This adapter does not deliver emails.
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
              Extracts keyword-matched candidate sentences only. These are not verified facts or imported records.
            </p>
          </div>

          <textarea
            rows={3}
            aria-label="Conversation text to import" value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            className="w-full p-2.5 bg-slate-900 text-white rounded-xl border border-slate-800 focus:outline-none focus:border-indigo-500 font-mono text-[11px]"
          />

          <div className="flex justify-between items-center">
            <span className="text-[10px] text-slate-500">This action only parses text; it does not index records</span>
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
