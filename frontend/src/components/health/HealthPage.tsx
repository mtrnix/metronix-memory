import { RefreshCw } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { useHealth, useWorkspaceStore, getWorkspaceStats } from '@/shared';
import { useMetrics } from '@/hooks/useMetrics';
import ServiceCard from '@/components/admin/ServiceCard';
import StatsGrid from '@/components/admin/StatsGrid';
import MetricsTable from '@/components/admin/MetricsTable';

const SERVICES = [
  { key: 'qdrant', name: 'Qdrant', icon: '\u{1F9E0}' },
  { key: 'neo4j', name: 'Neo4j', icon: '\u{1F578}\uFE0F' },
  { key: 'ollama', name: 'Ollama', icon: '\u{1F916}' },
];

export default function HealthPage() {
  const { health, error } = useHealth();
  const { metrics, loading: metricsLoading, refresh: refreshMetrics } = useMetrics();
  const workspaceId = useWorkspaceStore((s) => s.active?.workspace_id);

  const { data: stats = null } = useQuery({
    queryKey: ['workspace-stats', workspaceId],
    queryFn: () => getWorkspaceStats(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 30_000,
  });

  return (
    <div className="h-full overflow-y-auto p-6 space-y-8">
      {error && (
        <div className="rounded-lg border border-error/30 bg-error/10 px-4 py-3 text-sm text-error">
          {error}
        </div>
      )}

      {/* Service Health */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-text">
          Service Health
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {SERVICES.map((svc) => (
            <ServiceCard
              key={svc.key}
              name={svc.name}
              icon={svc.icon}
              status={
                health?.services[svc.key] as 'ok' | 'error' | undefined
              }
            />
          ))}
        </div>
      </section>

      {/* Workspace Stats */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-text">
          Workspace Statistics
        </h2>
        <StatsGrid stats={stats} />
      </section>

      {/* Metrics */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text">
            Operations Metrics
          </h2>
          <button
            onClick={refreshMetrics}
            disabled={metricsLoading}
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-text-muted hover:border-border-light hover:text-text disabled:opacity-40 transition-colors"
          >
            <RefreshCw
              size={12}
              className={metricsLoading ? 'animate-spin' : ''}
            />
            Refresh Metrics
          </button>
        </div>
        <MetricsTable metrics={metrics} />
      </section>
    </div>
  );
}
