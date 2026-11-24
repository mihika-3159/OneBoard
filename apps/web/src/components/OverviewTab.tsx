import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  DollarSign,
  Clock,
  AlertTriangle,
  ShieldCheck,
  ArrowRight,
  Sparkles,
} from 'lucide-react';
import { api } from '../services/api';
import { DashboardMetrics, BusinessProfile, ProactiveAlert } from '../types';

interface OverviewTabProps {
  onNavigate: (tab: string) => void;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({ onNavigate }) => {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [business, setBusiness] = useState<BusinessProfile | null>(null);
  const [alerts, setAlerts] = useState<ProactiveAlert[]>([]);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [m, b, a] = await Promise.all([
        api.getMetrics(),
        api.getBusiness(),
        api.getAlerts(),
      ]);
      setMetrics(m);
      setBusiness(b);
      setAlerts(a);
      setLoadError(false);
    } catch (e) {
      setLoadError(true);
      setMetrics(null);
      console.error('Error loading dashboard data', e);
    }
  };

  const currency = business?.currency || 'USD';
  const formatMoney = (amount: number): string => {
    try {
      return new Intl.NumberFormat('en', {
        style: 'currency', currency, maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return `${amount.toLocaleString()} ${currency}`;
    }
  };
  const figuresAvailable = metrics !== null && metrics.financial_data_status === 'recorded';

  return (
    <div className="space-y-6">
      {/* Top Banner / Welcome */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-6 rounded-2xl glass-panel relative overflow-hidden">
        <div className="relative z-10">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Dubai AI Agents Championship 2026–27
            </span>
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              9 Adviser Roles Available
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white">
            {business?.name || 'Your Workspace'} Operating System
          </h1>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Run a company of one with the capabilities of a team. Continuous business memory, visual workflow studio, and empirical outcome accountability.
          </p>
        </div>

        <div className="flex items-center gap-3 relative z-10">
          <button
            onClick={() => onNavigate('boardroom')}
            className="flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-xl transition shadow-lg shadow-indigo-600/20"
          >
            <Sparkles className="w-4 h-4" />
            Convene Council
          </button>

        </div>
      </div>

      {loadError && (
        <div role="alert" className="p-4 border border-rose-500/30 rounded-xl text-rose-300 text-sm">
          Dashboard records could not be loaded. No financial amounts have been inferred.
        </div>
      )}
      {metrics && (
        <div className="p-3 border border-amber-500/20 rounded-xl text-amber-300 text-xs">
          Financial figures are user-recorded and not independently reconciled.
          {metrics.financial_data_status === 'needs_review'
            ? ' Invalid or ambiguous entries require correction before any runway assessment.'
            : ''}
        </div>
      )}
      {/* Proactive Hazards & Alerts Banner */
      {alerts.length > 0 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400 mt-0.5">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-amber-200">
                Proactive Executive Alert: {alerts[0].title}
              </div>
              <div className="text-xs text-amber-300/80 mt-0.5">
                {alerts[0].description}
              </div>
            </div>
          </div>
          <button
            onClick={() => onNavigate('operations')}
            className="self-start md:self-auto text-xs font-semibold px-3 py-1.5 bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded-lg transition border border-amber-500/30 flex items-center gap-1.5"
          >
            View Commitment <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl glass-panel glass-panel-hover transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Monthly Recurring Rev</span>
            <div className="p-2 rounded-xl bg-emerald-500/10 text-emerald-400">
              <TrendingUp className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-white mt-3 font-mono">
            {metrics ? formatMoney(metrics.mrr) : 'Unavailable'}
          </div>
          <div className="text-xs text-emerald-400 flex items-center gap-1 mt-1 font-medium">
            {metrics ? `${metrics.active_customers_count} active customer records (unverified)` : 'No source records loaded'}
          </div>
        </div>

        <div className="p-5 rounded-2xl glass-panel glass-panel-hover transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Net Cash Runway</span>
            <div className="p-2 rounded-xl bg-indigo-500/10 text-indigo-400">
              <Clock className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-white mt-3 font-mono">
            {figuresAvailable && metrics?.runway_months !== null && metrics?.runway_months !== undefined
              ? `${metrics.runway_months} months` : 'Unavailable'}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Cash: {metrics ? formatMoney(metrics.cash_balance) : 'Unavailable'} • Burn: {metrics ? formatMoney(metrics.monthly_burn) : 'Unavailable'}/mo
          </div>
        </div>

        <div className="p-5 rounded-2xl glass-panel glass-panel-hover transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Overdue Receivables</span>
            <div className="p-2 rounded-xl bg-amber-500/10 text-amber-400">
              <DollarSign className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-white mt-3 font-mono">
            {metrics ? formatMoney(metrics.overdue_receivables_amount) : 'Unavailable'}
          </div>
          <div className="text-xs text-amber-400 mt-1 flex items-center justify-between">
            <span>{metrics?.overdue_invoices_count ?? 0} overdue invoice records</span>
            <button onClick={() => onNavigate('workflows')} className="underline hover:text-amber-300">Run Recovery</button>
          </div>
        </div>

        <div className="p-5 rounded-2xl glass-panel glass-panel-hover transition">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Accountability Index</span>
            <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400">
              <ShieldCheck className="w-4 h-4" />
            </div>
          </div>
          <div className="text-2xl font-bold text-white mt-3 font-mono">
            Not assessed
          </div>
          <div className="text-xs text-purple-400 mt-1">
            No independently verified outcome score yet
          </div>
        </div>
      </div>

      {/* Main Grid: Revenue Trend & Executive Council Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Historical data does not exist in these snapshots. Never draw a
            time series from fabricated months or repeated current figures. */}
        <div className="lg:col-span-2 p-6 rounded-2xl glass-panel">
          <h2 className="text-base font-bold text-white">Financial Records & Provenance</h2>
          <p className="text-xs text-slate-400 mt-2">
            Historical financial trajectory is unavailable. This API provides a current,
            user-recorded snapshot rather than a dated, independently reconciled ledger.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-5 text-sm">
            <p className="text-slate-200">Recurring revenue: {metrics ? formatMoney(metrics.mrr) : 'Unavailable'}</p>
            <p className="text-slate-200">Recurring expenses: {metrics ? formatMoney(metrics.monthly_burn) : 'Unavailable'}</p>
            <p className="text-slate-200">Source records: {metrics?.financial_record_ids?.active_customer_ids.length ?? 0} active customers</p>
            <p className="text-slate-200">Last record update: {metrics?.financial_data_updated_at || 'Not available'}</p>
          </div>
        </div>

        {/* 9-Role Executive Council Snapshot */}
        <div className="p-6 rounded-2xl glass-panel space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white">AI Executive Council</h2>
            <button
              onClick={() => onNavigate('boardroom')}
              className="text-xs font-semibold text-indigo-400 hover:text-indigo-300"
            >
              Enter Boardroom →
            </button>
          </div>
          <p className="text-xs text-slate-400">
            9 coordinated specialists operating on shared business memory with accountable deliberation.
          </p>

          <div className="space-y-2.5">
            {[
              { role: 'Chief of Staff', dept: 'Executive Office', status: 'Ready for Agenda' },
              { role: 'Finance Adviser', dept: 'Finance', status: 'Review recorded financials' },
              { role: 'Marketing Adviser', dept: 'Growth', status: 'Analysis not verified' },
              { role: 'Operations Adviser', dept: 'Operations', status: 'Review workflow runs' },
              { role: 'Technology Adviser', dept: 'Engineering', status: 'Availability unverified' },
            ].map((adv) => (
              <div key={adv.role} className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800/80 flex items-center justify-between">
                <div>
                  <div className="text-xs font-semibold text-slate-200">{adv.role}</div>
                  <div className="text-[11px] text-slate-500">{adv.dept}</div>
                </div>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/50">
                  {adv.status}
                </span>
              </div>
            ))}
          </div>

          <button
            onClick={() => onNavigate('command')}
            className="w-full py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-xl border border-slate-700/60 transition flex items-center justify-center gap-2"
          >
            Ask Founder Command Center
          </button>
        </div>
      </div>
    </div>
  );
};
