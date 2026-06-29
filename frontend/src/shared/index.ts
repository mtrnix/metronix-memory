// API
export { apiFetch } from './api/client';
export { ApiError } from './api/errors';
export {
  login,
  getToken,
  setToken,
  clearToken,
  isAuthenticated,
} from './api/auth';
export {
  listWorkspaces,
  getWorkspace,
  createWorkspace,
  activateWorkspace,
  getWorkspaceStats,
  deleteWorkspace,
} from './api/workspaces';
export { getHealth, getReady, getMetrics } from './api/health';

// Types
export type {
  LoginRequest,
  LoginResponse,
  WorkspaceResponse,
  WorkspaceListResponse,
  WorkspaceCreate,
  WorkspaceStatsResponse,
  HealthResponse,
  MetricsResponse,
  OperationMetrics,
} from './api/types';

// Stores
export { useWorkspaceStore } from './stores/workspace';
export { useAuthStore } from './stores/auth';

// Hooks
export { useWorkspaces } from './hooks/useWorkspaces';
export { useHealth } from './hooks/useHealth';

// Components
export { default as StatusDot } from './components/StatusDot';
export { default as WorkspaceSelector } from './components/WorkspaceSelector';
export { default as MetricCard } from './components/MetricCard';
export { default as LoadingSpinner } from './components/LoadingSpinner';
export { default as ErrorMessage } from './components/ErrorMessage';
export { default as StatusBadge } from './components/StatusBadge';
export { default as LoginPage } from './components/LoginPage';
export { default as ConfirmDialog } from './components/ConfirmDialog';

// Utils
export {
  formatNumber,
  formatRelativeTime,
  formatDuration,
  formatPercentage,
  formatCurrency,
} from './utils/format';
