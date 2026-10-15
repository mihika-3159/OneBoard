import React, { useState, useEffect, useCallback } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  applyNodeChanges,
  applyEdgeChanges,
  Node,
  Edge,
  NodeChange,
  EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  Play,
  Sparkles,
  CheckCircle2,
  AlertTriangle,
  Plus,
  BookOpen,
  ArrowRight,
  ShieldCheck,
  RotateCcw,
} from 'lucide-react';
import { api } from '../services/api';
import { WorkflowDef } from '../types';

export const WorkflowStudioTab: React.FC = () => {
  const [workflows, setWorkflows] = useState<WorkflowDef[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowDef | null>(null);
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);

  // Natural Language Prompt Generator & Teach a Process
  const [promptText, setPromptText] = useState(
    'Every Friday, review overdue invoices, calculate total outstanding balance, require founder approval, and send reminder emails.'
  );
  const [isGenerating, setIsGenerating] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [executionOutput, setExecutionOutput] = useState<any | null>(null);
  const [pendingApprovals, setPendingApprovals] = useState<any[]>([]);

  // Teach a Process mode
  const [isTeachModal, setIsTeachModal] = useState(false);
  const [teachDesc, setTeachDesc] = useState('');

  useEffect(() => {
    loadWorkflows();
    loadApprovals();
  }, []);

  const loadWorkflows = async () => {
    try {
      const data = await api.getWorkflows();
      setWorkflows(data);
      if (data.length > 0 && !selectedWorkflow) {
        selectWorkflow(data[0]);
      }
    } catch (e) {
      console.error('Error loading workflows', e);
    }
  };

  const loadApprovals = async () => {
    try {
      const apps = await api.getPendingApprovals();
      setPendingApprovals(apps);
    } catch (e) {
      console.error('Error loading approvals', e);
    }
  };

  const selectWorkflow = (wf: WorkflowDef) => {
    setSelectedWorkflow(wf);
    const flowNodes = (wf.nodes || []).map((n) => ({
      id: n.id,
      position: n.position || { x: 100, y: 100 },
      data: { label: n.data?.label || n.id },
      style: {
        background: n.type === 'approval' ? '#7f1d1d' : n.type === 'trigger' ? '#312e81' : '#0f172a',
        color: '#f8fafc',
        border: '1px solid #334155',
        borderRadius: '0.75rem',
        padding: '10px 16px',
        fontSize: '12px',
        fontWeight: '600',
        width: 180,
      },
    }));
    const flowEdges = (wf.edges || []).map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: true,
      style: { stroke: '#6366f1', strokeWidth: 2 },
    }));
    setNodes(flowNodes);
    setEdges(flowEdges);
    setExecutionOutput(null);
  };

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)),
    []
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    []
  );

  const handleGenerateWorkflow = async () => {
    setIsGenerating(true);
    try {
      const generated = await api.generateWorkflowFromPrompt(promptText);
      const created = await api.createWorkflow(generated);
      await loadWorkflows();
      selectWorkflow(created);
    } catch (e) {
      console.error('Generation failed', e);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleTeachProcess = async () => {
    setIsGenerating(true);
    try {
      const generated = await api.teachProcess(teachDesc);
      const created = await api.createWorkflow(generated);
      await loadWorkflows();
      selectWorkflow(created);
      setIsTeachModal(false);
      setTeachDesc('');
    } catch (e) {
      console.error('Teach a Process failed', e);
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRunWorkflow = async (dryRun: boolean = false) => {
    if (!selectedWorkflow) return;
    setIsRunning(true);
    try {
      const res = await api.executeWorkflow(selectedWorkflow.id, dryRun);
      setExecutionOutput(res);
      await loadApprovals();
    } catch (e) {
      console.error('Workflow run failed', e);
    } finally {
      setIsRunning(false);
    }
  };

  const handleApprovePending = async (requestId: string) => {
    try {
      await api.resolveApproval(requestId, 'approve');
      await loadApprovals();
      if (selectedWorkflow) {
        const res = await api.executeWorkflow(selectedWorkflow.id, false);
        setExecutionOutput(res);
      }
    } catch (e) {
      console.error('Approval resolution failed', e);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header bar */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              Visual Automation Builder
            </span>
            <span className="text-xs text-slate-400">React Flow DAG Execution Engine with Human Checkpoints</span>
          </div>
          <h1 className="text-xl font-bold text-white">Visual Workflow Studio & Process Teacher</h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsTeachModal(true)}
            className="flex items-center gap-1.5 px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-xl border border-slate-700 transition"
          >
            <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
            Teach OneBoard a Process
          </button>
          <button
            onClick={() => handleRunWorkflow(false)}
            disabled={isRunning || !selectedWorkflow}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition shadow-lg shadow-indigo-600/20"
          >
            <Play className="w-3.5 h-3.5 fill-white" />
            {isRunning ? 'Executing DAG...' : 'Execute Workflow'}
          </button>
        </div>
      </div>

      {/* Natural Language Workflow Generator Bar */}
      <div className="p-4 rounded-2xl bg-indigo-950/20 border border-indigo-500/30 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <div className="flex items-center gap-2 text-indigo-400 text-xs font-bold whitespace-nowrap">
          <Sparkles className="w-4 h-4" /> Natural Language Generator:
        </div>
        <input
          type="text"
          value={promptText}
          onChange={(e) => setPromptText(e.target.value)}
          placeholder="Describe an automation in plain English..."
          className="flex-1 px-3.5 py-2 bg-slate-900 text-white text-xs rounded-xl border border-slate-800 focus:outline-none focus:border-indigo-500"
        />
        <button
          onClick={handleGenerateWorkflow}
          disabled={isGenerating}
          className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition whitespace-nowrap shadow-md shadow-indigo-600/20"
        >
          {isGenerating ? 'Generating DAG...' : 'Generate & Visualize'}
        </button>
      </div>

      {/* Pending Approval Gates (Human-in-the-loop) */}
      {pendingApprovals.length > 0 && (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-amber-300 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400" />
              Human Approval Gate Pending ({pendingApprovals.length} action)
            </span>
            <span className="text-[10px] text-amber-300/80">Workflow paused at high-risk step</span>
          </div>
          {pendingApprovals.map((app) => (
            <div key={app.id} className="p-3 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between text-xs">
              <div>
                <div className="font-semibold text-white">{app.title}</div>
                <div className="text-[11px] text-slate-400">{app.description}</div>
              </div>
              <button
                onClick={() => handleApprovePending(app.id)}
                className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold rounded-lg transition flex items-center gap-1"
              >
                <CheckCircle2 className="w-3.5 h-3.5" /> Approve & Resume
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Main Studio View: Workflows List + Canvas */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Workflows List */}
        <div className="space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Saved Workflows</h2>
          <div className="space-y-2">
            {workflows.map((w) => (
              <div
                key={w.id}
                onClick={() => selectWorkflow(w)}
                className={`p-3.5 rounded-xl border cursor-pointer transition ${
                  selectedWorkflow?.id === w.id
                    ? 'bg-indigo-600/10 border-indigo-500/50 text-white'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs">{w.name}</div>
                <div className="text-[11px] text-slate-400 line-clamp-1 mt-0.5">{w.description}</div>
                <div className="text-[10px] text-slate-500 mt-2 font-mono flex items-center justify-between">
                  <span>Trigger: {w.trigger_type}</span>
                  <span className="px-1.5 py-0.5 rounded bg-slate-800 text-indigo-300">
                    {w.nodes?.length || 0} nodes
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* React Flow Canvas */}
        <div className="lg:col-span-3 space-y-4">
          <div className="h-[480px] rounded-2xl border border-slate-800/80 bg-[#090d16] relative overflow-hidden">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              fitView
            >
              <Background color="#1e293b" gap={16} />
              <Controls className="bg-slate-900 border-slate-800 text-white fill-white" />
            </ReactFlow>

            <div className="absolute top-3 left-3 bg-slate-900/80 backdrop-blur px-3 py-1.5 rounded-lg border border-slate-800 text-xs text-slate-300 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-indigo-400"></span>
              Active Graph: {selectedWorkflow?.name || 'Workflow Canvas'}
            </div>
          </div>

          {/* Execution Output Drawer */}
          {executionOutput && (
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="font-bold text-white flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                  Execution Status: {executionOutput.status}
                </span>
                <span className="font-mono text-slate-400 text-[11px]">
                  Run ID: {executionOutput.id}
                </span>
              </div>

              {executionOutput.verified_success && (
                <div className="p-2.5 rounded-lg bg-emerald-950/20 border border-emerald-500/30 text-emerald-300 text-xs">
                  Outcome Verified: {executionOutput.verification_details?.assertion}
                </div>
              )}

              <div className="space-y-1.5 text-xs">
                <div className="font-semibold text-slate-300">Node Step Results:</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {Object.entries(executionOutput.step_results || {}).map(([nodeId, res]: [string, any]) => (
                    <div key={nodeId} className="p-2.5 rounded-lg bg-slate-800/60 border border-slate-700/60 text-[11px]">
                      <div className="font-semibold text-indigo-300">{res.label || nodeId}</div>
                      <div className="text-slate-400 mt-0.5">Status: {res.status}</div>
                      {res.result && (
                        <div className="font-mono text-[10px] text-slate-500 mt-1 truncate">
                          {JSON.stringify(res.result)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Teach a Process Modal */}
      {isTeachModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="p-6 rounded-2xl bg-slate-900 border border-slate-700 max-w-xl w-full space-y-4">
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              <BookOpen className="w-5 h-5 text-indigo-400" />
              Teach OneBoard a Repetitive Process
            </h3>
            <p className="text-xs text-slate-400 leading-relaxed">
              Describe a multi-step routine you perform manually. OneBoard deconstructs the steps, matches authorized tools, sets up approval gates, and prepares an automated executable workflow.
            </p>
            <textarea
              rows={4}
              value={teachDesc}
              onChange={(e) => setTeachDesc(e.target.value)}
              placeholder="e.g. When a new customer signs up for Enterprise, fetch their company domain, draft a customized welcome message with the API onboarding guide, and request my approval before sending..."
              className="w-full px-3.5 py-2.5 bg-slate-800 text-white text-xs rounded-xl border border-slate-700 focus:outline-none focus:border-indigo-500"
            />
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setIsTeachModal(false)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl"
              >
                Cancel
              </button>
              <button
                onClick={handleTeachProcess}
                disabled={isGenerating || !teachDesc.trim()}
                className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition"
              >
                {isGenerating ? 'Synthesizing...' : 'Create & Verify Automation'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
