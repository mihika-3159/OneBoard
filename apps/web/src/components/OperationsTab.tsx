import React, { useEffect, useState } from 'react';
import { AlertTriangle, Clock, RefreshCw, Users } from 'lucide-react';
import { api } from '../services/api';

type Commitment = {
  id: string; title: string; counterparty: string; description: string | null;
  deadline: string; risk_level: string; status: string; evidence_source: string | null;
};
type Customer = {
  id: string; name: string; company: string | null; tier: string | null;
  mrr: number | null; status: string; health_score: number | null;
};
type Lead = {
  id: string; name: string; company: string | null; pipeline_stage: string;
  estimated_value: number | null; source: string;
};
type OperationsOverview = {
  source: string; is_demo: boolean; currency: string;
  counts: { commitments: number; customers: number; leads: number };
  limits: { per_category: number; truncated: { commitments: boolean; customers: boolean; leads: boolean } };
  commitments: Commitment[]; customers: Customer[]; leads: Lead[];
};

export const OperationsTab: React.FC = () => {
  const [overview, setOverview] = useState<OperationsOverview | null>(null);
  const [active, setActive] = useState<'commitments' | 'customers' | 'leads'>('commitments');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getOperationsOverview() as OperationsOverview;
      if (!Array.isArray(data.commitments) || !Array.isArray(data.customers) || !Array.isArray(data.leads)) {
        throw new Error('Unexpected operations API response');
      }
      setOverview(data);
    } catch (err) {
      setOverview(null);
      setError(err instanceof Error ? err.message : 'Could not load tenant operations');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadData(); }, []);
  const formatMoney = (amount: number | null): string => {
    if (amount === null || !Number.isFinite(amount)) return 'Unavailable';
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency', currency: overview?.currency || 'USD', maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return String(amount) + ' ' + (overview?.currency || '');
    }
  };
  const sections = [
    { id: 'commitments' as const, title: 'Customer Commitments', count: overview?.counts.commitments ?? 0 },
    { id: 'customers' as const, title: 'Customers', count: overview?.counts.customers ?? 0 },
    { id: 'leads' as const, title: 'Sales Pipeline', count: overview?.counts.leads ?? 0 },
  ];

  return (
    <div className="space-y-5">
      <section className="p-5 rounded-2xl glass-panel flex flex-wrap justify-between items-center gap-3">
        <div>
          <h1 className="text-xl font-bold text-white">Operations & Customer Deliverables</h1>
          <p className="text-xs text-slate-400 mt-1">
            Tenant-owned application records, not independently verified customer or contract data.
          </p>
          {overview?.is_demo && <p className="text-xs text-amber-300 mt-1">
            Demo workspace: records are fictional examples.
          </p>}
        </div>
        <button onClick={() => void loadData()} disabled={loading}
          className="px-3 py-2 rounded-xl bg-slate-800 text-slate-200 disabled:opacity-50 text-xs flex items-center gap-2">
          <RefreshCw className="w-4 h-4" /> Refresh records
        </button>
      </section>
      {error && <div role="alert" className="p-4 border border-rose-500/30 rounded-xl text-rose-300">
        Could not load operations: {error}
      </div>}
      {loading && <p role="status" className="text-slate-400">Loading operations records…</p>}
      {overview && (
        <>
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Operations sections">
            {sections.map(section => (
              <button key={section.id} role="tab"
                aria-selected={active === section.id}
                onClick={() => setActive(section.id)}
                className={'px-4 py-2 text-xs rounded-xl border ' + (
                  active === section.id
                    ? 'bg-indigo-600 text-white border-indigo-500'
                    : 'bg-slate-900 text-slate-300 border-slate-800'
                )}>
                {section.title} ({section.count})
              </button>
            ))}
          </div>
          {overview.limits.truncated[active] && (
            <p className="text-xs text-amber-300" role="status">
              Showing the first {overview.limits.per_category} records. More exist in this workspace.
            </p>
          )}
          {active === 'commitments' && (
            <section className="space-y-3" aria-label="Customer commitments">
              {overview.commitments.length === 0 && <p className="p-6 glass-panel rounded-xl text-sm text-slate-400">
                No customer commitments recorded in this workspace.
              </p>}
              {overview.commitments.map(item => (
                <article key={item.id} className="p-5 glass-panel rounded-xl space-y-2">
                  <div className="flex justify-between flex-wrap gap-2">
                    <h2 className="text-sm font-semibold text-white">{item.title}</h2>
                    <span className="text-xs text-amber-300 flex items-center gap-1">
                      {item.risk_level === 'critical' ? <AlertTriangle className="w-4 h-4" /> : <Clock className="w-4 h-4" />}
                      {item.status} · {item.risk_level}
                    </span>
                  </div>
                  <p className="text-xs text-slate-300">{item.counterparty}</p>
                  {item.description && <p className="text-xs text-slate-400">{item.description}</p>}
                  <p className="text-xs text-slate-400">
                    Deadline: {new Date(item.deadline).toLocaleDateString()}
                  </p>
                  <p className="text-xs text-slate-500">
                    {item.evidence_source ? 'User-recorded source: ' + item.evidence_source : 'Source evidence not attached'}
                  </p>
                </article>
              ))}
            </section>
          )}
          {active === 'customers' && (
            <section aria-label="Customers" className="glass-panel p-5 rounded-xl">
              {overview.customers.length === 0 ? (
                <p className="text-sm text-slate-400 flex gap-2 items-center">
                  <Users className="w-4 h-4" /> No customer records yet. Import a CSV in Integrations.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs text-left text-slate-300">
                    <thead><tr className="border-b border-slate-800">
                      <th className="p-2">Customer</th><th className="p-2">Company</th>
                      <th className="p-2">Recorded MRR</th><th className="p-2">Status</th>
                      <th className="p-2">Health evidence</th>
                    </tr></thead>
                    <tbody>{overview.customers.map(customer => (
                      <tr key={customer.id} className="border-b border-slate-800/60">
                        <td className="p-2">{customer.name}</td><td className="p-2">{customer.company || 'Not recorded'}</td>
                        <td className="p-2">{formatMoney(customer.mrr)}</td><td className="p-2">{customer.status}</td>
                        <td className="p-2">Not independently assessed</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </section>
          )}
          {active === 'leads' && (
            <section aria-label="Sales pipeline" className="space-y-3">
              {overview.leads.length === 0 && (
                <p className="p-6 glass-panel rounded-xl text-sm text-slate-400">No sales leads recorded yet.</p>
              )}
              {overview.leads.map(lead => (
                <article key={lead.id} className="glass-panel rounded-xl p-4 flex flex-wrap justify-between gap-3">
                  <div><h2 className="text-white font-semibold text-sm">{lead.name}</h2>
                    <p className="text-slate-400 text-xs">{lead.company || 'Company not recorded'}</p>
                    <p className="text-slate-500 text-xs">{lead.source} · {lead.pipeline_stage}</p>
                  </div>
                  <span className="text-xs text-slate-300">Estimated, unverified: {formatMoney(lead.estimated_value)}</span>
                </article>
              ))}
            </section>
          )}
        </>
      )}
    </div>
  );
};
