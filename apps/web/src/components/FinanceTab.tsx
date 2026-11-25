import React, { useEffect, useState } from 'react';
import { Calculator, AlertTriangle, FileText, RefreshCw } from 'lucide-react';
import { api } from '../services/api';
import { FinanceLedgerPanel } from './FinanceLedgerPanel';
import { BusinessProfile, DashboardMetrics } from '../types';

export const FinanceTab: React.FC = () => {
  const [summary, setSummary] = useState<DashboardMetrics | null>(null);
  const [business, setBusiness] = useState<BusinessProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [metrics, profile] = await Promise.all([
        api.getMetrics(), api.getBusiness(),
      ]);
      setSummary(metrics);
      setBusiness(profile);
    } catch {
      setError('Recorded financial information is unavailable. No values have been estimated.');
      setSummary(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);

  const currency = business?.currency || 'USD';
  const money = (amount: number | null | undefined): string => {
    if (amount === null || amount === undefined || !Number.isFinite(amount)) return 'Not available';
    try {
      return new Intl.NumberFormat('en', {
        style: 'currency', currency,
      }).format(amount);
    } catch {
      return `${amount.toLocaleString()} ${currency}`;
    }
  };
  const isReliable = summary?.financial_data_status === 'recorded';
  const numericDisplay = (value: number | null | undefined) =>
    summary?.financial_data_status === 'needs_review' ? 'Needs review' : money(value);

  return (
    <div className="space-y-6">
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs text-slate-400">
            <Calculator className="w-4 h-4" />
            Deterministic calculation from recorded tenant data
          </div>
          <h1 className="text-xl font-bold text-white">Financial Records & Cash Runway</h1>
          <p className="text-xs text-amber-300 mt-2">
            User-recorded, not independently reconciled with bank statements or accounting ledgers.
          </p>
        </div>
        <button onClick={() => { void loadData(); }} className="text-xs text-slate-300 px-3 py-2 bg-slate-800 rounded-lg" disabled={loading}>
          <RefreshCw className="inline w-3.5 h-3.5 mr-1" /> Refresh
        </button>
      </div>

      {error && <div role="alert" className="p-4 rounded-xl border border-rose-500/30 text-rose-300 text-sm">{error}</div>}
      {!error && summary?.financial_data_status === 'needs_review' && (
        <div role="alert" className="p-4 rounded-xl border border-amber-500/30 text-amber-200 text-sm">
          <AlertTriangle className="w-4 h-4 inline mr-2" />
          Financial calculations require review. Unsupported or invalid records were excluded; do not use partial figures for decisions.
          <ul className="mt-2 list-disc pl-5">
            {(summary.financial_data_issues || []).map(issue => <li key={issue}>{issue}</li>)}
          </ul>
        </div>
      )}
      {!error && summary?.financial_data_status === 'unconfigured' && (
        <p className="p-4 rounded-xl glass-panel text-slate-300 text-sm">
          There are no configured financial records yet. No revenue or cash runway has been inferred.
        </p>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          ['Monthly Recurring Revenue', summary?.mrr],
          ['Monthly Recurring Expenses', summary?.monthly_burn],
          ['Recorded Cash Balance', summary?.cash_balance],
          ['Recorded Overdue Receivables', summary?.overdue_receivables_amount],
        ].map(([label, value]) => (
          <div key={String(label)} className="p-5 rounded-2xl glass-panel">
            <span className="text-xs uppercase font-semibold text-slate-400">{label}</span>
            <div className="text-2xl font-bold text-white font-mono mt-2">
              {loading ? 'Loading…' : !summary ? 'Unavailable' : numericDisplay(value as number | null | undefined)}
            </div>
          </div>
        ))}
      </div>

      <div className="p-6 rounded-2xl glass-panel space-y-3">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-indigo-400" />
          <h2 className="text-sm font-bold text-white">Runway and source provenance</h2>
        </div>
        <div className="text-sm text-slate-200">
          Estimated runway: {isReliable && summary?.runway_months !== null && summary?.runway_months !== undefined
            ? `${summary.runway_months} months`
            : summary?.runway_status === 'profitable' ? 'No net cash burn recorded'
            : summary?.runway_status === 'breakeven' ? 'Net burn recorded as zero'
            : 'Unavailable or requires review'}
        </div>
        <p className="text-xs text-slate-400">
          {summary?.active_customers_count ?? 0} active customer records,
          {' '}{summary?.overdue_invoices_count ?? 0} overdue invoice records.
        </p>
        <p className="text-xs text-slate-400">
          Last recorded data update: {summary?.financial_data_updated_at || 'Not available'}. Cash source: {summary?.financial_sources?.cash_balance === 'journal_with_recorded_opening_balance' ? 'Accounting journal with recorded opening balance' : 'Business profile (unreconciled)' }.
        </p>
        <p className="text-xs text-slate-400">
          {summary?.financial_data_verified ? 'Independently verified' : 'Unverified application records'}.
          See the accounting journal below for recorded historical trends and user-supplied bank statement reconciliation; no authenticated bank feed is connected.
        </p>
        {summary?.financial_record_ids && (
          <p className="text-xs text-slate-500">
            Included: {summary.financial_record_ids.active_customer_ids.length} customer records,
            {' '}{summary.financial_record_ids.expense_ids.length} expense records and
            {' '}{summary.financial_record_ids.invoice_ids.length} invoice records.
          </p>
        )}
      </div>
      <FinanceLedgerPanel currency={currency} onChange={()=>void loadData()}/>
    </div>
  );
};
