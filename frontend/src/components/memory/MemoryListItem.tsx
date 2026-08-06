import type { MemoryRecord, MemoryKind } from '@/api/memory';

const KIND_BADGE_STYLES: Record<MemoryKind, string> = {
  fact: 'bg-primary/10 text-primary',
  preference: 'bg-accent/10 text-accent',
  pinned: 'bg-warning/10 text-warning',
};

function truncate(text: string, max = 90): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

interface MemoryListItemProps {
  record: MemoryRecord;
  selected: boolean;
  isActive: boolean;
  onToggleSelect: (id: string) => void;
  onClick: (id: string) => void;
}

export default function MemoryListItem({
  record,
  selected,
  isActive,
  onToggleSelect,
  onClick,
}: MemoryListItemProps) {
  return (
    <div
      onClick={() => onClick(record.id)}
      className={`flex cursor-pointer items-start gap-3 border-b border-border px-3 py-2.5 transition-colors ${
        isActive ? 'bg-primary-muted' : 'hover:bg-surface-hover'
      }`}
    >
      <input
        type="checkbox"
        checked={selected}
        onClick={(e) => e.stopPropagation()}
        onChange={() => onToggleSelect(record.id)}
        className="mt-1 h-4 w-4 shrink-0 rounded border-border-light accent-primary"
        aria-label={`Select memory ${record.id}`}
      />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-text">{truncate(record.content)}</p>
        <div className="mt-1 flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-medium ${KIND_BADGE_STYLES[record.kind]}`}
          >
            {record.kind}
          </span>
          <span className="text-xs text-text-dim">
            {formatDate(record.created_at)}
          </span>
        </div>
      </div>
    </div>
  );
}
