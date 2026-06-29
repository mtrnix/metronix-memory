import { apiFetch } from '@/shared';

// --- Types ---

export interface ConfigField {
  name: string;
  label: string;
  type: 'string' | 'url' | 'secret';
  required: boolean;
  placeholder?: string;
}

export interface ConnectorSchema {
  type: string;
  label: string;
  category: 'connector' | 'channel';
  fields: ConfigField[];
}

export interface Connection {
  id: string;
  workspace_id: string;
  connector_type: string;
  name: string;
  config: Record<string, string>;
  status: string;
  enabled: boolean;
  error_message: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface CreateConnectionRequest {
  connector_type: string;
  name: string;
  config: Record<string, string>;
}

export interface UpdateConnectionRequest {
  name?: string;
  config?: Record<string, string>;
  enabled?: boolean;
}

export interface TestResult {
  success: boolean;
  message?: string;
  error?: string;
}

// --- API functions ---

export function getSchemas(): Promise<Record<string, ConnectorSchema>> {
  return apiFetch<{ schemas: Record<string, ConnectorSchema> }>(
    '/api/v1/connections/schemas/',
  ).then((r) => r.schemas);
}

export function listConnections(
  workspaceId: string,
  category?: 'connector' | 'channel',
): Promise<Connection[]> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  if (category) params.set('category', category);
  return apiFetch<{ connections: Connection[] }>(
    `/api/v1/connections/?${params}`,
  ).then((r) => r.connections);
}

export function createConnection(
  workspaceId: string,
  data: CreateConnectionRequest,
): Promise<Connection> {
  return apiFetch<Connection>(
    `/api/v1/connections/?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: 'POST',
      body: JSON.stringify(data),
    },
  );
}

export function updateConnection(
  id: string,
  workspaceId: string,
  data: UpdateConnectionRequest,
): Promise<Connection> {
  return apiFetch<Connection>(
    `/api/v1/connections/${id}/?workspace_id=${encodeURIComponent(workspaceId)}`,
    {
      method: 'PUT',
      body: JSON.stringify(data),
    },
  );
}

export function deleteConnection(
  id: string,
  workspaceId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/connections/${id}/?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: 'DELETE' },
  );
}

export function testConnection(
  id: string,
  workspaceId: string,
): Promise<TestResult> {
  return apiFetch<TestResult>(
    `/api/v1/connections/${id}/test/?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: 'POST' },
  );
}

export function revealSecrets(
  id: string,
  workspaceId: string,
): Promise<Connection> {
  return apiFetch<Connection>(
    `/api/v1/connections/${id}/reveal-secrets/?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
}

export function syncConnection(
  id: string,
  workspaceId: string,
): Promise<{ status: string; message: string }> {
  return apiFetch<{ status: string; message: string }>(
    `/api/v1/connections/${id}/sync/?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: 'POST' },
  );
}

// --- Sync logs ---

export type SyncLogStatus = 'success' | 'partial' | 'failed' | 'running';

export interface SyncLog {
  id: string;
  connection_id: string | null;
  connector_type: string;
  title: string;
  started: string;
  duration_ms: number;
  documents_fetched: number;
  documents_new: number;
  documents_updated: number;
  documents_skipped: number;
  qdrant_chunks: number;
  errors: string[];
  status: SyncLogStatus;
}

export function listSyncLogs(
  workspaceId: string,
  connectionId: string,
  limit = 10,
): Promise<SyncLog[]> {
  const params = new URLSearchParams({
    workspace_id: workspaceId,
    connection_id: connectionId,
    limit: String(limit),
  });
  return apiFetch<{ items: SyncLog[] }>(
    `/api/v1/dashboard/sync-history?${params}`,
  ).then((r) => r.items);
}

export function getLatestSyncLog(
  workspaceId: string,
  connectionId: string,
): Promise<SyncLog | null> {
  return listSyncLogs(workspaceId, connectionId, 1).then(
    (items) => items[0] ?? null,
  );
}
