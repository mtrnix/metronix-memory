import type { MetricsResponse } from '@/shared';

interface MetricsTableProps {
  metrics: MetricsResponse | null;
}

function formatDuration(sec: number): string {
  if (sec < 0.001) return '<1ms';
  if (sec < 1) return `${(sec * 1000).toFixed(0)}ms`;
  return `${sec.toFixed(2)}s`;
}

export default function MetricsTable({ metrics }: MetricsTableProps) {
  if (!metrics) {
    return (
      <div className="rounded-xl border border-border bg-surface p-5 text-center text-sm text-text-muted">
        Click "Refresh Metrics" to load
      </div>
    );
  }

  const ops = Object.entries(metrics.operations);

  return (
    <div className="rounded-xl border border-border bg-surface overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-4 py-3 font-medium text-text-muted">Operation</th>
              <th className="px-4 py-3 font-medium text-text-muted">Count</th>
              <th className="px-4 py-3 font-medium text-text-muted">Success</th>
              <th className="px-4 py-3 font-medium text-text-muted">Avg</th>
              <th className="px-4 py-3 font-medium text-text-muted">Rate</th>
            </tr>
          </thead>
          <tbody>
            {ops.map(([name, op]) => (
              <tr key={name} className="border-b border-border last:border-0">
                <td className="px-4 py-3 font-medium text-text">{name}</td>
                <td className="px-4 py-3 text-text-muted">{op.count}</td>
                <td className="px-4 py-3 text-text-muted">
                  {op.success_count}
                </td>
                <td className="px-4 py-3 text-text-muted">
                  {formatDuration(op.avg_duration_sec)}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`text-xs font-medium ${
                      op.success_rate >= 95
                        ? 'text-success'
                        : op.success_rate >= 80
                          ? 'text-warning'
                          : 'text-error'
                    }`}
                  >
                    {op.success_rate.toFixed(1)}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Cache stats */}
      <div className="border-t border-border px-4 py-3 text-xs text-text-muted">
        Embedding cache: {metrics.embedding_cache.hits} hits /{' '}
        {metrics.embedding_cache.misses} misses ({metrics.embedding_cache.size}/
        {metrics.embedding_cache.maxsize} slots) &bull; Uptime:{' '}
        {Math.floor(metrics.uptime_sec / 3600)}h{' '}
        {Math.floor((metrics.uptime_sec % 3600) / 60)}m
      </div>
    </div>
  );
}
