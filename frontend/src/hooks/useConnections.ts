import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useWorkspaceStore } from '@/shared';
import {
  getSchemas,
  listConnections,
  createConnection,
  updateConnection,
  deleteConnection,
  testConnection,
  syncConnection,
  getLatestSyncLog,
  listSyncLogs,
} from '@/api/connections';
import type {
  CreateConnectionRequest,
  UpdateConnectionRequest,
} from '@/api/connections';

function useActiveWorkspaceId(): string | null {
  const active = useWorkspaceStore((s) => s.active);
  return active?.workspace_id ?? null;
}

export function useSchemas() {
  return useQuery({
    queryKey: ['connections', 'schemas'],
    queryFn: getSchemas,
    staleTime: 5 * 60_000,
  });
}

export function useConnections(category?: 'connector' | 'channel') {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['connections', 'list', workspaceId, category],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      return listConnections(workspaceId, category);
    },
    enabled: !!workspaceId,
    refetchInterval: 15_000,
  });
}

export function useCreateConnection() {
  const qc = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (data: CreateConnectionRequest) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return createConnection(workspaceId, data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections', 'list'] });
    },
  });
}

export function useUpdateConnection() {
  const qc = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (params: { id: string; data: UpdateConnectionRequest }) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return updateConnection(params.id, workspaceId, params.data);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections', 'list'] });
    },
  });
}

export function useDeleteConnection() {
  const qc = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return deleteConnection(id, workspaceId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections', 'list'] });
    },
  });
}

export function useTestConnection() {
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return testConnection(id, workspaceId);
    },
  });
}

export function useSyncConnection() {
  const qc = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (id: string) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return syncConnection(id, workspaceId);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['connections', 'list'] });
    },
  });
}

export function useLatestSyncLog(
  connectionId: string | undefined,
  connectionStatus: string | undefined,
) {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['connections', 'latest-sync-log', workspaceId, connectionId],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      if (!connectionId) throw new Error('No connection id');
      return getLatestSyncLog(workspaceId, connectionId);
    },
    enabled: !!workspaceId && !!connectionId,
    // Poll every 5s while the connection is actively syncing;
    // otherwise refresh at the normal 15s cadence used elsewhere.
    refetchInterval: connectionStatus === 'syncing' ? 5_000 : 15_000,
  });
}

export function useSyncHistory(connectionId: string | undefined) {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['connections', 'sync-history', workspaceId, connectionId],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      if (!connectionId) throw new Error('No connection id');
      return listSyncLogs(workspaceId, connectionId, 10);
    },
    enabled: !!workspaceId && !!connectionId,
  });
}
