export interface BusinessProfile {
  id: string;
  name: string;
  description: string;
  industry: string;
  currency: string;
  timezone: string;
  business_model: string;
  products_summary: string[];
  target_customers: string[];
  strategic_objectives: string[];
  monthly_burn_rate: number;
  current_cash_balance: number;
  runway_months: number;
}

export interface DashboardMetrics {
  mrr: number;
  monthly_burn: number;
  net_burn: number;
  runway_months: number | null;
  runway_status: string;
  cash_balance: number;
  active_customers_count: number;
  overdue_invoices_count: number;
  overdue_receivables_amount: number;
  pending_tasks_count: number;
  goals_count: number;
  health_score: number | null;
  financial_data_status: 'recorded' | 'unconfigured' | 'needs_review';
  financial_data_issues: string[];
  financial_data_verified: boolean;
  financial_data_updated_at: string | null;
  financial_snapshot_generated_at: string;
  financial_record_ids: {
    active_customer_ids: string[];
    expense_ids: string[];
    invoice_ids: string[];
  };
  financial_sources?: { cash_balance: string; [key: string]: string };
  financial_provenance: {
    currency: string;
    independent_ledger_reconciliation: boolean;
    [key: string]: string | boolean;
  };
}

export interface CouncilRole {
  name: string;
  title: string;
  department: string;
  focus: string;
}

export interface DeliberationTranscriptItem {
  argument_id?: string;
  forecast_proposal?: {metric:string;point:number;lower:number;upper:number;confidence:number;days:number} | null;
  evidence_status?: string;
  adviser: string;
  role: string;
  department: string;
  stage: string;
  content: string;
  timestamp: string;
}

export interface CouncilMeeting {
  id: string;
  title: string;
  meeting_type: string;
  stage: string;
  topic: string;
  advisers_present: string[];
  deliberation_transcript: DeliberationTranscriptItem[];
  synthesis_summary?: string;
  structured_synthesis?: {status:string; disposition:string; uncertainty:string; arguments:{id:string;adviser:string;quote:string}[]; citations:{id:string;quote:string;source:string}[]};
  areas_of_agreement: string[];
  areas_of_disagreement: string[];
  recommended_actions: { title: string; owner: string; priority: string }[];
  founder_decision?: string;
  founder_notes?: string;
  created_tasks?: string[];
  created_at: string;
  completed_at?: string;
}

export interface AdviserScorecard {
  id: string;
  adviser_name: string;
  department: string;
  total_recommendations: number;
  approved_recommendations: number;
  overridden_recommendations: number;
  predictions_tracked: number;
  average_prediction_error_pct: number | null;
  evidence_completeness_score: number | null;
  action_completion_rate: number | null;
  verified_outcome_rate: number | null;
  last_evaluated: string | null;
  verification_status?: string;
}

export interface DecisionRecord {
  id: string;
  title: string;
  business_context: string;
  advisers_consulted: string[];
  recommendations_summary: string;
  assumptions: { id: string; text: string; status: string }[];
  dissenting_opinions: any[];
  founder_decision: string;
  expected_outcomes: { metric: string; predicted_value: number; timeframe_days: number }[];
  actual_outcomes: { metric: string; predicted_value: number; actual_value: number; absolute_error: number; percentage_error: number | null; recorded_at?: string; verified_at?: string; source?: string; independently_verified?: boolean; notes?: string }[];
  outcome_verified: boolean;
  outcome_data_quality?: 'fictional_demo' | 'founder_reported_unverified';
  outcome_notes?: string;
  created_at: string;
}

export interface MemoryConflict {
  id: string;
  entity_type: string;
  entity_name: string;
  source_a: { name: string; value: string };
  source_b: { name: string; value: string };
  classification: string;
  explanation: string;
  suggested_resolution: string;
  status: string;
  created_at: string;
}

export interface ProactiveAlert {
  id: string;
  type: string;
  severity: "critical" | "high" | "medium" | "low";
  title: string;
  description: string;
  counterparty?: string;
  deadline?: string;
  created_at: string;
}

export interface CustomAgent {
  id: string;
  name: string;
  role_title: string;
  department: string;
  description: string;
  system_prompt: string;
  selected_model: string;
  allowed_tools: string[];
  allowed_memory_collections?: string[];
  requires_approval_for: string[];
  max_steps: number;
  status: "active" | "paused";
}

export interface WorkflowDef {
  version?: number;
  id: string;
  name: string;
  description?: string;
  category: string;
  trigger_type: string;
  trigger_config: Record<string, any>;
  nodes: any[];
  edges: any[];
  is_active: boolean;
  is_template?: boolean;
}

export interface GatewayStatus {
  status: "connected" | "offline";
  base_url: string;
  latency_ms: number;
  available_models: string[];
  inference_available?: boolean;
  requested_model?: string;
  requested_model_installed?: boolean;
  active_profile: string;
  profile_details: Record<string, any>;
  offline_mode?: boolean;
  message?: string;
}

export interface UserProfile {
  id: string;
  email: string;
  name: string;
  role: string;
  business_id: string;
  api_key?: string;
}

export interface AuthResponse {
  status: string;
  user: UserProfile;
  business: Partial<BusinessProfile>;
  token?: string;
  csrf_token?: string;
  message?: string;
}

