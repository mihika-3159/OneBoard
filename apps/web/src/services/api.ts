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
let authEpoch=0;
export const sessionExpiredEvent='oneboard:session-expired';
export const connectionIssueEvent='oneboard:connection-issue';
export function resetClientSession(){authEpoch++;inMemoryCsrfToken=null;inMemoryBearerToken=null;}

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
async function checkedResponse(path: string, options: RequestInit = {}): Promise<Response> {
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

  const epoch=authEpoch;
  const authEndpoint=/^\/auth\/(login|register|logout|me|security\/recover)$/.test(path);
  const report=(message:string)=>{if(epoch===authEpoch&&!authEndpoint)window.dispatchEvent(new CustomEvent(connectionIssueEvent,{detail:{message,write:method!=='GET'&&method!=='HEAD'}}))};
  let res:Response;
  try{res=await fetch(url,options)}catch(e){if(!options.signal?.aborted)report('Network request interrupted.');throw e}
  if(res.status>=500)report('Service request failed.');

  if (res.status === 401) {
    if(!authEndpoint&&epoch===authEpoch){resetClientSession();window.dispatchEvent(new Event(sessionExpiredEvent));}
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

  if(epoch!==authEpoch)throw new UnauthorizedError('Session changed during request.');
  return res;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await checkedResponse(path, options);
  // 204 No Content
  if (res.status === 204) {
    return {} as T;
  }

  return res.json();
}

// Preserve the same request identity when a network/5xx error leaves the
// outcome unknown. A deliberate new execution receives a new UUID only after
// the previous outcome has been confirmed.
// These are non-secret operation IDs, not authentication material.
// Do not dispatch if persistent storage is unavailable: a reload must not
// silently generate a new operation after an ambiguous response.
const workflowKeyPrefix = 'oneboard.workflow.pending.v1:';
function workflowIdentity(workflowId:string,dryRun:boolean){return workflowKeyPrefix+workflowId+':'+dryRun}
async function withWorkflowLock<T>(identity:string,operation:()=>Promise<T>):Promise<T>{
  if(navigator.locks) return navigator.locks.request(identity,operation);
  // session-local fallback still preserves the pending key across reloads.
  return operation();
}

// ---------------------------------------------------------------------------
// Exported API Client
// ---------------------------------------------------------------------------
export const api = {
  dataRead: async(path:string)=>request<any>('/data/'+path),
  dataWrite: async(path:string,payload?:unknown,method='POST')=>request<any>('/data/'+path,{method,body:payload===undefined?undefined:JSON.stringify(payload)}),
  dataDownload: async(path:string)=>(await checkedResponse('/data/'+path)).blob(),
  dataUpload: async(path:string,file:File)=>request<any>('/data/'+path,{method:'PUT',body:file,headers:{'Content-Type':'application/json'}}),
  databaseDiagnostics: async()=>request<any>('/diagnostics/database'),
  providerRead: async(path:string)=>request<any>('/integrations/providers/'+path),
  providerWrite: async(path:string,payload:unknown)=>request<any>('/integrations/providers/'+path,{method:'POST',body:JSON.stringify(payload)}),
  financeRead: async(path:string)=>request<any>('/business/financial/'+path),
  financeWrite: async(path:string,payload:unknown)=>request<any>('/business/financial/'+path,{method:'POST',body:JSON.stringify(payload)}),
  streamInference: async <T = any>(path: string, payload: unknown, signal: AbortSignal, progress: (message: string) => void): Promise<T> => {
    const res = await checkedResponse(path, {method: "POST", signal, headers: {Accept: "application/x-ndjson"},
      ...(payload === undefined ? {} : {body: JSON.stringify(payload)})});
    if (!res.headers.get("content-type")?.includes("application/x-ndjson") || !res.body) throw new Error("Missing inference stream");
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = "";
    let final: {result: T} | undefined;
    let ended = false;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) {
          ended = true;
          if (!final || buffer.trim()) throw new Error("Inference interrupted before a complete final result");
          return final.result;
        }
        buffer += value;
        if (buffer.length > 8 * 1024 * 1024) throw new Error("Inference response exceeded limit");
        let end;
        while ((end = buffer.indexOf("\n")) >= 0) {
          const event = JSON.parse(buffer.slice(0, end));
          buffer = buffer.slice(end + 1);
          if (final) throw new Error("Unexpected data after final inference result");
          if (event.error) throw new Error(event.error);
          if (Object.prototype.hasOwnProperty.call(event, "result")) {
            final = {result: event.result as T};
          } else {
            if (typeof event.progress !== "string") throw new Error("Invalid inference progress event");
            progress(event.progress);
          }
        }
      }
    } finally {
      if (!ended) { try { await reader.cancel(); } catch { /* Already aborted */ } }
      reader.releaseLock();
    }
  },
  // Authentication & Session
  login: async (email: string, password: string, mfa_code?: string): Promise<AuthResponse> => {
    const res = await request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, mfa_code }),
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

  securityStatus: () => request<any>("/auth/security"),
  securityAction: (path:string, payload:Record<string,unknown>, method="POST") => request<any>("/auth/security"+path,{method,body:JSON.stringify(payload)}),
  securityList: (path:string) => request<any>("/auth/security"+path),
  recoverAccount: async(email:string,recovery_code:string,new_password:string) => {
    const result=await request<any>("/auth/security/recover",{method:"POST",body:JSON.stringify({email,recovery_code,new_password})});
    setBearerToken(null);setCsrfToken(null);return result;
  },

  // Business & Metrics
  getBusiness: async (): Promise<BusinessProfile> => {
    return request<BusinessProfile>('/business');
  },

  getMetrics: async (): Promise<DashboardMetrics> => {
    return request<DashboardMetrics>('/business/metrics');
  },

  getOperationsOverview: async (): Promise<any> => {
    // Real tenant-owned commitments, customers and leads.
    // The demo CRM adapter intentionally remains unavailable to real tenants.
    return request<any>('/business/operations');
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

  streamCommand: async (command: string, signal: AbortSignal, append: (text: string) => void) => {
    const res = await checkedResponse('/ai/command/stream', {
      method: 'POST', signal, body: JSON.stringify({ command }),
    });
    if (!res.body) throw new Error('Missing response stream');
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    let final: {result: any} | undefined;
    let ended = false;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) {
          ended = true;
          if (!final || buffer.trim()) throw new Error('Generation interrupted');
          return final.result;
        }
        buffer += value;
        if (buffer.length > 8 * 1024 * 1024) throw new Error('Generation response exceeded limit');
        let end;
        while ((end = buffer.indexOf('\n')) >= 0) {
          const event = JSON.parse(buffer.slice(0, end));
          buffer = buffer.slice(end + 1);
          if (final) throw new Error('Unexpected data after final generation result');
          if (event.error) throw new Error(event.error);
          if (Object.prototype.hasOwnProperty.call(event, 'result')) {
            final = {result: event.result};
          } else {
            if (typeof event.delta !== 'string') throw new Error('Invalid generation event');
            append(event.delta);
          }
        }
      }
    } finally {
      if (!ended) { try { await reader.cancel(); } catch { /* Already aborted */ } }
      reader.releaseLock();
    }
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
    const identity=workflowIdentity(workflowId,dryRun);
    return withWorkflowLock(identity,async()=>{
      let key=localStorage.getItem(identity);
      if(!key){key=crypto.randomUUID();localStorage.setItem(identity,key);}
      const result=await request<any>(`/workflows/${workflowId}/execute?dry_run=${dryRun}`,{
        method:'POST',headers:{'Idempotency-Key':key}
      });
      // Clear only after the durable identity has been returned.
      if(result?.id && localStorage.getItem(identity)===key)localStorage.removeItem(identity);
      return result;
    });
  },
  getWorkflowVersions: async (id:string):Promise<any[]> => request<any[]>(`/workflows/${id}/versions`),
  updateWorkflowDefinition: async (id:string,payload:any):Promise<WorkflowDef> => request<WorkflowDef>(`/workflows/${id}/definition`,{method:'PUT',body:JSON.stringify(payload)}),
  rollbackWorkflow: async (id:string,expected_version:number,target_version:number):Promise<WorkflowDef> =>
    request<WorkflowDef>(`/workflows/${id}/rollback`,{method:'POST',body:JSON.stringify({expected_version,target_version})}),
  getWorkflowEvents: async ():Promise<any[]>=>request<any[]>('/workflows/events'),
  retryWorkflowEvent: async (id:string):Promise<any>=>request<any>(`/workflows/events/${id}/retry`,{method:'POST'}),
  cancelWorkflowRun: async (id:string):Promise<any>=>request<any>(`/workflows/runs/${id}/cancel`,{method:'POST'}),
  recoverWorkflowRun: async (id:string):Promise<any>=>request<any>(`/workflows/runs/${id}/recover`,{method:'POST'}),
  reconcileWorkflowRuns: async ():Promise<any>=>request<any>('/workflows/runs/reconcile-interrupted',{method:'POST'}),

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

  getSchedules: async (): Promise<any[]> => request<any[]>('/workflows/schedules'),
  saveSchedule: async (id:string, cron:string, timezone:string, enabled:boolean,missed_policy:string='coalesce'):Promise<any> =>
    request<any>(`/workflows/${id}/schedule`,{method:'PUT',body:JSON.stringify({cron,timezone,enabled,missed_policy})}),
  getRetention: async ():Promise<any> => request<any>('/data/retention',{cache:'no-store'}),
  saveRetention: async (policy:Record<string,number|null>):Promise<any> =>
    request<any>('/data/retention',{method:'PUT',body:JSON.stringify(policy)}),
  exportSnapshot: async ():Promise<any> => request<any>('/data/export-snapshot'),

  // Custom Agents
  getAgentRuns: async (): Promise<any[]> => request<any[]>('/agents/runs'),
  startAgentRun: async (agentId: string, payload: any): Promise<any> =>
    request<any>(`/agents/${agentId}/runs`, {method:'POST',body:JSON.stringify(payload)}),
  advanceAgentRun: async (runId: string): Promise<any> =>
    request<any>(`/agents/runs/${runId}/advance`, {method:'POST'}),
  runRemainingAgentSteps: async (runId: string, signal: AbortSignal): Promise<any> =>
    api.streamInference(`/agents/runs/${runId}/run-remaining`, undefined, signal, ()=>{}),
  cancelAgentRun: async (runId: string): Promise<any> =>
    request<any>(`/agents/runs/${runId}/cancel`, {method:'POST'}),
  reconcileCouncil: async (): Promise<any> => request<any>('/council/meetings/reconcile-interrupted',{method:'POST'}),
  getCalibration: async (): Promise<any> => request<any>('/accountability/calibration'),
  recordModelForecast: async (meetingId:string,argumentId:string):Promise<any> =>
    request<any>(`/accountability/meetings/${meetingId}/forecast/${argumentId}`,{method:'POST'}),
  recordForecast: async (decisionId: string, payload: any): Promise<any> =>
    request<any>(`/accountability/decisions/${decisionId}/forecast`,{method:'POST',body:JSON.stringify(payload)}),
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

  memoryDocuments: async ():Promise<any>=>request<any>('/memory/documents'),
  retryMemoryDocument: async (id:string):Promise<any>=>request<any>(`/memory/documents/${id}/retry`,{method:'POST'}),
  reindexMemoryDocument: async (id:string):Promise<any>=>request<any>(`/memory/documents/${id}/reindex`,{method:'POST'}),
  memorySource: async (id:string):Promise<any>=>request<any>(`/memory/sources/${id}`),
  memoryFeedback: async (query:string,chunk_id:string,helpful:boolean):Promise<any>=>request<any>('/memory/feedback',{method:'POST',body:JSON.stringify({query,chunk_id,helpful})}),
  uploadDocument: async (file: File,supersedesId?:string): Promise<any> => {
    const formData = new FormData();
    formData.append('file', file);
    if(supersedesId)formData.append('supersedes_id',supersedesId);
    return request<any>('/memory/upload', {
      method: 'POST',
      body: formData,
    });
  },

  // Integrations
  getIntegrations: async (): Promise<any[]> => {
    return request<any[]>('/integrations');
  },

  importLocalCustomers: async (
    csvText: string, idempotencyKey: string, sourceName: string, dryRun = true
  ): Promise<any> => {
    return request<any>('/integrations/local/customers/import', {
      method: 'POST',
      body: JSON.stringify({
        csv_text: csvText,
        idempotency_key: idempotencyKey,
        source_name: sourceName,
        dry_run: dryRun,
      }),
    });
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

  getCRMContacts: async (): Promise<{ is_simulated: boolean; source: string; contacts: any[] }> => {
    return request<{ is_simulated: boolean; source: string; contacts: any[] }>('/integrations/crm/contacts');
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
