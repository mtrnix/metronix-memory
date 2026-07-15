import { Loader2 } from 'lucide-react';
import { useMemoryRecord } from '@/hooks/useMemory';

interface MemoryDetailPanelProps {
  recordId: string | null;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-text-dim">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm text-text">{value}</dd>
    </div>
  );
}

export default function MemoryDetailPanel({ recordId }: MemoryDetailPanelProps) {
  const { data: record, isLoading, isError } = useMemoryRecord(recordId);

  if (!recordId) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-text-muted">
        Select a memory record to view its full text.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center text-text-muted">
        <Loader2 size={20} className="animate-spin" />
      </div>
    );
  }

  if (isError || !record) {
    return (
      <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-error">
        Failed to load this memory record.
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="rounded-xl border border-border bg-surface p-5">
        <p className="whitespace-pre-wrap text-sm text-text">{record.content}</p>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-4">
        <Field label="Kind" value={record.kind} />
        <Field label="Status" value={record.status} />
        <Field label="Scope" value={record.scope} />
        <Field label="Source type" value={record.source_type || '—'} />
        <Field label="Agent" value={record.agent_id} />
        <Field label="Created" value={new Date(record.created_at).toLocaleString()} />
        {record.tags.length > 0 && (
          <div className="col-span-2">
            <dt className="text-xs font-medium uppercase tracking-wide text-text-dim">
              Tags
            </dt>
            <dd className="mt-1 flex flex-wrap gap-1.5">
              {record.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-text-muted"
                >
                  {tag}
                </span>
              ))}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}
