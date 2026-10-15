import React, { useState, useEffect } from 'react';
import {
  TrendingUp,
  DollarSign,
  Clock,
  AlertTriangle,
  Users,
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip } from 'recharts';
import { api } from '../services/api';
import { DashboardMetrics, BusinessProfile, ProactiveAlert } from '../types';

interface OverviewTabProps {
  onNavigate: (tab: string) => void;
}

export const OverviewTab: React.FC<OverviewTabProps> = ({ onNavigate }) => {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [business, setBusiness] = useState<BusinessProfile | null>(null);
  const [alerts, setAlerts] = useState<ProactiveAlert[]>([]);
  const [isResetting, setIsResetting] = useState(false);

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
    } catch (e) {
      console.error('Error loading dashboard data', e);
    }
  };

  const handleResetDemo = async () => {
    setIsResetting(true);
    await api.resetDemo();
    await loadData();
    setIsResetting(false);
  };

  const chartData = [
    { month: 'Nov', revenue: 11200, burn: 10500 },
    { month: 'Dec', revenue: 13400, burn: 11100 },
    { month: 'Jan', revenue: 15100, burn: 11800 },
    { month: 'Feb', revenue: 16900, burn: 12000 },
    { month: 'Mar', revenue: 17800, burn: 12100 },
    { month: 'Apr', revenue: metrics?.mrr || 18450, burn: metrics?.monthly_burn || 12200 },
  ];

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
              9-Agent Council Active
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight text-white">
            {business?.name || 'Northstar Studio'} Operating System
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
          <button
            onClick={handleResetDemo}
            disabled={isResetting}
            className="flex items-center gap-2 px-3.5 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-sm font-medium rounded-xl border border-slate-700/60 transition"
            title="Reset Northstar Studio demo scenario fixtures"
          >
            <RefreshCw className={`w-4 h-4 ${isResetting ? 'animate-spin' : ''}`} />
            Reset Demo
          </button>
        </div>
      </div>

      {/* Proactive Hazards & Alerts Banner */}
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
            ${(metrics?.mrr || 18450).toLocaleString()}
          </div>
          <div className="text-xs text-emerald-400 flex items-center gap-1 mt-1 font-medium">
            +14.2% vs last month • 38 active SaaS accounts
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
            {metrics?.runway_months || 7.2} <span className="text-sm font-normal text-slate-400">months</span>
          </div>
          <div className="text-xs text-slate-400 mt-1">
            Cash: ${(metrics?.cash_balance || 132840).toLocaleString()} • Burn: ${(metrics?.monthly_burn || 12200).toLocaleString()}/mo
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
            ${(metrics?.overdue_receivables_amount || 4170).toLocaleString()}
          </div>
          <div className="text-xs text-amber-400 mt-1 flex items-center justify-between">
            <span>{metrics?.overdue_invoices_count || 3} overdue accounts</span>
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
            91.4%
          </div>
          <div className="text-xs text-purple-400 mt-1">
            Empirical Council prediction & action score
          </div>
        </div>
      </div>

      {/* Main Grid: Revenue Trend & Executive Council Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Revenue & Burn Trend Chart */}
        <div className="lg:col-span-2 p-6 rounded-2xl glass-panel">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-bold text-white">Financial Trajectory & Working Capital</h2>
              <p className="text-xs text-slate-400">Monthly Recurring Revenue vs Operating Expenditures</p>
            </div>
            <span className="text-xs font-mono text-indigo-400 bg-indigo-500/10 px-2.5 py-1 rounded-lg border border-indigo-500/20">
              Target: $25k MRR
            </span>
          </div>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="colorRev" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorBurn" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.2} />
                    <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="month" stroke="#64748b" fontSize={12} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={12} tickLine={false} tickFormatter={(val) => `$${val / 1000}k`} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0f172a', borderColor: '#334155', borderRadius: '0.75rem', fontSize: '12px' }}
                />
                <Area type="monotone" dataKey="revenue" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorRev)" name="MRR ($)" />
                <Area type="monotone" dataKey="burn" stroke="#f43f5e" strokeWidth={2} fillOpacity={1} fill="url(#colorBurn)" name="Burn ($)" />
              </AreaChart>
            </ResponsiveContainer>
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
              { role: 'Finance Adviser', dept: 'Finance', status: 'Runway: 7.2mo' },
              { role: 'Marketing Adviser', dept: 'Growth', status: 'Auditing CAC' },
              { role: 'Operations Adviser', dept: 'Operations', status: '1 Workflow Paused' },
              { role: 'Technology Adviser', dept: 'Engineering', status: 'Exporter PR #14' },
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
