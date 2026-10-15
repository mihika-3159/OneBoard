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
  UserSession,
  AuthResponse
} from '../types';

const API_BASE = '/api';

export class ApiError extends Error {
  status: number;
  detail: any;

  constructor(message: string, status: number, detail?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem('oneboard_token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // Do not set Content-Type for FormData uploads (browser sets multipart boundary)
  if (options.body instanceof FormData) {
    delete headers['Content-Type'];
  }

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (!res.ok) {
      let errMessage = `HTTP ${res.status}: ${res.statusText}`;
      let errDetail: any = null;
      try {
        const data = await res.json();
        errDetail = data.detail || data.message || data;
        if (typeof errDetail === 'string') {
          errMessage = errDetail;
        } else if (errDetail) {
          errMessage = JSON.stringify(errDetail);
        }
      } catch {
        // Response body was not JSON
      }
      throw new ApiError(errMessage, res.status, errDetail);
    }

    return await res.json();
  } catch (err: any) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(
      err?.message || 'Network connection failed. Ensure OneBoard API backend is running on port 8000.',
      0
    );
  }
}

export const api = {
  // Authentication & Sessions
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const res = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (res.access_token) {
      localStorage.setItem('oneboard_token', res.access_token);
    }
    return res;
  },

  register: async (payload: { email: string; password: string; name: string; company_name: string; industry?: string }): Promise<AuthResponse> => {
    const res = await request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (res.access_token) {
      localStorage.setItem('oneboard_token', res.access_token);
    }
    return res;
  },

  getMe: async (): Promise<UserSession> => {
    return request<UserSession>('/auth/me');
  },

  logout: () => {
    localStorage.removeItem('oneboard_token');
  },

  getAuthToken: (): string | null => {
    return localStorage.getItem('oneboard_token');
  },

  // Business & Metrics
  getBusiness: async (): Promise<BusinessProfile> => {
    return request<BusinessProfile>('/business');
  },

  getMetrics: async (): Promise<DashboardMetrics> => {
    return request<DashboardMetrics>('/business/metrics');
  },

  resetDemo: async (): Promise<any> => {
    return request<any>('/business/seed-demo', { method: 'POST' });
  },

  // Council & Boardroom
  getCouncilRoles: async (): Promise<CouncilRole[]> => {
    return request<CouncilRole[]>('/council/roles');
  },

  getCouncilMeetings: async (): Promise<CouncilMeeting[]> => {
    return request<CouncilMeeting[]>('/council/meetings');
  },

  deliberateMeeting: async (payload: { title: string; meeting_type: string; topic: string; selected_advisers?: string[] }): Promise<CouncilMeeting> => {
    return request<CouncilMeeting>('/council/deliberate', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  approveMeeting: async (meetingId: string, notes?: string): Promise<any> => {
    return request<any>(`/council/meetings/${meetingId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ decision_notes: notes }),
    });
  },

  // AI Gateway & Founder Command
  getGatewayStatus: async (): Promise<GatewayStatus> => {
    return request<GatewayStatus>('/ai/status');
  },

  switchProfile: async (profile: string): Promise<any> => {
    return request<any>('/ai/profile', {
      method: 'POST',
      body: JSON.stringify({ profile }),
    });
  },

  benchmarkGateway: async (): Promise<any> => {
    return request<any>('/ai/benchmark', { method: 'POST' });
  },

  executeCommand: async (command: string): Promise<any> => {
    return request<any>('/ai/command', {
      method: 'POST',
      body: JSON.stringify({ command }),
    });
  },

  // Workflows
  getWorkflows: async (): Promise<WorkflowDef[]> => {
    return request<WorkflowDef[]>('/workflows');
  },

  getWorkflowRuns: async (): Promise<any[]> => {
    return request<any[]>('/workflows/runs');
  },

  getWorkflowTemplates: async (): Promise<any[]> => {
    return request<any[]>('/workflows/templates');
  },

  getPendingApprovals: async (): Promise<any[]> => {
    return request<any[]>('/workflows/approvals');
  },

  resolveApproval: async (requestId: string, action: 'approve' | 'reject', notes?: string): Promise<any> => {
    return request<any>(`/workflows/approvals/${requestId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, notes }),
    });
  },

  createWorkflow: async (payload: { name: string; description?: string; category: string; trigger_type: string; nodes: any[]; edges: any[] }): Promise<WorkflowDef> => {
    return request<WorkflowDef>('/workflows', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  executeWorkflow: async (workflowId: string, dryRun: boolean = false): Promise<any> => {
    return request<any>(`/workflows/${workflowId}/execute?dry_run=${dryRun}`, {
      method: 'POST',
    });
  },

  generateWorkflowPrompt: async (prompt: string): Promise<any> => {
    return request<any>('/workflows/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },

  generateWorkflowFromPrompt: async (prompt: string): Promise<any> => {
    return request<any>('/workflows/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },

  teachProcess: async (description: string, examples?: string): Promise<any> => {
    return request<any>('/workflows/teach-process', {
      method: 'POST',
      body: JSON.stringify({ description, examples }),
    });
  },

  // Custom Agents
  getAgents: async (): Promise<CustomAgent[]> => {
    return request<CustomAgent[]>('/agents');
  },

  createAgent: async (agentData: any): Promise<CustomAgent> => {
    return request<CustomAgent>('/agents', {
      method: 'POST',
      body: JSON.stringify(agentData),
    });
  },

  generateAgentPrompt: async (prompt: string): Promise<any> => {
    return request<any>('/agents/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },

  generateAgentConfig: async (prompt: string): Promise<any> => {
    return request<any>('/agents/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },

  testAgent: async (agentId: string, testInput: string): Promise<any> => {
    return request<any>(`/agents/${agentId}/test`, {
      method: 'POST',
      body: JSON.stringify({ test_input: testInput }),
    });
  },

  toggleAgentStatus: async (agentId: string): Promise<any> => {
    return request<any>(`/agents/${agentId}/toggle-status`, {
      method: 'POST',
    });
  },

  // Accountability & Outcomes
  getDecisions: async (): Promise<DecisionRecord[]> => {
    return request<DecisionRecord[]>('/accountability/decisions');
  },

  getScorecards: async (): Promise<AdviserScorecard[]> => {
    return request<AdviserScorecard[]>('/accountability/scorecards');
  },

  verifyOutcome: async (
    payloadOrId: string | { decision_id: string; metric_name: string; actual_value: number; notes?: string },
    metricName?: string,
    actualValue?: number,
    notes?: string
  ): Promise<any> => {
    let body: any;
    if (typeof payloadOrId === 'object' && payloadOrId !== null) {
      body = payloadOrId;
    } else {
      body = {
        decision_id: payloadOrId,
        metric_name: metricName,
        actual_value: actualValue,
        notes,
      };
    }
    return request<any>('/accountability/verify-outcome', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  // Proactive Alerts
  getAlerts: async (): Promise<ProactiveAlert[]> => {
    return request<ProactiveAlert[]>('/alerts');
  },

  // Business Memory & Graph
  searchMemory: async (query: string, topK: number = 5): Promise<any> => {
    return request<any>('/memory/search', {
      method: 'POST',
      body: JSON.stringify({ query, top_k: topK }),
    });
  },

  getMemoryGraph: async (): Promise<any> => {
    return request<any>('/memory/graph');
  },

  getMemoryConflicts: async (): Promise<MemoryConflict[]> => {
    return request<MemoryConflict[]>('/memory/conflicts');
  },

  getConflicts: async (): Promise<MemoryConflict[]> => {
    return request<MemoryConflict[]>('/memory/conflicts');
  },

  resolveConflict: async (conflictId: string, resolution: string, action: string): Promise<any> => {
    return request<any>(`/memory/conflicts/${conflictId}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ resolution, action }),
    });
  },

  uploadDocument: async (file: File): Promise<any> => {
    const formData = new FormData();
    formData.append('file', file);
    return request<any>('/memory/upload', {
      method: 'POST',
      body: formData,
    });
  },

  // Integrations
  getIntegrations: async (): Promise<any[]> => {
    return request<any[]>('/integrations');
  },

  syncIntegration: async (integrationId: string): Promise<any> => {
    return request<any>(`/integrations/${integrationId}/sync`, {
      method: 'POST',
    });
  },

  importChatConversation: async (conversationText: string): Promise<any> => {
    return request<any>('/integrations/import-chat', {
      method: 'POST',
      body: JSON.stringify({ conversation_text: conversationText }),
    });
  },

  importChat: async (conversationText: string): Promise<any> => {
    return request<any>('/integrations/import-chat', {
      method: 'POST',
      body: JSON.stringify({ conversation_text: conversationText }),
    });
  },

  getCRMContacts: async (): Promise<any> => {
    return request<any>('/integrations/crm/contacts');
  },

  getFinanceLedger: async (): Promise<any> => {
    return request<any>('/integrations/finance/ledger');
  },

  getEmailOutbox: async (): Promise<any> => {
    return request<any>('/integrations/email/outbox');
  },

  getGithubStatus: async (): Promise<any> => {
    return request<any>('/integrations/github/status');
  },
};
