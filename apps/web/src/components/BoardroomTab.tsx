import React, { useState, useEffect } from 'react';
import {
  Users,
  Play,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  Sparkles,
  ChevronRight,
  ShieldCheck,
  FileText,
  Check,
} from 'lucide-react';
import { api } from '../services/api';
import { CouncilRole, CouncilMeeting } from '../types';

export const BoardroomTab: React.FC = () => {
  const [roles, setRoles] = useState<CouncilRole[]>([]);
  const [meetings, setMeetings] = useState<CouncilMeeting[]>([]);
  const [selectedMeeting, setSelectedMeeting] = useState<CouncilMeeting | null>(null);

  // New Meeting Form
  const [isConvening, setIsConvening] = useState(false);
  const [meetingTitle, setMeetingTitle] = useState('Q2 Growth & Runway Review');
  const [meetingTopic, setMeetingTopic] = useState(
    'Should we increase our Growth tier price from $59 to $69, or offer annual prepay incentives to extend our 7.2-month runway?'
  );
  const [meetingType, setMeetingType] = useState('weekly_executive_review');
  const [selectedAdviserNames, setSelectedAdviserNames] = useState<string[]>([
    'Chief of Staff',
    'Strategy Adviser',
    'Finance Adviser',
    'Marketing Adviser',
    'Operations Adviser',
  ]);

  const [approvalNotes, setApprovalNotes] = useState('');
  const [isApproving, setIsApproving] = useState(false);
  const [isDeliberating, setIsDeliberating] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [r, m] = await Promise.all([api.getCouncilRoles(), api.getCouncilMeetings()]);
      setRoles(r);
      setMeetings(m);
      if (m.length > 0 && !selectedMeeting) {
        setSelectedMeeting(m[0]);
      }
    } catch (e) {
      console.error('Error loading council data', e);
    }
  };

  const handleConvene = async () => {
    setIsDeliberating(true);
    try {
      const newMeeting = await api.deliberateMeeting({
        title: meetingTitle,
        meeting_type: meetingType,
        topic: meetingTopic,
        selected_advisers: selectedAdviserNames,
      });
      await loadData();
      setSelectedMeeting(newMeeting);
      setIsConvening(false);
    } catch (e) {
      console.error('Deliberation failed', e);
    } finally {
      setIsDeliberating(false);
    }
  };

  const handleApprove = async () => {
    if (!selectedMeeting) return;
    setIsApproving(true);
    try {
      await api.approveMeeting(selectedMeeting.id, approvalNotes || 'Approved board strategy.');
      await loadData();
      const updated = (await api.getCouncilMeetings()).find((m) => m.id === selectedMeeting.id);
      if (updated) setSelectedMeeting(updated);
    } catch (e) {
      console.error('Approval failed', e);
    } finally {
      setIsApproving(false);
    }
  };

  const toggleAdviser = (name: string) => {
    if (selectedAdviserNames.includes(name)) {
      setSelectedAdviserNames(selectedAdviserNames.filter((n) => n !== name));
    } else {
      setSelectedAdviserNames([...selectedAdviserNames, name]);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Closed Operational Loop
            </span>
            <span className="text-xs text-slate-400">9-Role Multi-Agent Executive Deliberation</span>
          </div>
          <h1 className="text-xl font-bold text-white">Boardroom Deliberation & Governance</h1>
        </div>

        <button
          onClick={() => setIsConvening(!isConvening)}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition shadow-lg shadow-indigo-600/20"
        >
          <Play className="w-3.5 h-3.5 fill-white" />
          Convene New Meeting
        </button>
      </div>

      {/* Convene Modal / Drawer */}
      {isConvening && (
        <div className="p-6 rounded-2xl bg-slate-900 border border-indigo-500/30 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white">Convene AI Executive Council</h2>
            <button
              onClick={() => setIsConvening(false)}
              className="text-xs text-slate-400 hover:text-white"
            >
              Cancel
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-semibold text-slate-300">Meeting Title</label>
              <input
                type="text"
                value={meetingTitle}
                onChange={(e) => setMeetingTitle(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-slate-800 text-white text-sm rounded-xl border border-slate-700 focus:outline-none focus:border-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-300">Review Type</label>
              <select
                value={meetingType}
                onChange={(e) => setMeetingType(e.target.value)}
                className="w-full mt-1 px-3 py-2 bg-slate-800 text-white text-sm rounded-xl border border-slate-700 focus:outline-none focus:border-indigo-500"
              >
                <option value="weekly_executive_review">Weekly Executive Review</option>
                <option value="monthly_financial_review">Monthly Financial Review</option>
                <option value="product_launch_review">Product Launch Review</option>
                <option value="marketing_strategy_review">Marketing Strategy Review</option>
                <option value="operational_incident_review">Operational Incident Review</option>
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-300">Strategic Deliberation Topic</label>
            <textarea
              rows={3}
              value={meetingTopic}
              onChange={(e) => setMeetingTopic(e.target.value)}
              className="w-full mt-1 px-3 py-2 bg-slate-800 text-white text-sm rounded-xl border border-slate-700 focus:outline-none focus:border-indigo-500"
            />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-300 mb-2 block">
              Select Specialist Advisers to Attend ({selectedAdviserNames.length} selected)
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {roles.map((r) => {
                const isSelected = selectedAdviserNames.includes(r.name);
                return (
                  <div
                    key={r.name}
                    onClick={() => toggleAdviser(r.name)}
                    className={`p-2.5 rounded-xl border cursor-pointer transition flex items-center justify-between text-xs ${
                      isSelected
                        ? 'bg-indigo-600/20 border-indigo-500/40 text-white'
                        : 'bg-slate-800/40 border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    <div>
                      <div className="font-semibold">{r.name}</div>
                      <div className="text-[10px] text-slate-500">{r.department}</div>
                    </div>
                    {isSelected && <Check className="w-3.5 h-3.5 text-indigo-400" />}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="pt-2 flex justify-end">
            <button
              onClick={handleConvene}
              disabled={isDeliberating || selectedAdviserNames.length === 0}
              className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition shadow-lg shadow-indigo-600/20"
            >
              {isDeliberating ? (
                <>
                  <Sparkles className="w-4 h-4 animate-spin" />
                  Deliberating Across Council Roles...
                </>
              ) : (
                <>
                  <Play className="w-3.5 h-3.5 fill-white" />
                  Start Executive Deliberation
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Main Boardroom Deliberation View */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Meetings History */}
        <div className="space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Past Board Meetings</h2>
          {meetings.length === 0 ? (
            <div className="p-4 rounded-xl glass-panel text-xs text-slate-500">No meetings recorded yet.</div>
          ) : (
            meetings.map((m) => (
              <div
                key={m.id}
                onClick={() => setSelectedMeeting(m)}
                className={`p-4 rounded-xl border cursor-pointer transition ${
                  selectedMeeting?.id === m.id
                    ? 'bg-indigo-600/10 border-indigo-500/50 text-white'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-200">{m.title}</span>
                  {m.founder_decision === 'approved' ? (
                    <span className="px-2 py-0.5 text-[10px] rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                      <CheckCircle2 className="w-3 h-3" /> Approved
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 text-[10px] rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      Pending Action
                    </span>
                  )}
                </div>
                <div className="text-[11px] text-slate-400 line-clamp-1 mt-1">{m.topic}</div>
                <div className="text-[10px] text-slate-500 mt-2 font-mono">
                  {new Date(m.created_at).toLocaleDateString()} • {m.advisers_present.length} Advisers
                </div>
              </div>
            ))
          )}
        </div>

        {/* Right Column: Active Deliberation Transcript & Synthesis */}
        <div className="lg:col-span-2 space-y-4">
          {selectedMeeting ? (
            <div className="p-6 rounded-2xl glass-panel space-y-5">
              <div className="border-b border-slate-800 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <h3 className="text-lg font-bold text-white">{selectedMeeting.title}</h3>
                  <p className="text-xs text-slate-400 mt-0.5">{selectedMeeting.topic}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-slate-400 bg-slate-800/80 px-2.5 py-1 rounded-lg border border-slate-700">
                    {selectedMeeting.meeting_type}
                  </span>
                </div>
              </div>

              {/* Multi-Agent Deliberation Speeches */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-2">
                  <Users className="w-3.5 h-3.5 text-indigo-400" />
                  Deliberation Record & Specialist Analysis
                </h4>

                <div className="space-y-3 max-h-[380px] overflow-y-auto pr-1">
                  {selectedMeeting.deliberation_transcript?.map((item, idx) => (
                    <div
                      key={idx}
                      className={`p-3.5 rounded-xl text-xs space-y-1.5 ${
                        item.stage === 'challenge_round'
                          ? 'bg-rose-950/20 border border-rose-500/30 text-rose-200'
                          : 'bg-slate-900/80 border border-slate-800 text-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between font-semibold">
                        <span className="text-indigo-300">{item.adviser} ({item.role})</span>
                        <span className="text-[10px] font-mono text-slate-500">{item.stage}</span>
                      </div>
                      <div className="leading-relaxed whitespace-pre-wrap">{item.content}</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Synthesis & Agreement / Disagreement */}
              <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-500/30 space-y-3 text-xs">
                <div className="font-bold text-indigo-300 flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-indigo-400" />
                  Chief of Staff Consensus Synthesis
                </div>
                <p className="text-slate-300 leading-relaxed">
                  {selectedMeeting.synthesis_summary || 'Council synthesized trade-offs and aligned on recommended actions.'}
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                  <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30 text-emerald-300">
                    <span className="font-semibold block mb-1">Areas of Consensus:</span>
                    <ul className="list-disc pl-4 space-y-0.5 text-[11px] text-emerald-300/90">
                      {selectedMeeting.areas_of_agreement?.map((a, i) => (
                        <li key={i}>{a}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="p-2.5 rounded-lg bg-amber-950/20 border border-amber-500/30 text-amber-300">
                    <span className="font-semibold block mb-1">Debated Trade-Offs / Objections:</span>
                    <ul className="list-disc pl-4 space-y-0.5 text-[11px] text-amber-300/90">
                      {selectedMeeting.areas_of_disagreement?.map((d, i) => (
                        <li key={i}>{d}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Recommended Actions */}
              {selectedMeeting.recommended_actions?.length > 0 && (
                <div className="space-y-2 text-xs">
                  <h4 className="font-bold text-slate-300">Action Plan to be Dispatched:</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {selectedMeeting.recommended_actions.map((act, i) => (
                      <div key={i} className="p-2.5 rounded-xl bg-slate-900 border border-slate-800">
                        <div className="font-semibold text-slate-200">{act.title}</div>
                        <div className="text-[10px] text-slate-400 mt-1 flex justify-between">
                          <span>Owner: {act.owner}</span>
                          <span className="text-amber-400 font-mono uppercase">{act.priority}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Founder Approval Gate */}
              {selectedMeeting.founder_decision === 'approved' ? (
                <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2 text-emerald-300 font-semibold">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    Decision Approved by Founder & Converted into Tracked Tasks
                  </div>
                  <span className="font-mono text-emerald-400 text-[11px]">
                    Tasks: {selectedMeeting.created_tasks?.length || 3} created
                  </span>
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-slate-900 border border-indigo-500/30 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold text-white">Founder Ratification Gate</span>
                    <span className="text-[11px] text-slate-400">Human-in-the-loop executive sign-off</span>
                  </div>
                  <input
                    type="text"
                    value={approvalNotes}
                    onChange={(e) => setApprovalNotes(e.target.value)}
                    placeholder="Optional founder instructions or execution caveats..."
                    className="w-full px-3 py-2 bg-slate-800 text-white text-xs rounded-lg border border-slate-700 focus:outline-none"
                  />
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={handleApprove}
                      disabled={isApproving}
                      className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-xl transition flex items-center gap-1.5"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Approve & Convert to Tasks
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="p-12 rounded-2xl glass-panel text-center text-slate-500 text-sm">
              Select or convene a board meeting to view the deliberation and synthesis.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
