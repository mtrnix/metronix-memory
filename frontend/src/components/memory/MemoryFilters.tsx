import type { MemoryKind } from '@/api/memory';

const KIND_OPTIONS: Array<{ value: MemoryKind | 'all'; label: string }> = [
  { value: 'all', label: 'All kinds' },
  { value: 'fact', label: 'Fact' },
  { value: 'preference', label: 'Preference' },
  { value: 'pinned', label: 'Pinned' },
];

interface MemoryFiltersProps {
  kind: MemoryKind | 'all';
  onKindChange: (kind: MemoryKind | 'all') => void;
  sourceType: string;
  onSourceTypeChange: (sourceType: string) => void;
  sourceTypeOptions: string[];
}

const SELECT_CLASSES =
  'rounded-lg border border-border bg-surface px-3 py-1.5 text-sm text-text focus:border-primary focus:outline-none';

export default function MemoryFilters({
  kind,
  onKindChange,
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
        {KIND_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
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
