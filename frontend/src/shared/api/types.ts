// Auth
export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user_id: string;
  email: string;
  display_name: string;
  role: string;
}

// Workspaces
export interface WorkspaceResponse {
  workspace_id: string;
  name: string;
  description?: string;
  created_at: string;
  user_id: string;
  is_active: boolean;
  config?: Record<string, unknown>;
}

export interface WorkspaceListResponse {
  workspaces: WorkspaceResponse[];
  count: number;
}

export interface WorkspaceCreate {
  name: string;
  description?: string;
  user_id?: string;
  workspace_id?: string;
}

export interface WorkspaceStatsResponse {
  workspace_id: string;
  name: string;
  file_count: number;
  chunk_count: number;
  entity_count: number;
  jira_issue_count: number;
  last_upload_time?: string;
}

// Health & Metrics
export interface HealthResponse {
  status: "ready" | "degraded";
  services: Record<string, "ok" | "error">;
}

export interface MetricsResponse {
  uptime_sec: number;
  operations: Record<string, OperationMetrics>;
  embedding_cache: {
    hits: number;
    misses: number;
    size: number;
    maxsize: number;
  };
}

export interface OperationMetrics {
  count: number;
  success_count: number;
  error_count: number;
  total_duration_sec: number;
  avg_duration_sec: number;
  min_duration_sec: number;
  max_duration_sec: number;
  success_rate: number;
  last_error?: string;
}
