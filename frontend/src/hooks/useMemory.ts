import {
  useQuery,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query';
import { useWorkspaceStore } from '@/shared';
import {
  listMemoryRecords,
  getMemoryRecord,
  getMemoryFacets,
  batchDeleteMemoryRecords,
} from '@/api/memory';
import type { MemoryKind } from '@/api/memory';

const PAGE_SIZE = 50;

function useActiveWorkspaceId(): string | null {
  const active = useWorkspaceStore((s) => s.active);
  return active?.workspace_id ?? null;
}

export interface MemoryListFilterState {
  kindFilter: MemoryKind[];
  sourceTypeFilter: string[];
}

export function useMemoryRecords(filters: MemoryListFilterState) {
  const workspaceId = useActiveWorkspaceId();
  return useInfiniteQuery({
    queryKey: ['memory', 'records', workspaceId, filters],
    queryFn: ({ pageParam }) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return listMemoryRecords(workspaceId, {
        kindFilter: filters.kindFilter,
        sourceTypeFilter: filters.sourceTypeFilter,
        limit: PAGE_SIZE,
        offset: pageParam,
      });
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.has_more ? lastPage.offset + lastPage.limit : undefined,
    enabled: !!workspaceId,
  });
}

export function useMemoryRecord(id: string | null) {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['memory', 'record', workspaceId, id],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      if (!id) throw new Error('No record id');
      return getMemoryRecord(workspaceId, id);
    },
    enabled: !!workspaceId && !!id,
  });
}

export function useMemoryFacets() {
  const workspaceId = useActiveWorkspaceId();
  return useQuery({
    queryKey: ['memory', 'facets', workspaceId],
    queryFn: () => {
      if (!workspaceId) throw new Error('No workspace selected');
      return getMemoryFacets(workspaceId);
    },
    enabled: !!workspaceId,
  });
}

export function useBatchDeleteMemoryRecords() {
  const qc = useQueryClient();
  const workspaceId = useActiveWorkspaceId();
  return useMutation({
    mutationFn: (recordIds: string[]) => {
      if (!workspaceId) throw new Error('No workspace selected');
      return batchDeleteMemoryRecords(workspaceId, recordIds);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['memory', 'records'] });
      qc.invalidateQueries({ queryKey: ['memory', 'facets'] });
    },
  });
}
