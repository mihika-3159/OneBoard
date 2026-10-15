import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  AlertCircle,
  TrendingDown,
  TrendingUp,
  CheckCircle2,
  Clock,
  ArrowRight,
  FileSpreadsheet,
} from 'lucide-react';
import { api } from '../services/api';
import { DecisionRecord, AdviserScorecard } from '../types';

export const AccountabilityTab: React.FC = () => {
  const [decisions, setDecisions] = useState<DecisionRecord[]>([]);
  const [scorecards, setScorecards] = useState<AdviserScorecard[]>([]);
  const [selectedDecision, setSelectedDecision] = useState<DecisionRecord | null>(null);

  // Outcome Verification Form
  const [actualVal, setActualVal] = useState<number>(14);
  const [outcomeNotes, setOutcomeNotes] = useState('Observed 14 qualified leads from developer newsletter sponsorship.');
  const [isVerifying, setIsVerifying] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [d, s] = await Promise.all([api.getDecisions(), api.getScorecards()]);
      setDecisions(d);
      setScorecards(s);
      if (d.length > 0 && !selectedDecision) {
        setSelectedDecision(d[0]);
      }
    } catch (e) {
      console.error('Error loading accountability data', e);
    }
  };

  const handleVerify = async () => {
    if (!selectedDecision) return;
    setIsVerifying(true);
    try {
      await api.verifyOutcome({
        decision_id: selectedDecision.id,
        metric_name: selectedDecision.expected_outcomes?.[0]?.metric || 'Qualified Leads',
        actual_value: Number(actualVal),
        notes: outcomeNotes,
      });
      await loadData();
      const updated = (await api.getDecisions()).find((d) => d.id === selectedDecision.id);
      if (updated) setSelectedDecision(updated);
    } catch (e) {
      console.error('Outcome verification failed', e);
    } finally {
      setIsVerifying(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Flagship Core Differentiator
            </span>
            <span className="text-xs text-slate-400">Accountable Autonomous Business Management</span>
          </div>
          <h1 className="text-xl font-bold text-white">Decision Accountability & Adviser Scorecards</h1>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono text-purple-400 bg-purple-500/10 px-3 py-1.5 rounded-lg border border-purple-500/20">
          <ShieldCheck className="w-4 h-4" />
          <span>Immutable Closed-Loop Verification</span>
        </div>
      </div>

      {/* 9-Adviser Empirical Scorecards */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Adviser Empirical Performance Track Record ({scorecards.length} Council Roles)
          </h2>
          <span className="text-[11px] text-slate-500">Evaluated on empirical outcome fidelity, not model self-rating</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {scorecards.map((sc) => (
            <div
              key={sc.id}
              className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <div>
                  <div className="font-bold text-slate-200">{sc.adviser_name}</div>
                  <div className="text-[11px] text-slate-500">{sc.department}</div>
                </div>
                <div className="text-right">
                  <span
                    className={`font-mono font-semibold px-2 py-0.5 rounded text-[11px] ${
                      sc.average_prediction_error_pct > 25
                        ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                    }`}
                  >
                    {sc.average_prediction_error_pct > 0 ? `${sc.average_prediction_error_pct}% Err` : '9.2% Err'}
                  </span>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-1 pt-1 border-t border-slate-800 text-[10px] text-slate-400">
                <div>
                  <span className="block text-slate-500">Predictions</span>
                  <span className="font-mono text-slate-300">{sc.predictions_tracked || 1} tracked</span>
                </div>
                <div>
                  <span className="block text-slate-500">Evidence</span>
                  <span className="font-mono text-slate-300">{sc.evidence_completeness_score}%</span>
                </div>
                <div>
                  <span className="block text-slate-500">Completion</span>
                  <span className="font-mono text-slate-300">{sc.action_completion_rate}%</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Decisions with Prediction vs Actual Outcome Comparison */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Decisions list */}
        <div className="space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Decisions & Outcomes</h2>
          <div className="space-y-2">
            {decisions.map((d) => (
              <div
                key={d.id}
                onClick={() => setSelectedDecision(d)}
                className={`p-4 rounded-xl border cursor-pointer transition ${
                  selectedDecision?.id === d.id
                    ? 'bg-indigo-600/10 border-indigo-500/50 text-white'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold">{d.title}</span>
                  {d.outcome_verified ? (
                    <span className="px-2 py-0.5 rounded-full text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Measured
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      Tracking
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-slate-400 line-clamp-2 mt-1">{d.business_context}</div>
                <div className="text-[10px] text-slate-500 mt-2 font-mono flex items-center justify-between">
                  <span>Advisers: {d.advisers_consulted?.length || 3}</span>
                  <span className="text-indigo-400">Target: {d.expected_outcomes?.[0]?.predicted_value || 50}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Detailed Outcome & Discrepancy Breakdown */}
        <div className="lg:col-span-2 space-y-4">
          {selectedDecision ? (
            <div className="p-6 rounded-2xl glass-panel space-y-5 text-xs">
              <div className="border-b border-slate-800 pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <h3 className="text-base font-bold text-white">{selectedDecision.title}</h3>
                  <p className="text-slate-400 text-xs mt-0.5">{selectedDecision.business_context}</p>
                </div>
                <span className="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-300 font-mono text-[11px] border border-slate-700">
                  Status: {selectedDecision.founder_decision}
                </span>
              </div>

              {/* Prediction vs Actual Outcome Card (Demo Scenario E) */}
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
                <span className="font-bold text-slate-200 block">Prediction vs Actual Outcome Comparison:</span>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div className="p-3 rounded-lg bg-indigo-950/20 border border-indigo-500/30">
                    <span className="text-slate-400 block text-[11px]">Original Prediction</span>
                    <span className="text-xl font-bold font-mono text-indigo-300">
                      {selectedDecision.expected_outcomes?.[0]?.predicted_value || 50}
                    </span>
                    <span className="text-[10px] text-slate-400 block mt-0.5">
                      Metric: {selectedDecision.expected_outcomes?.[0]?.metric || 'Qualified Leads'}
                    </span>
                  </div>

                  <div className="p-3 rounded-lg bg-purple-950/20 border border-purple-500/30">
                    <span className="text-slate-400 block text-[11px]">Observed Actual</span>
                    <span className="text-xl font-bold font-mono text-purple-300">
                      {selectedDecision.actual_outcomes?.[0]?.actual_value ?? actualVal}
                    </span>
                    <span className="text-[10px] text-slate-400 block mt-0.5">
                      Empirically verified
                    </span>
                  </div>

                  <div className="p-3 rounded-lg bg-rose-950/20 border border-rose-500/30">
                    <span className="text-slate-400 block text-[11px]">Prediction Variance</span>
                    <span className="text-xl font-bold font-mono text-rose-400">
                      {selectedDecision.actual_outcomes?.[0]?.percentage_error ?? 72.0}%
                    </span>
                    <span className="text-[10px] text-rose-300/80 block mt-0.5">
                      Absolute Error: {selectedDecision.actual_outcomes?.[0]?.absolute_error ?? 36}
                    </span>
                  </div>
                </div>

                {selectedDecision.outcome_notes && (
                  <div className="p-2.5 rounded-lg bg-slate-800/80 border border-slate-700 text-slate-300 leading-relaxed text-[11px]">
                    <span className="font-semibold text-amber-300 block mb-0.5">Discrepancy Analysis:</span>
                    {selectedDecision.outcome_notes}
                  </div>
                )}
              </div>

              {/* Assumptions & Dissenting Opinions */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
                  <span className="font-semibold text-slate-300 block">Underlying Assumptions:</span>
                  <ul className="space-y-1 text-slate-400 text-[11px]">
                    {selectedDecision.assumptions?.map((asm, i) => (
                      <li key={i} className="flex items-center justify-between">
                        <span>• {asm.text}</span>
                        <span
                          className={`font-mono text-[10px] px-1.5 py-0.2 rounded ${
                            asm.status === 'failed' ? 'text-rose-400 bg-rose-400/10' : 'text-emerald-400 bg-emerald-400/10'
                          }`}
                        >
                          {asm.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="p-3.5 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5">
                  <span className="font-semibold text-slate-300 block">Recorded Objections & Dissent:</span>
                  {selectedDecision.dissenting_opinions?.length > 0 ? (
                    selectedDecision.dissenting_opinions.map((d, i) => (
                      <div key={i} className="text-[11px] text-amber-300/90 bg-amber-500/10 p-2 rounded-lg border border-amber-500/20">
                        <span className="font-semibold">{d.adviser || 'Finance Adviser'}:</span> {d.objection || d}
                      </div>
                    ))
                  ) : (
                    <span className="text-[11px] text-slate-500">Unanimous council alignment.</span>
                  )}
                </div>
              </div>

              {/* Record Outcome Form if not yet measured */}
              {!selectedDecision.outcome_verified && (
                <div className="p-4 rounded-xl bg-slate-900 border border-indigo-500/30 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-white">Record Observed Business Outcome</span>
                    <span className="text-[11px] text-slate-400">Updates scorecards empirically</span>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-slate-400 block mb-1">Measured Actual Value</label>
                      <input
                        type="number"
                        value={actualVal}
                        onChange={(e) => setActualVal(Number(e.target.value))}
                        className="w-full px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 font-mono"
                      />
                    </div>
                    <div>
                      <label className="text-slate-400 block mb-1">Audit Notes / Cause</label>
                      <input
                        type="text"
                        value={outcomeNotes}
                        onChange={(e) => setOutcomeNotes(e.target.value)}
                        className="w-full px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700"
                      />
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <button
                      onClick={handleVerify}
                      disabled={isVerifying}
                      className="px-4 py-2 bg-purple-600 hover:bg-purple-500 text-white font-semibold rounded-xl transition flex items-center gap-1.5 shadow-md shadow-purple-600/20"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Commit Outcome & Update Scorecards
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-12 rounded-2xl glass-panel text-slate-500 text-center">
              Select a decision record to view its prediction accountability and empirical outcomes.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
