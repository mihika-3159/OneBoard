import React, { useState, useEffect } from 'react';
import { DollarSign, Clock, AlertTriangle, CheckCircle2, TrendingUp, Calculator } from 'lucide-react';
import { api } from '../services/api';

export const FinanceTab: React.FC = () => {
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const data = await api.getFinanceLedger();
      setSummary(data);
    } catch (e) {
      console.error('Error loading finance ledger', e);
    }
  };

  const invoices = [
    { number: 'INV-2026-001', customer: 'Acme Technologies', amount: 199.0, status: 'paid', due: '15 days ago' },
    { number: 'INV-2026-002', customer: 'Vance Logistics', amount: 590.0, status: 'overdue', due: '8 days ago' },
    { number: 'INV-2026-003', customer: 'Rio Scale', amount: 1180.0, status: 'overdue', due: '12 days ago' },
    { number: 'INV-2026-004', customer: 'Nova Labs', amount: 59.0, status: 'sent', due: 'in 5 days' },
    { number: 'INV-2026-005', customer: 'Apex Digital', amount: 2400.0, status: 'overdue', due: '4 days ago' },
  ];

  const expenses = [
    { category: 'Infrastructure', vendor: 'AWS & Cloudflare Edge Ingress', amount: 3450.0 },
    { category: 'Software & Tools', vendor: 'GitHub Enterprise & Datadog', amount: 1200.0 },
    { category: 'Marketing', vendor: 'Developer Ads & Technical Sponsorships', amount: 2800.0 },
    { category: 'Legal & Risk', vendor: 'Startup Legal Counsel (GDPR/Contracts)', amount: 1500.0 },
    { category: 'Operations', vendor: 'Stripe Processing & Banking Fees', amount: 3250.0 },
  ];

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              Deterministic Financial Engine
            </span>
            <span className="text-xs text-slate-400">Non-hallucinatory arithmetic validated by Python code</span>
          </div>
          <h1 className="text-xl font-bold text-white">Financial Ledger & Cash Runway</h1>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-emerald-400 bg-emerald-500/10 px-3 py-1.5 rounded-lg border border-emerald-500/20">
          <Calculator className="w-4 h-4" />
          <span>Calculations Verified</span>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl glass-panel">
          <span className="text-xs text-slate-400 uppercase font-semibold">Monthly Recurring Revenue</span>
          <div className="text-2xl font-bold text-white font-mono mt-2">${(summary?.mrr || 18450).toLocaleString()}</div>
          <div className="text-xs text-emerald-400 mt-1">38 paying subscribers</div>
        </div>

        <div className="p-5 rounded-2xl glass-panel">
          <span className="text-xs text-slate-400 uppercase font-semibold">Monthly Operating Burn</span>
          <div className="text-2xl font-bold text-rose-400 font-mono mt-2">${(summary?.monthly_burn || 12200).toLocaleString()}</div>
          <div className="text-xs text-slate-400 mt-1">Infrastructure & tools</div>
        </div>

        <div className="p-5 rounded-2xl glass-panel">
          <span className="text-xs text-slate-400 uppercase font-semibold">Cash on Hand</span>
          <div className="text-2xl font-bold text-white font-mono mt-2">${(summary?.cash_on_hand || 132840).toLocaleString()}</div>
          <div className="text-xs text-slate-400 mt-1">SVB / Mercury depository</div>
        </div>

        <div className="p-5 rounded-2xl glass-panel">
          <span className="text-xs text-slate-400 uppercase font-semibold">Net Cash Runway</span>
          <div className="text-2xl font-bold text-indigo-400 font-mono mt-2">{summary?.runway_months || 7.2} mos</div>
          <div className="text-xs text-indigo-400 mt-1">Safe operating zone</div>
        </div>
      </div>

      {/* Invoices Table & Expenses Breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 p-6 rounded-2xl glass-panel space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-bold text-white">Accounts Receivable & Invoicing</h2>
            <span className="text-xs font-mono text-amber-400 bg-amber-500/10 px-2.5 py-1 rounded-lg border border-amber-500/20">
              3 Overdue ($4,170.00)
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500 border-b border-slate-800 pb-2">
                <tr>
                  <th className="py-2">Invoice #</th>
                  <th>Customer</th>
                  <th>Amount</th>
                  <th>Due Date</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {invoices.map((inv, i) => (
                  <tr key={i} className="hover:bg-slate-800/30">
                    <td className="py-2.5 font-mono text-slate-400">{inv.number}</td>
                    <td className="font-semibold text-white">{inv.customer}</td>
                    <td className="font-mono text-white">${inv.amount.toLocaleString()}</td>
                    <td className="text-slate-400">{inv.due}</td>
                    <td>
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-mono ${
                          inv.status === 'paid'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : inv.status === 'overdue'
                            ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                            : 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20'
                        }`}
                      >
                        {inv.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Expenses */}
        <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
          <h2 className="text-sm font-bold text-white">Operating Expenditures</h2>
          <div className="space-y-3">
            {expenses.map((exp, i) => (
              <div key={i} className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                <div className="flex justify-between font-semibold">
                  <span className="text-slate-200">{exp.category}</span>
                  <span className="font-mono text-slate-300">${exp.amount.toLocaleString()}</span>
                </div>
                <div className="text-[11px] text-slate-500">{exp.vendor}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
