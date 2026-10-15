import React, { useState, useEffect } from 'react';
import {
  Bot,
  Plus,
  Sparkles,
  Shield,
  Play,
  Pause,
  CheckCircle2,
  Lock,
  Cpu,
  Sliders,
  Send,
} from 'lucide-react';
import { api } from '../services/api';
import { CustomAgent } from '../types';

export const AgentStudioTab: React.FC = () => {
  const [agents, setAgents] = useState<CustomAgent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<CustomAgent | null>(null);

  // Natural Language & Visual Builder State
  const [isCreating, setIsCreating] = useState(false);
  const [createMode, setCreateMode] = useState<'visual' | 'nl'>('nl');
  const [nlPrompt, setNlPrompt] = useState(
    'Create a Customer Onboarding Specialist that reviews new SaaS signups, checks if webhook endpoints are configured, and drafts check-in emails requiring my approval.'
  );

  // Form State
  const [name, setName] = useState('');
  const [roleTitle, setRoleTitle] = useState('');
  const [department, setDepartment] = useState('Customer Success');
  const [description, setDescription] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('qwen2.5:7b');
  const [allowedTools, setAllowedTools] = useState<string[]>(['read_crm', 'check_telemetry']);
  const [requiresApproval, setRequiresApproval] = useState<string[]>(['send_email']);

  // Sandbox Tester State
  const [testInput, setTestInput] = useState('We have 3 new customer signups today. One has not configured their API key yet.');
  const [testOutput, setTestOutput] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    loadAgents();
  }, []);

  const loadAgents = async () => {
    try {
      const data = await api.getAgents();
      setAgents(data);
      if (data.length > 0 && !selectedAgent) {
        setSelectedAgent(data[0]);
      }
    } catch (e) {
      console.error('Error loading custom agents', e);
    }
  };

  const handleGenerateNL = async () => {
    setIsSubmitting(true);
    try {
      const config = await api.generateAgentConfig(nlPrompt);
      setName(config.name || 'New Custom Agent');
      setRoleTitle(config.role_title || 'Autonomous Specialist');
      setDepartment(config.department || 'Operations');
      setDescription(config.description || '');
      setSystemPrompt(config.system_prompt || '');
      setAllowedTools(config.allowed_tools || ['read_crm']);
      setRequiresApproval(config.requires_approval_for || ['send_email']);
      setCreateMode('visual');
    } catch (e) {
      console.error('Agent generation failed', e);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveAgent = async () => {
    setIsSubmitting(true);
    try {
      const newAgent = await api.createAgent({
        name,
        role_title: roleTitle,
        department,
        description,
        system_prompt: systemPrompt,
        selected_model: selectedModel,
        allowed_tools: allowedTools,
        requires_approval_for: requiresApproval,
        max_steps: 4,
      });
      await loadAgents();
      setSelectedAgent(newAgent);
      setIsCreating(false);
    } catch (e) {
      console.error('Saving agent failed', e);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTestAgent = async () => {
    if (!selectedAgent) return;
    setIsTesting(true);
    try {
      const res = await api.testAgent(selectedAgent.id, testInput);
      setTestOutput(res.output);
    } catch (e) {
      console.error('Testing failed', e);
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="p-5 rounded-2xl glass-panel flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
              No-Code Agent Studio
            </span>
            <span className="text-xs text-slate-400">Build, test, and deploy bounded specialist agents</span>
          </div>
          <h1 className="text-xl font-bold text-white">Custom Agent Studio & Permission Boundaries</h1>
        </div>

        <button
          onClick={() => {
            setIsCreating(!isCreating);
            setCreateMode('nl');
          }}
          className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition shadow-lg shadow-indigo-600/20"
        >
          <Plus className="w-4 h-4" />
          Create Custom Agent
        </button>
      </div>

      {/* Creation Modal / Drawer */}
      {isCreating && (
        <div className="p-6 rounded-2xl bg-slate-900 border border-indigo-500/30 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-base font-bold text-white">New Specialist Agent</span>
              <div className="flex rounded-lg bg-slate-800 p-0.5 border border-slate-700 text-xs font-medium">
                <button
                  onClick={() => setCreateMode('nl')}
                  className={`px-3 py-1 rounded-md transition ${createMode === 'nl' ? 'bg-indigo-600 text-white' : 'text-slate-400'}`}
                >
                  Natural Language
                </button>
                <button
                  onClick={() => setCreateMode('visual')}
                  className={`px-3 py-1 rounded-md transition ${createMode === 'visual' ? 'bg-indigo-600 text-white' : 'text-slate-400'}`}
                >
                  Visual Form
                </button>
              </div>
            </div>
            <button onClick={() => setIsCreating(false)} className="text-xs text-slate-400 hover:text-white">
              Cancel
            </button>
          </div>

          {createMode === 'nl' ? (
            <div className="space-y-3">
              <p className="text-xs text-slate-400">
                Describe the agent's purpose, business domain, and responsibilities. OneBoard will construct a validated agent schema with appropriate permissions.
              </p>
              <textarea
                rows={3}
                value={nlPrompt}
                onChange={(e) => setNlPrompt(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-800 text-white text-xs rounded-xl border border-slate-700 focus:outline-none focus:border-indigo-500"
              />
              <div className="flex justify-end">
                <button
                  onClick={handleGenerateNL}
                  disabled={isSubmitting || !nlPrompt.trim()}
                  className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold rounded-xl transition"
                >
                  <Sparkles className="w-3.5 h-3.5" />
                  Generate Agent Configuration
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-slate-300">Agent Name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full mt-1 px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="font-semibold text-slate-300">Department</label>
                  <select
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    className="w-full mt-1 px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 focus:outline-none"
                  >
                    <option value="Customer Success">Customer Success</option>
                    <option value="Growth">Growth</option>
                    <option value="Finance">Finance</option>
                    <option value="Operations">Operations</option>
                    <option value="Engineering">Engineering</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="font-semibold text-slate-300">System Instruction Prompt</label>
                <textarea
                  rows={3}
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  className="w-full mt-1 px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 focus:outline-none font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-slate-300">Assigned Ollama Model</label>
                  <select
                    value={selectedModel}
                    onChange={(e) => setSelectedModel(e.target.value)}
                    className="w-full mt-1 px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 focus:outline-none font-mono"
                  >
                    <option value="qwen2.5:7b">qwen2.5:7b (Recommended)</option>
                    <option value="llama3.2:1b">llama3.2:1b (Fast CPU)</option>
                    <option value="llama3.1:8b">llama3.1:8b (High Precision)</option>
                  </select>
                </div>
                <div>
                  <label className="font-semibold text-slate-300">Approval Requirement Boundary</label>
                  <input
                    type="text"
                    value={requiresApproval.join(', ')}
                    onChange={(e) => setRequiresApproval(e.target.value.split(',').map((s) => s.trim()))}
                    placeholder="send_email, update_price"
                    className="w-full mt-1 px-3 py-2 bg-slate-800 text-white rounded-lg border border-slate-700 focus:outline-none font-mono"
                  />
                </div>
              </div>

              <div className="flex justify-end pt-2">
                <button
                  onClick={handleSaveAgent}
                  disabled={isSubmitting || !name.trim()}
                  className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold rounded-xl transition"
                >
                  Deploy Custom Agent
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main Studio View: Agents List + Details + Sandbox */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Agents List */}
        <div className="space-y-3">
          <h2 className="text-xs font-bold uppercase tracking-wider text-slate-400">Deployed Agents</h2>
          <div className="space-y-2">
            {agents.map((a) => (
              <div
                key={a.id}
                onClick={() => setSelectedAgent(a)}
                className={`p-3.5 rounded-xl border cursor-pointer transition ${
                  selectedAgent?.id === a.id
                    ? 'bg-indigo-600/10 border-indigo-500/50 text-white'
                    : 'bg-slate-900/60 border-slate-800 text-slate-300 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-semibold">{a.name}</span>
                  <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    {a.status}
                  </span>
                </div>
                <div className="text-[11px] text-slate-400 mt-1">{a.role_title} • {a.department}</div>
                <div className="text-[10px] text-slate-500 mt-2 font-mono flex items-center justify-between">
                  <span>Model: {a.selected_model}</span>
                  <span>Tools: {a.allowed_tools?.length || 2}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Agent Details & Permission Boundary */}
        <div className="space-y-4">
          {selectedAgent ? (
            <div className="p-5 rounded-2xl glass-panel space-y-4 text-xs">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div>
                  <h3 className="text-base font-bold text-white">{selectedAgent.name}</h3>
                  <p className="text-slate-400 mt-0.5">{selectedAgent.role_title}</p>
                </div>
                <span className="px-2.5 py-1 rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 font-mono">
                  {selectedAgent.department}
                </span>
              </div>

              <div>
                <span className="font-semibold text-slate-300 block mb-1">System Instructions:</span>
                <p className="text-slate-400 bg-slate-900/80 p-3 rounded-xl border border-slate-800 font-mono text-[11px] leading-relaxed">
                  {selectedAgent.system_prompt}
                </p>
              </div>

              <div className="space-y-2">
                <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-indigo-400" />
                  Deterministic Permission Boundary:
                </span>
                <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1.5 text-[11px]">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Permitted Tools:</span>
                    <span className="text-indigo-300 font-mono">{selectedAgent.allowed_tools?.join(', ') || 'read_crm'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Approval Required For:</span>
                    <span className="text-amber-400 font-mono">{selectedAgent.requires_approval_for?.join(', ') || 'send_email'}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Max Execution Loops:</span>
                    <span className="text-slate-300 font-mono">{selectedAgent.max_steps || 4} steps</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div className="p-8 rounded-2xl glass-panel text-slate-500 text-xs text-center">
              Select an agent to inspect its configuration.
            </div>
          )}
        </div>

        {/* Sandbox Tester */}
        <div className="space-y-4">
          <div className="p-5 rounded-2xl glass-panel space-y-4">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-indigo-400" />
                Live Agent Sandbox
              </span>
              <span className="text-[10px] text-slate-500 font-mono">Isolated Testing</span>
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-300 block mb-1">Test Simulation Input:</label>
              <textarea
                rows={3}
                value={testInput}
                onChange={(e) => setTestInput(e.target.value)}
                className="w-full p-2.5 bg-slate-900 text-white text-xs rounded-xl border border-slate-800 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <button
              onClick={handleTestAgent}
              disabled={isTesting || !selectedAgent}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition flex items-center justify-center gap-1.5 shadow-md shadow-indigo-600/20"
            >
              <Send className="w-3.5 h-3.5" />
              {isTesting ? 'Simulating Agent...' : 'Test Agent in Sandbox'}
            </button>

            {testOutput && (
              <div className="p-3 rounded-xl bg-slate-900 border border-indigo-500/30 space-y-1.5">
                <span className="text-[11px] font-semibold text-indigo-300 block">Agent Output:</span>
                <div className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed">{testOutput}</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
