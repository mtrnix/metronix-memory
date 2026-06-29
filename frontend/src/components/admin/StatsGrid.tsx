import type { WorkspaceStatsResponse } from '@/shared';

interface StatsGridProps {
  stats: WorkspaceStatsResponse | null;
}

export default function StatsGrid({ stats }: StatsGridProps) {
  if (!stats) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5 text-center text-sm text-text-muted">
        No workspace stats available
      </div>
    );
  }

  const items = [
    { label: 'Files', value: stats.file_count },
    { label: 'Chunks', value: stats.chunk_count },
    { label: 'Entities', value: stats.entity_count },
    { label: 'Jira Issues', value: stats.jira_issue_count },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <div
          key={item.label}
          className="rounded-xl border border-border bg-surface p-5"
        >
          <p className="text-xs text-text-muted">{item.label}</p>
          <p className="mt-1 text-2xl font-semibold text-text">
            {item.value.toLocaleString()}
          </p>
        </div>
      ))}
    </div>
  );
}
