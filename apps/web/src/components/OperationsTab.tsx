import React, { useState, useEffect } from 'react';
import { Users, AlertTriangle, CheckCircle2, Clock, Mail, ShieldAlert } from 'lucide-react';
import { api } from '../services/api';

export const OperationsTab: React.FC = () => {
  const [contacts, setContacts] = useState<any[]>([]);
  const [subTab, setSubTab] = useState<'customers' | 'commitments' | 'leads'>('commitments');

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const c = await api.getCRMContacts();
      setContacts(c);
    } catch (e) {
      console.error('Error loading CRM data', e);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Operations & Customer CRM
            </span>
            <span className="text-xs text-slate-400">Commitments • Active Customers • Pipeline</span>
          </div>
          <h1 className="text-xl font-bold text-white">Operations & Customer Deliverables</h1>
        </div>

        <div className="flex rounded-xl bg-slate-900 p-1 border border-slate-800 text-xs font-semibold">
          {[
            { id: 'commitments', label: 'Customer Commitments', count: 2 },
            { id: 'customers', label: 'Active Customers (38)' },
            { id: 'leads', label: 'Sales Pipeline (4)' },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setSubTab(tab.id as any)}
              className={`px-3 py-1.5 rounded-lg transition ${
                subTab === tab.id ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Customer Commitments (Demo Scenario C) */}
      {subTab === 'commitments' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-200">
            <span className="font-bold block mb-0.5">Critical Deliverable Horizon (Demo Scenario C):</span>
            The background proactive monitor has detected a pending customer commitment promised in contract documentation approaching its deadline.
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            {/* Acme Corp Sarah Chen Webhook Exporter */}
            <div className="p-6 rounded-2xl glass-panel border border-rose-500/40 space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-rose-400" />
                  <span className="text-sm font-bold text-white">Custom Webhook Exporter Delivery</span>
                </div>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-rose-500/10 text-rose-400 border border-rose-500/20">
                  Critical • Due in 3 days
                </span>
              </div>

              <div className="space-y-1.5">
                <div className="text-slate-400">Counterparty:</div>
                <div className="text-slate-200 font-semibold">Sarah Chen (Acme Technologies, Enterprise Tier)</div>
                <div className="text-slate-400">Description:</div>
                <p className="text-slate-300 leading-relaxed">
                  Agreed to ship high-throughput custom exporter for Acme's telemetry pipeline by end of current sprint.
                </p>
                <div className="text-slate-500 text-[11px] pt-1 font-mono">
                  Evidence: Contract addendum with Acme • GitHub Issue #14
                </div>
              </div>

              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                <span className="font-semibold text-slate-300 block">Proactive Recovery Workflow:</span>
                <p className="text-[11px] text-slate-400">
                  Sprint tasks are 80% complete. Operations Adviser recommends drafting a status reassurance note to Sarah.
                </p>
                <div className="flex justify-end gap-2 pt-1">
                  <button className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold">
                    Inspect GitHub PR
                  </button>
                  <button className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-semibold">
                    Draft Customer Update Email
                  </button>
                </div>
              </div>
            </div>

            {/* FinEdge Advisory SOC2 Package */}
            <div className="p-6 rounded-2xl glass-panel space-y-4">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center gap-2">
                  <Clock className="w-4 h-4 text-amber-400" />
                  <span className="text-sm font-bold text-white">SOC2 Compliance Evidence Package</span>
                </div>
                <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Medium Risk • Due in 18 days
                </span>
              </div>

              <div className="space-y-1.5">
                <div className="text-slate-400">Counterparty:</div>
                <div className="text-slate-200 font-semibold">Elena Rostova (FinEdge Advisory)</div>
                <div className="text-slate-400">Description:</div>
                <p className="text-slate-300 leading-relaxed">
                  Provide vendor security questionnaire and audited pen-test summary.
                </p>
                <div className="text-slate-500 text-[11px] pt-1 font-mono">
                  Evidence: Meeting Notes: Q1 Enterprise Review
                </div>
              </div>

              <div className="p-3 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-between">
                <span className="text-slate-400">Owner: Risk & Compliance Adviser</span>
                <span className="text-emerald-400 font-mono">On Schedule</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Customers List */}
      {subTab === 'customers' && (
        <div className="p-6 rounded-2xl glass-panel space-y-4">
          <h2 className="text-sm font-bold text-white">Active Paying Customers (38 Accounts)</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500 border-b border-slate-800 pb-2">
                <tr>
                  <th className="py-2">Customer</th>
                  <th>Company</th>
                  <th>Tier</th>
                  <th>MRR</th>
                  <th>Health</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 text-slate-300">
                {contacts.map((c, i) => (
                  <tr key={i} className="hover:bg-slate-800/30">
                    <td className="py-2.5 font-semibold text-white">{c.name}</td>
                    <td>{c.company}</td>
                    <td><span className="px-2 py-0.5 rounded bg-slate-800 text-indigo-300 font-mono">{c.status === 'onboarding' ? 'Growth' : 'Enterprise'}</span></td>
                    <td className="font-mono text-emerald-400">${c.mrr}/mo</td>
                    <td>
                      <span className={`font-mono font-semibold ${c.health > 80 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {c.health}%
                      </span>
                    </td>
                    <td>
                      <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                        {c.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Pipeline */}
      {subTab === 'leads' && (
        <div className="p-6 rounded-2xl glass-panel space-y-4 text-xs">
          <h2 className="text-sm font-bold text-white">Inbound & Referral Sales Pipeline</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {[
              { name: 'Kavita Rao', comp: 'CloudNest', val: '$1,200/mo', stage: 'Qualified', src: 'Inbound' },
              { name: 'Tom Bradley', comp: 'Apex Digital', val: '$2,400/mo', stage: 'Proposal', src: 'Webinar' },
              { name: 'Julian Thorne', comp: 'Vanguard Security', val: '$3,600/mo', stage: 'Won', src: 'Referral' },
              { name: 'Sophie Laurent', comp: 'Atelier Paris', val: '$700/mo', stage: 'Contacted', src: 'Inbound' },
            ].map((lead, i) => (
              <div key={i} className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                <div className="flex justify-between font-semibold">
                  <span className="text-white">{lead.name}</span>
                  <span className="text-emerald-400 font-mono">{lead.val}</span>
                </div>
                <div className="text-slate-400">{lead.comp}</div>
                <div className="pt-2 flex justify-between text-[10px] text-slate-500 font-mono border-t border-slate-800">
                  <span>Stage: {lead.stage}</span>
                  <span>{lead.src}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
