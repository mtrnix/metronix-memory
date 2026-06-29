import { apiFetch } from './client';
import type {
  WorkspaceCreate,
  WorkspaceListResponse,
  WorkspaceResponse,
  WorkspaceStatsResponse,
} from './types';

export function listWorkspaces(): Promise<WorkspaceListResponse> {
  return apiFetch<WorkspaceListResponse>('/api/v1/workspaces/');
}

export function getWorkspace(id: string): Promise<WorkspaceResponse> {
  return apiFetch<WorkspaceResponse>(`/api/v1/workspaces/${id}`);
}

export function createWorkspace(
  data: WorkspaceCreate,
): Promise<WorkspaceResponse> {
  return apiFetch<WorkspaceResponse>('/api/v1/workspaces/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function activateWorkspace(
  id: string,
): Promise<WorkspaceResponse> {
  return apiFetch<WorkspaceResponse>(`/api/v1/workspaces/${id}/activate`, {
    method: 'POST',
  });
}

export function getWorkspaceStats(
  id: string,
): Promise<WorkspaceStatsResponse> {
  return apiFetch<WorkspaceStatsResponse>(`/api/v1/workspaces/${id}/stats`);
}

export function deleteWorkspace(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/workspaces/${id}`, { method: 'DELETE' });
}
