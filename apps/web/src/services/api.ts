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
  UserProfile,
  AuthResponse,
} from '../types';

const API_BASE = '/api';

// ---------------------------------------------------------------------------
// Typed API Error Classes
// ---------------------------------------------------------------------------
export class ApiError extends Error {
  public status: number;
  public detail: string;

  constructor(status: number, detail: string) {
    super(`API Error ${status}: ${detail}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export class UnauthorizedError extends ApiError {
  constructor(detail = 'Authentication required or session expired.') {
    super(401, detail);
    this.name = 'UnauthorizedError';
  }
}

export class ForbiddenError extends ApiError {
  constructor(detail = 'Access denied: resource belongs to another business tenant.') {
    super(403, detail);
    this.name = 'ForbiddenError';
  }
}

// In-memory CSRF and session token state (avoiding localStorage for tokens)
let inMemoryCsrfToken: string | null = null;
let inMemoryBearerToken: string | null = null;

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp('(^|;\\s*)(' + name + ')=([^;]*)'));
  return match ? decodeURIComponent(match[3]) : null;
}

export function setCsrfToken(token: string | null): void {
  inMemoryCsrfToken = token;
}

export function setBearerToken(token: string | null): void {
  inMemoryBearerToken = token;
}

// ---------------------------------------------------------------------------
// Central HTTP Request Handler
// ---------------------------------------------------------------------------
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers = new Headers(options.headers || {});

  // Send credentials (HttpOnly session cookie)
  options.credentials = 'include';

  // Attach in-memory bearer token if present
  if (inMemoryBearerToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${inMemoryBearerToken}`);
  }

  // Attach CSRF token on state-changing requests
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
    const csrf = inMemoryCsrfToken || getCookie('oneboard_csrf');
    if (csrf && !headers.has('x-csrf-token')) {
      headers.set('x-csrf-token', csrf);
    }
  }

  // Default to JSON content-type if body is JSON string and not FormData
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  options.headers = headers;

  const res = await fetch(url, options);

  if (res.status === 401) {
    let detail = 'Authentication required.';
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch {
      // Fallback to default
    }
    throw new UnauthorizedError(detail);
  }

  if (res.status === 403) {
    let detail = 'Access forbidden.';
    try {
      const err = await res.json();
      detail = err.detail || detail;
    } catch {
      // Fallback
    }
    throw new ForbiddenError(detail);
  }

  if (!res.ok) {
    let detail = `Request failed with HTTP ${res.status}`;
    try {
      const err = await res.json();
      detail = err.detail || err.message || detail;
    } catch {
      // Fallback
    }
    throw new ApiError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) {
    return {} as T;
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// Exported API Client
// ---------------------------------------------------------------------------
export const api = {
  // Authentication & Session
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const res = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (res.csrf_token) setCsrfToken(res.csrf_token);
    if (res.token) setBearerToken(res.token);
    return res;
  },

  register: async (payload: {
    name: string;
    email: string;
    password: string;
    business_name?: string;
    industry?: string;
  }): Promise<AuthResponse> => {
    const res = await request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    if (res.csrf_token) setCsrfToken(res.csrf_token);
    if (res.token) setBearerToken(res.token);
    return res;
  },

  logout: async (): Promise<void> => {
    try {
      await request<void>('/auth/logout', { method: 'POST' });
    } finally {
      setCsrfToken(null);
      setBearerToken(null);
    }
  },

  getMe: async (): Promise<{ user: UserProfile; business: BusinessProfile }> => {
    return request<{ user: UserProfile; business: BusinessProfile }>('/auth/me');
  },

  regenerateApiKey: async (): Promise<{ api_key: string }> => {
    return request<{ api_key: string }>('/auth/regenerate-api-key', { method: 'POST' });
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

  deliberateMeeting: async (payload: {
    title: string;
    meeting_type: string;
    topic: string;
    selected_advisers?: string[];
  }): Promise<CouncilMeeting> => {
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

  createWorkflow: async (payload: {
    name: string;
    description?: string;
    category: string;
    trigger_type: string;
    nodes: any[];
    edges: any[];
  }): Promise<WorkflowDef> => {
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
