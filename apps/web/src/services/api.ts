import {
  BusinessProfile,
  DashboardMetrics,
  CouncilRole,
  CouncilMeeting,
  AdviserScorecard,
  DecisionRecord,
  MemoryConflict,
  ProactiveAlert,
  CustomAgent,
  WorkflowDef,
  GatewayStatus,
} from '../types';

const API_BASE = '/api';

export const api = {
  // Business & Metrics
  getBusiness: async (): Promise<BusinessProfile> => {
    const res = await fetch(`${API_BASE}/business`);
    return res.json();
  },
  getMetrics: async (): Promise<DashboardMetrics> => {
    const res = await fetch(`${API_BASE}/business/metrics`);
    return res.json();
  },
  resetDemo: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/business/seed-demo`, { method: 'POST' });
    return res.json();
  },

  // Council & Boardroom
  getCouncilRoles: async (): Promise<CouncilRole[]> => {
    const res = await fetch(`${API_BASE}/council/roles`);
    return res.json();
  },
  getCouncilMeetings: async (): Promise<CouncilMeeting[]> => {
    const res = await fetch(`${API_BASE}/council/meetings`);
    return res.json();
  },
  deliberateMeeting: async (payload: { title: string; meeting_type: string; topic: string; selected_advisers?: string[] }): Promise<CouncilMeeting> => {
    const res = await fetch(`${API_BASE}/council/deliberate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  },
  approveMeeting: async (meetingId: string, notes?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/council/meetings/${meetingId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision_notes: notes }),
    });
    return res.json();
  },

  // AI Gateway & Founder Command
  getGatewayStatus: async (): Promise<GatewayStatus> => {
    const res = await fetch(`${API_BASE}/ai/status`);
    return res.json();
  },
  switchProfile: async (profile: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/ai/profile`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    });
    return res.json();
  },
  benchmarkGateway: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/ai/benchmark`, { method: 'POST' });
    return res.json();
  },
  executeCommand: async (command: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/ai/command`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command }),
    });
    return res.json();
  },

  // Workflows & Visual Studio
  getWorkflows: async (): Promise<WorkflowDef[]> => {
    const res = await fetch(`${API_BASE}/workflows`);
    return res.json();
  },
  createWorkflow: async (payload: any): Promise<WorkflowDef> => {
    const res = await fetch(`${API_BASE}/workflows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  },
  executeWorkflow: async (workflowId: string, dryRun: boolean = false): Promise<any> => {
    const res = await fetch(`${API_BASE}/workflows/${workflowId}/execute?dry_run=${dryRun}`, {
      method: 'POST',
    });
    return res.json();
  },
  generateWorkflowFromPrompt: async (prompt: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/workflows/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    return res.json();
  },
  teachProcess: async (description: string, examples?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/workflows/teach-process`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description, examples }),
    });
    return res.json();
  },
  getPendingApprovals: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/workflows/approvals`);
    return res.json();
  },
  resolveApproval: async (requestId: string, action: 'approve' | 'reject', notes?: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/workflows/approvals/${requestId}/action`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, notes }),
    });
    return res.json();
  },
  getWorkflowTemplates: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/workflows/templates`);
    return res.json();
  },

  // Agent Studio
  getAgents: async (): Promise<CustomAgent[]> => {
    const res = await fetch(`${API_BASE}/agents`);
    return res.json();
  },
  createAgent: async (payload: any): Promise<CustomAgent> => {
    const res = await fetch(`${API_BASE}/agents`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  },
  generateAgentConfig: async (prompt: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/agents/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
    return res.json();
  },
  testAgent: async (agentId: string, testInput: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/agents/${agentId}/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ test_input: testInput }),
    });
    return res.json();
  },

  // Accountability & Outcomes
  getDecisions: async (): Promise<DecisionRecord[]> => {
    const res = await fetch(`${API_BASE}/accountability/decisions`);
    return res.json();
  },
  getScorecards: async (): Promise<AdviserScorecard[]> => {
    const res = await fetch(`${API_BASE}/accountability/scorecards`);
    return res.json();
  },
  verifyOutcome: async (payload: { decision_id: string; metric_name: string; actual_value: number; notes?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/accountability/verify-outcome`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  },

  // Memory & Knowledge Graph
  searchMemory: async (query: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/memory/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    });
    return res.json();
  },
  getMemoryGraph: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/memory/graph`);
    return res.json();
  },
  getConflicts: async (): Promise<MemoryConflict[]> => {
    const res = await fetch(`${API_BASE}/memory/conflicts`);
    return res.json();
  },
  resolveConflict: async (conflictId: string, resolution: string, action: string = 'custom'): Promise<any> => {
    const res = await fetch(`${API_BASE}/memory/conflicts/${conflictId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution, action }),
    });
    return res.json();
  },

  // Proactive Alerts
  getAlerts: async (): Promise<ProactiveAlert[]> => {
    const res = await fetch(`${API_BASE}/alerts`);
    return res.json();
  },

  // Integrations
  getIntegrations: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/integrations`);
    return res.json();
  },
  syncIntegration: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/integrations/${id}/sync`, { method: 'POST' });
    return res.json();
  },
  importChat: async (conversation_text: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/integrations/import-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ conversation_text }),
    });
    return res.json();
  },
  getCRMContacts: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/integrations/crm/contacts`);
    return res.json();
  },
  getFinanceLedger: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/integrations/finance/ledger`);
    return res.json();
  },
  getEmailOutbox: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/integrations/email/outbox`);
    return res.json();
  },
};
