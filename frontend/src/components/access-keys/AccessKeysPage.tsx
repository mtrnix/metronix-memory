import { useState } from 'react';
import { KeyRound, Loader2, Plus, Trash2 } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { listAllUsers, listApiKeys, revokeApiKey } from '@/api/users';
import type { ApiKey } from '@/api/users';
import { ApiError } from '@/shared/api/errors';
import { ConfirmDialog, ErrorMessage } from '@/shared';
import CreateApiKeyDialog from './CreateApiKeyDialog';

function queryErrorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function formatCreatedAt(value: string): string {
  return new Date(value).toLocaleString();
}

export default function AccessKeysPage() {
  const queryClient = useQueryClient();
  const [selectedUserId, setSelectedUserId] = useState('');
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [keyToRevoke, setKeyToRevoke] = useState<ApiKey | null>(null);

  const usersQuery = useQuery({
    queryKey: ['admin-users'],
    queryFn: listAllUsers,
  });
  const activeUserId = selectedUserId || usersQuery.data?.[0]?.id || '';
  const keysQuery = useQuery({
    queryKey: ['api-keys', activeUserId],
    queryFn: () => listApiKeys(activeUserId),
    enabled: Boolean(activeUserId),
  });

  const revokeMutation = useMutation({
    mutationFn: ({ userId, keyPrefix }: { userId: string; keyPrefix: string }) =>
      revokeApiKey(userId, keyPrefix),
    onSuccess: async (_result, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['api-keys', variables.userId] });
      setKeyToRevoke(null);
    },
  });

  function handleRevokeConfirm() {
    if (!keyToRevoke || !activeUserId || revokeMutation.isPending) return;
    revokeMutation.mutate({
      userId: activeUserId,
      keyPrefix: keyToRevoke.key_prefix,
    });
  }

  function handleCreated() {
    void queryClient.invalidateQueries({ queryKey: ['api-keys', activeUserId] });
  }

  function openRevokeDialog(key: ApiKey) {
    revokeMutation.reset();
    setKeyToRevoke(key);
  }

  function closeRevokeDialog() {
    revokeMutation.reset();
    setKeyToRevoke(null);
  }

  const revokeMessage = keyToRevoke
    ? `Revoke ${keyToRevoke.key_prefix}? This cannot be undone.${
        revokeMutation.isError
          ? ` ${queryErrorMessage(revokeMutation.error, 'Unable to revoke access key.')}`
          : ''
      }`
    : 'Revoke this key? This cannot be undone.';

  if (usersQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 size={24} className="animate-spin text-text-muted" />
      </div>
    );
  }

  if (usersQuery.isError) {
    return (
      <div className="p-6">
        <ErrorMessage
          message={queryErrorMessage(usersQuery.error, 'Unable to load users.')}
          onRetry={() => void usersQuery.refetch()}
        />
      </div>
    );
  }

  const users = usersQuery.data ?? [];

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold text-text">Access keys</h1>
            <p className="mt-1 text-sm text-text-muted">
              Create and revoke personal access keys for an admin user.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreateDialogOpen(true)}
            disabled={!activeUserId}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus size={16} />
            Create key
          </button>
        </div>

        {users.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border py-12 text-center">
            <p className="text-sm text-text-muted">No users are available.</p>
          </div>
        ) : (
          <>
            <div className="max-w-md">
              <label htmlFor="access-key-user" className="mb-1 block text-xs font-medium text-text-muted">
                User
              </label>
              <select
                id="access-key-user"
                value={activeUserId}
                onChange={(event) => setSelectedUserId(event.target.value)}
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text focus:border-primary focus:outline-none"
              >
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.display_name || user.email} ({user.email})
                  </option>
                ))}
              </select>
            </div>

            {keysQuery.isLoading ? (
              <div className="flex justify-center py-12">
                <Loader2 size={24} className="animate-spin text-text-muted" />
              </div>
            ) : keysQuery.isError ? (
              <ErrorMessage
                message={queryErrorMessage(keysQuery.error, 'Unable to load access keys.')}
                onRetry={() => void keysQuery.refetch()}
              />
            ) : keysQuery.data?.keys.length ? (
              <div className="overflow-hidden rounded-xl border border-border">
                <table className="w-full text-left text-sm">
                  <thead className="bg-surface-hover text-xs uppercase tracking-wide text-text-muted">
                    <tr>
                      <th className="px-4 py-3 font-medium">User Key</th>
                      <th className="px-4 py-3 font-medium">Label</th>
                      <th className="px-4 py-3 font-medium">Created</th>
                      <th className="px-4 py-3 text-right font-medium">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {keysQuery.data.keys.map((key) => (
                      <tr key={key.id}>
                        <td className="px-4 py-3 font-mono text-text">{key.key_prefix}</td>
                        <td className="px-4 py-3 text-text-muted">{key.label}</td>
                        <td className="px-4 py-3 text-text-muted">{formatCreatedAt(key.created_at)}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => openRevokeDialog(key)}
                            aria-label={`Revoke ${key.key_prefix}`}
                            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-error transition-colors hover:bg-error/10"
                          >
                            <Trash2 size={14} />
                            Revoke
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="rounded-xl border border-dashed border-border py-12 text-center">
                <KeyRound size={24} className="mx-auto text-text-dim" />
                <p className="mt-3 text-sm text-text-muted">No access keys for this user.</p>
              </div>
            )}
          </>
        )}
      </div>

      {createDialogOpen && (
        <CreateApiKeyDialog
          open
          userId={activeUserId}
          onClose={() => setCreateDialogOpen(false)}
          onCreated={handleCreated}
        />
      )}
      <ConfirmDialog
        open={keyToRevoke !== null}
        title="Revoke access key"
        message={revokeMessage}
        confirmLabel={revokeMutation.isPending ? 'Revoking…' : 'Revoke'}
        destructive
        onConfirm={handleRevokeConfirm}
        onCancel={closeRevokeDialog}
      />
    </div>
  );
}
