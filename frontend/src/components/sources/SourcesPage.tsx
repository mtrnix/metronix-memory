import { useState } from 'react';
import { Plus, Loader2, AlertCircle, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { uploadFile } from '@/api/upload';
import { useWorkspaceStore } from '@/shared';
import { useSchemas, useConnections } from '@/hooks/useConnections';
import type { Connection } from '@/api/connections';
import ConnectionCard from './ConnectionCard';
import ConnectionDialog from './ConnectionDialog';
import UploadZone from './UploadZone';

export default function SourcesPage() {
  const active = useWorkspaceStore((s) => s.active);
  const workspaceId = active?.workspace_id;

  const schemasQuery = useSchemas();
  const connectorsQuery = useConnections('connector');
  const channelsQuery = useConnections('channel');

  const [uploading, setUploading] = useState(false);

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogCategory, setDialogCategory] = useState<'connector' | 'channel'>('connector');
  const [editingConnection, setEditingConnection] = useState<Connection | null>(null);

  function openAddDialog(category: 'connector' | 'channel') {
    setDialogCategory(category);
    setEditingConnection(null);
    setDialogOpen(true);
  }

  function openEditDialog(connection: Connection) {
    const schema = schemasQuery.data?.[connection.connector_type];
    setDialogCategory(schema?.category ?? 'connector');
    setEditingConnection(connection);
    setDialogOpen(true);
  }

  async function handleUpload(file: File) {
    setUploading(true);
    try {
      const res = await uploadFile(file, workspaceId);
      toast.success(`Indexed ${res.file_name}: ${res.chunks} chunks`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  }

  const schemas = schemasQuery.data ?? {};

  const schemasUnavailable = schemasQuery.isLoading || schemasQuery.isError;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-8">
      {/* Schema load error */}
      {schemasQuery.isError && (
        <div className="flex items-center gap-2 rounded-lg border border-error/30 bg-error/10 px-4 py-3 text-sm text-error">
          <AlertCircle size={16} className="shrink-0" />
          <span>Failed to load connection types.</span>
          <button
            onClick={() => schemasQuery.refetch()}
            className="ml-1 inline-flex items-center gap-1 text-primary hover:underline"
          >
            <RefreshCw size={13} />
            Retry
          </button>
        </div>
      )}

      {/* Connectors */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text">Connectors</h2>
          <button
            onClick={() => openAddDialog('connector')}
            disabled={schemasUnavailable}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover disabled:opacity-40 transition-colors"
          >
            <Plus size={14} />
            Add Connection
          </button>
        </div>

        {connectorsQuery.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-text-muted" />
          </div>
        ) : connectorsQuery.data?.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {connectorsQuery.data.map((c) => (
              <ConnectionCard
                key={c.id}
                connection={c}
                schema={schemas[c.connector_type]}
                onEdit={() => openEditDialog(c)}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border py-12 text-center">
            <p className="text-sm text-text-muted">No connectors configured</p>
            <p className="mt-1 text-xs text-text-dim">
              Click &ldquo;Add Connection&rdquo; to connect your first data source
            </p>
          </div>
        )}
      </section>

      {/* Channels */}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-text">Channels</h2>
          <button
            onClick={() => openAddDialog('channel')}
            disabled={schemasUnavailable}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-hover disabled:opacity-40 transition-colors"
          >
            <Plus size={14} />
            Add Channel
          </button>
        </div>

        {channelsQuery.isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 size={24} className="animate-spin text-text-muted" />
          </div>
        ) : channelsQuery.data?.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {channelsQuery.data.map((c) => (
              <ConnectionCard
                key={c.id}
                connection={c}
                schema={schemas[c.connector_type]}
                onEdit={() => openEditDialog(c)}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-border py-12 text-center">
            <p className="text-sm text-text-muted">No channels configured</p>
            <p className="mt-1 text-xs text-text-dim">
              Click &ldquo;Add Channel&rdquo; to connect a messaging platform
            </p>
          </div>
        )}
      </section>

      {/* Upload */}
      <section>
        <h2 className="mb-4 text-lg font-semibold text-text">Upload Documents</h2>
        <UploadZone onUpload={handleUpload} uploading={uploading} />
      </section>

      {/* Add/Edit Dialog */}
      <ConnectionDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        schemas={schemas}
        category={dialogCategory}
        workspaceId={workspaceId ?? ''}
        editConnection={editingConnection}
      />
    </div>
  );
}
