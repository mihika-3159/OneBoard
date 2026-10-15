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
  runway_months: number;
  cash_balance: number;
  active_customers_count: number;
  overdue_invoices_count: number;
  overdue_receivables_amount: number;
  pending_tasks_count: number;
  goals_count: number;
  health_score: number;
}

export interface CouncilRole {
  name: string;
  title: string;
  department: string;
  focus: string;
}

export interface DeliberationTranscriptItem {
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
  average_prediction_error_pct: number;
  evidence_completeness_score: number;
  action_completion_rate: number;
  verified_outcome_rate: number;
  last_evaluated: string;
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
  actual_outcomes: { metric: string; predicted_value: number; actual_value: number; absolute_error: number; percentage_error: number; verified_at: string; notes?: string }[];
  outcome_verified: boolean;
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
  requires_approval_for: string[];
  max_steps: number;
  status: "active" | "paused";
}

export interface WorkflowDef {
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
  active_profile: string;
  profile_details: Record<string, any>;
  offline_mode?: boolean;
  message?: string;
}
