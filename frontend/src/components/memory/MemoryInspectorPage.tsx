import { useMemo, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { ConfirmDialog, useAuthStore } from '@/shared';
import { useMemoryRecords, useBatchDeleteMemoryRecords } from '@/hooks/useMemory';
import type { MemoryKind, MemoryRecord } from '@/api/memory';
import MemoryFilters from './MemoryFilters';
import MemoryList from './MemoryList';
import MemoryDetailPanel from './MemoryDetailPanel';

export default function MemoryInspectorPage() {
  const [kindFilter, setKindFilter] = useState<MemoryKind | 'all'>('all');
  const [sourceTypeFilter, setSourceTypeFilter] = useState<string>('all');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const role = useAuthStore((s) => s.role);
  const canDelete = role !== 'viewer';

  const {
    data,
    isLoading,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useMemoryRecords({
    kindFilter: kindFilter === 'all' ? [] : [kindFilter],
    sourceTypeFilter: sourceTypeFilter === 'all' ? [] : [sourceTypeFilter],
  });

  const records: MemoryRecord[] = useMemo(
    () => data?.pages.flatMap((page) => page.records) ?? [],
    [data],
  );

  const sourceTypeOptions = useMemo(() => {
    const seen = new Set<string>();
    records.forEach((r) => {
      if (r.source_type) seen.add(r.source_type);
    });
    return Array.from(seen).sort();
  }, [records]);

  const deleteMutation = useBatchDeleteMemoryRecords();

  function resetSelectionAndFilter<T>(setter: (value: T) => void) {
    return (value: T) => {
      setSelectedIds(new Set());
      setter(value);
    };
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function handleDelete() {
    const ids = Array.from(selectedIds);
    deleteMutation.mutate(ids, {
      onSuccess: (result) => {
        toast.success(
          `Deleted ${result.deleted.length} ${result.deleted.length === 1 ? 'record' : 'records'}`,
        );
        if (result.not_found.length > 0) {
          toast.error(`${result.not_found.length} record(s) were already gone`);
        }
        if (activeId && ids.includes(activeId)) {
          setActiveId(null);
        }
        setSelectedIds(new Set());
        setConfirmOpen(false);
      },
      onError: (e) => {
        toast.error(e.message);
        setConfirmOpen(false);
      },
    });
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <div>
          <h1 className="text-lg font-semibold text-text">Memory Inspector</h1>
          <p className="text-sm text-text-muted">
            Browse, filter, and delete stored agent memory records.
          </p>
        </div>
        <button
          onClick={() => setConfirmOpen(true)}
          disabled={selectedIds.size === 0 || !canDelete}
          title={!canDelete ? 'Insufficient permissions' : undefined}
          className="flex items-center gap-2 rounded-lg bg-error px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Trash2 size={16} />
          Delete{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}
        </button>
      </div>

      <div className="border-b border-border px-6 py-3">
        <MemoryFilters
          kind={kindFilter}
          onKindChange={resetSelectionAndFilter(setKindFilter)}
          sourceType={sourceTypeFilter}
          onSourceTypeChange={resetSelectionAndFilter(setSourceTypeFilter)}
          sourceTypeOptions={sourceTypeOptions}
        />
      </div>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex w-96 shrink-0 flex-col border-r border-border">
          <MemoryList
            records={records}
            selectedIds={selectedIds}
            activeId={activeId}
            onToggleSelect={toggleSelect}
            onSelect={setActiveId}
            hasNextPage={!!hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            onLoadMore={fetchNextPage}
            isLoading={isLoading}
          />
        </div>
        <MemoryDetailPanel recordId={activeId} />
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="Delete memory records"
        message={`This will permanently delete ${selectedIds.size} memory ${selectedIds.size === 1 ? 'record' : 'records'}. This cannot be undone.`}
        confirmLabel={deleteMutation.isPending ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
