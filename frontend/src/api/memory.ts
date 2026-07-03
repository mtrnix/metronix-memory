import { apiFetch } from '@/shared';

// --- Types (mirrors MemoryRecordResponse in src/metronix/api/routes/memory.py) ---

export type MemoryKind = 'fact' | 'preference' | 'pinned';
export type MemoryScope = 'global' | 'per_agent' | 'session';
export type LifecycleStatus =
  | 'candidate'
  | 'active'
  | 'stale'
  | 'superseded'
  | 'archived'
  | 'conflicted'
  | 'review_needed';

export interface MemoryRecord {
  id: string;
  workspace_id: string;
  agent_id: string;
  scope: MemoryScope;
  source_type: string;
  content: string;
  tags: string[];
  importance_score: number;
  ttl_expires_at: string | null;
  content_hash: string;
  created_at: string;
  session_id: string | null;
  metadata: Record<string, unknown>;
  status: LifecycleStatus;
  kind: MemoryKind;
}

export interface MemoryRecordListResponse {
  records: MemoryRecord[];
  count: number;
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface MemoryRecordListFilters {
  kindFilter?: MemoryKind[];
  sourceTypeFilter?: string[];
  limit?: number;
  offset?: number;
}

export interface BatchDeleteResponse {
  deleted: string[];
  not_found: string[];
}

// --- API functions ---

export function listMemoryRecords(
  workspaceId: string,
  filters: MemoryRecordListFilters = {},
): Promise<MemoryRecordListResponse> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  params.set('limit', String(filters.limit ?? 50));
  params.set('offset', String(filters.offset ?? 0));
  (filters.kindFilter ?? []).forEach((k) => params.append('kind_filter', k));
  (filters.sourceTypeFilter ?? []).forEach((s) =>
    params.append('source_type_filter', s),
  );
  return apiFetch<MemoryRecordListResponse>(
    `/api/v1/memory/records?${params}`,
  );
}

export function getMemoryRecord(
  workspaceId: string,
  id: string,
): Promise<MemoryRecord> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  return apiFetch<MemoryRecord>(
    `/api/v1/memory/records/${id}?${params}`,
  );
}

export function batchDeleteMemoryRecords(
  workspaceId: string,
  recordIds: string[],
): Promise<BatchDeleteResponse> {
  const params = new URLSearchParams({ workspace_id: workspaceId });
  return apiFetch<BatchDeleteResponse>(
    `/api/v1/memory/records/batch-delete?${params}`,
    {
      method: 'POST',
      body: JSON.stringify({ record_ids: recordIds }),
    },
  );
}
