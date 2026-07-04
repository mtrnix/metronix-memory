import type { MemoryKind } from '@/api/memory';

const KIND_LABELS: Record<MemoryKind, string> = {
  fact: 'Fact',
  preference: 'Preference',
  pinned: 'Pinned',
};

interface MemoryFiltersProps {
  kind: MemoryKind | 'all';
  onKindChange: (kind: MemoryKind | 'all') => void;
  kindOptions: MemoryKind[];
  sourceType: string;
  onSourceTypeChange: (sourceType: string) => void;
  sourceTypeOptions: string[];
}

const SELECT_CLASSES =
  'rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:border-primary focus:outline-none';

export default function MemoryFilters({
  kind,
  onKindChange,
  kindOptions,
  sourceType,
  onSourceTypeChange,
  sourceTypeOptions,
}: MemoryFiltersProps) {
  return (
    <div className="flex items-center gap-2">
      <select
        value={kind}
        onChange={(e) => onKindChange(e.target.value as MemoryKind | 'all')}
        className={SELECT_CLASSES}
        aria-label="Filter by kind"
      >
        <option value="all">All kinds</option>
        {kindOptions.map((opt) => (
          <option key={opt} value={opt}>
            {KIND_LABELS[opt]}
          </option>
        ))}
      </select>

      <select
        value={sourceType}
        onChange={(e) => onSourceTypeChange(e.target.value)}
        className={SELECT_CLASSES}
        aria-label="Filter by source type"
      >
        <option value="all">All sources</option>
        {sourceTypeOptions.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    </div>
  );
}
