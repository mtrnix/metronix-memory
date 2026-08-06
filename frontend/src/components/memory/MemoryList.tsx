import { Loader2 } from 'lucide-react';
import type { MemoryRecord } from '@/api/memory';
import MemoryListItem from './MemoryListItem';

interface MemoryListProps {
  records: MemoryRecord[];
  selectedIds: Set<string>;
  activeId: string | null;
  onToggleSelect: (id: string) => void;
  onSelect: (id: string) => void;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
  isLoading: boolean;
}

export default function MemoryList({
  records,
  selectedIds,
  activeId,
  onToggleSelect,
  onSelect,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
  isLoading,
}: MemoryListProps) {
  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center text-text-muted">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  if (records.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center px-4 text-center text-sm text-text-muted">
        No memory records match the current filters.
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto">
      {records.map((record) => (
        <MemoryListItem
          key={record.id}
          record={record}
          selected={selectedIds.has(record.id)}
          isActive={activeId === record.id}
          onToggleSelect={onToggleSelect}
          onClick={onSelect}
        />
      ))}

      {hasNextPage && (
        <button
          onClick={onLoadMore}
          disabled={isFetchingNextPage}
          className="m-3 rounded-lg border border-border py-2 text-sm text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-50 transition-colors"
        >
          {isFetchingNextPage ? 'Loading…' : 'Load more'}
        </button>
      )}
    </div>
  );
}
