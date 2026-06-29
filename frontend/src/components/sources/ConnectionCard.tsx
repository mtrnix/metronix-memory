import { useState } from 'react';
import {
  RefreshCw,
  Pencil,
  Trash2,
  Plug,
  AlertCircle,
  Check,
  CheckCircle2,
  XCircle,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';
import type { Connection, ConnectorSchema } from '@/api/connections';
import {
  // useUpdateConnection,
  useDeleteConnection,
  useTestConnection,
  useSyncConnection,
  useLatestSyncLog,
} from '@/hooks/useConnections';

interface ConnectionCardProps {
  connection: Connection;
  schema?: ConnectorSchema;
  onEdit: () => void;
}

const CONNECTOR_COLORS: Record<string, string> = {
  confluence: '#22d3ee',
  jira: '#60a5fa',
  notion: '#e2e8f0',
  github: '#8b949e',
  google_drive: '#34a853',
  slack_history: '#e01e5a',
  telegram: '#26a5e4',
  discord: '#5865f2',
  slack: '#e01e5a',
};

const CONNECTOR_ICONS: Record<string, string> = {
  confluence: '📄',
  jira: '📋',
  notion: '📝',
  github: '🐙',
  google_drive: '📁',
  slack_history: '💬',
  telegram: '✈️',
  discord: '🎮',
  slack: '💬',
};

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; text: string; label: string }> = {
    connected: { bg: 'bg-success/15', text: 'text-success', label: 'Connected' },
    active: { bg: 'bg-success/15', text: 'text-success', label: 'Connected' },
    error: { bg: 'bg-error/15', text: 'text-error', label: 'Error' },
    syncing: { bg: 'bg-accent/15', text: 'text-accent', label: 'Syncing' },
    disabled: { bg: 'bg-text-dim/15', text: 'text-text-dim', label: 'Disabled' },
  };
  const s = map[status] ?? { bg: 'bg-text-dim/15', text: 'text-text-dim', label: status };

  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.bg} ${s.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${s.text} bg-current`} />
      {s.label}
    </span>
  );
}

export default function ConnectionCard({
  connection,
  schema,
  onEdit,
}: ConnectionCardProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  // const updateMutation = useUpdateConnection();
  const deleteMutation = useDeleteConnection();
  const testMutation = useTestConnection();
  const syncMutation = useSyncConnection();

  const color = CONNECTOR_COLORS[connection.connector_type] ?? '#6366f1';
  const icon = CONNECTOR_ICONS[connection.connector_type] ?? '🔗';
  const label = schema?.label ?? connection.connector_type;
  const isConnector = schema?.category !== 'channel';

  // function handleToggleEnabled() {
  //   updateMutation.mutate(
  //     { id: connection.id, data: { enabled: !connection.enabled } },
  //     {
  //       onSuccess: () => toast.success(`Connection ${connection.enabled ? 'disabled' : 'enabled'}`),
  //       onError: (e) => toast.error(e.message),
  //     },
  //   );
  // }

  const { data: lastSync } = useLatestSyncLog(connection.id, connection.status);

  function renderSyncSummary() {
    if (!lastSync) return null;

    const duration = (lastSync.duration_ms / 1000).toFixed(1);

    if (lastSync.status === 'running') {
      return (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-accent">
          <Loader2 size={12} className="animate-spin" />
          <span>Running… (started {relativeTime(lastSync.started)})</span>
        </div>
      );
    }

    if (lastSync.status === 'failed') {
      const err = lastSync.errors[0] ?? 'Unknown error';
      return (
        <div className="mt-2 flex items-start gap-1.5 text-xs text-error">
          <XCircle size={12} className="mt-0.5 shrink-0" />
          <span className="truncate" title={err}>
            Last sync failed: {err}
          </span>
        </div>
      );
    }

    // success | partial
    const Icon = lastSync.status === 'partial' ? AlertCircle : CheckCircle2;
    const color = lastSync.status === 'partial' ? 'text-warning' : 'text-success';

    return (
      <div className={`mt-2 flex items-center gap-1.5 text-xs ${color}`}>
        <Icon size={12} />
        <span>
          Last sync: {lastSync.documents_fetched} fetched · {lastSync.documents_new} new · {lastSync.qdrant_chunks} chunks · {duration}s
        </span>
      </div>
    );
  }

  function handleTest() {
    testMutation.mutate(connection.id, {
      onSuccess: (result) => {
        if (result.success) {
          toast.success(result.message ?? 'Connection successful');
        } else {
          toast.error(result.error ?? 'Connection test failed');
        }
      },
      onError: (e) => toast.error(e.message),
    });
  }

  function handleSync() {
    syncMutation.mutate(connection.id, {
      onSuccess: (r) => toast.success(r.message ?? 'Sync started'),
      onError: (e) => toast.error(e.message),
    });
  }

  function handleDelete() {
    deleteMutation.mutate(connection.id, {
      onSuccess: () => {
        toast.success(`Deleted "${connection.name}"`);
        setConfirmDelete(false);
      },
      onError: (e) => toast.error(e.message),
    });
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-light">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-lg"
            style={{ backgroundColor: color + '20', color }}
          >
            {icon}
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-text">{connection.name}</h3>
            <p className="text-xs text-text-muted">{label}</p>
          </div>
        </div>
        <StatusBadge status={connection.enabled ? connection.status : 'disabled'} />
      </div>

      {/* Error message */}
      {connection.error_message && (
        <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-error/10 px-3 py-2">
          <AlertCircle size={14} className="mt-0.5 shrink-0 text-error" />
          <p className="text-xs text-error">{connection.error_message}</p>
        </div>
      )}

      {/* Meta */}
      <div className="mt-3 flex items-center gap-3 text-xs text-text-dim">
        {connection.last_synced_at && (
          <span>Synced {relativeTime(connection.last_synced_at)}</span>
        )}
      </div>
      {renderSyncSummary()}

      {/* Actions */}
      <div className="mt-4 flex items-center justify-between">
        {/* Left: toggle — disabled until backend supports enable/disable */}
        {/* <button
          onClick={handleToggleEnabled}
          disabled={updateMutation.isPending}
          className="relative h-5 w-9 rounded-full transition-colors"
          style={{ backgroundColor: connection.enabled ? color : '#2a2e3d' }}
          title={connection.enabled ? 'Disable' : 'Enable'}
        >
          <span
            className="absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform"
            style={{ left: connection.enabled ? '18px' : '2px' }}
          />
        </button> */}

        {/* Right: action buttons */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleTest}
            disabled={testMutation.isPending}
            className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-text transition-colors"
            title="Test connection"
          >
            {testMutation.isPending ? (
              <Loader2 size={13} className="animate-spin" />
            ) : testMutation.isSuccess && testMutation.data.success ? (
              <Check size={13} className="text-success" />
            ) : (
              <Plug size={13} />
            )}
            Test
          </button>

          {isConnector && (
            <button
              onClick={handleSync}
              disabled={syncMutation.isPending || connection.status === 'syncing'}
              className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40 transition-colors"
              title="Sync now"
            >
              <RefreshCw
                size={13}
                className={syncMutation.isPending || connection.status === 'syncing' ? 'animate-spin' : ''}
              />
              Sync
            </button>
          )}

          <button
            onClick={onEdit}
            className="rounded-lg p-1.5 text-text-muted hover:bg-surface-hover hover:text-text transition-colors"
            title="Edit"
          >
            <Pencil size={13} />
          </button>

          <button
            onClick={() => setConfirmDelete(true)}
            className="rounded-lg p-1.5 text-text-muted hover:bg-error/15 hover:text-error transition-colors"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {/* Delete confirmation */}
      {confirmDelete && (
        <div className="mt-3 rounded-lg border border-error/30 bg-error/10 p-3">
          <p className="mb-2 text-xs text-text">
            Delete connection &ldquo;{connection.name}&rdquo;? This will not remove synced data.
          </p>
          <div className="flex gap-2">
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
              className="rounded-lg bg-error px-3 py-1 text-xs font-medium text-white hover:bg-error/80 disabled:opacity-50 transition-colors"
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="rounded-lg px-3 py-1 text-xs text-text-muted hover:text-text transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
