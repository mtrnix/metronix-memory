import { useEffect, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { createApiKey } from '@/api/users';
import { ApiError } from '@/shared/api/errors';

interface CreateApiKeyDialogProps {
  open: boolean;
  userId: string;
  onClose: () => void;
  onCreated: () => void;
}

export default function CreateApiKeyDialog({
  open,
  userId,
  onClose,
  onCreated,
}: CreateApiKeyDialogProps) {
  const [label, setLabel] = useState('');
  const [rawKey, setRawKey] = useState('');
  const [copyStatus, setCopyStatus] = useState<'idle' | 'copied' | 'error'>('idle');
  const rawKeyRef = useRef('');
  const canReceiveSecretRef = useRef(true);

  const createMutation = useMutation({
    mutationFn: async (keyLabel: string) => {
      const response = await createApiKey(userId, keyLabel);
      if (!canReceiveSecretRef.current) return;
      rawKeyRef.current = response.raw_key;
      setRawKey(response.raw_key);
    },
    onSuccess: onCreated,
  });

  useEffect(() => {
    canReceiveSecretRef.current = true;
    return () => {
      canReceiveSecretRef.current = false;
      rawKeyRef.current = '';
    };
  }, []);

  function handleClose() {
    canReceiveSecretRef.current = false;
    rawKeyRef.current = '';
    setRawKey('');
    setLabel('');
    setCopyStatus('idle');
    createMutation.reset();
    onClose();
  }

  function handleCreate() {
    const trimmedLabel = label.trim();
    if (!trimmedLabel) return;
    createMutation.mutate(trimmedLabel);
  }

  async function handleCopy() {
    if (!rawKeyRef.current || !navigator.clipboard) {
      setCopyStatus('error');
      return;
    }

    try {
      await navigator.clipboard.writeText(rawKeyRef.current);
      setCopyStatus('copied');
    } catch {
      setCopyStatus('error');
    }
  }

  if (!open) return null;

  const errorMessage = createMutation.error instanceof ApiError
    ? createMutation.error.message
    : 'Unable to create the access key.';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={handleClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-api-key-title"
        className="relative w-full max-w-lg rounded-xl border border-border bg-surface p-6 shadow-2xl"
      >
        <div className="mb-5 flex items-center justify-between">
          <h2 id="create-api-key-title" className="text-lg font-semibold text-text">
            {rawKey ? 'Access key created' : 'Create access key'}
          </h2>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close dialog"
            className="text-text-muted transition-colors hover:text-text"
          >
            <X size={18} />
          </button>
        </div>

        {rawKey ? (
          <div className="space-y-4">
            <div className="rounded-lg border border-warning/30 bg-warning/10 p-4 text-sm text-warning">
              Copy this key now. For security, it will not be shown again after you close this dialog.
            </div>
            <code className="block break-all rounded-lg border border-border bg-bg p-3 font-mono text-sm text-text">
              {rawKey}
            </code>
            {copyStatus === 'error' && (
              <p className="text-xs text-error">
                Could not copy automatically. Select the key above and copy it manually.
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={handleCopy}
                className="rounded-lg border border-border px-4 py-2 text-sm text-text transition-colors hover:bg-surface-hover"
              >
                {copyStatus === 'copied' ? 'Copied' : 'Copy'}
              </button>
              <button
                type="button"
                onClick={handleClose}
                className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover"
              >
                Close
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label htmlFor="api-key-label" className="mb-1 block text-xs font-medium text-text-muted">
                Label
              </label>
              <input
                id="api-key-label"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="hermes-native-production"
                autoFocus
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
              />
            </div>
            {createMutation.isError && (
              <p className="rounded-lg border border-error/20 bg-error/10 p-3 text-sm text-error">
                {errorMessage}
              </p>
            )}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={handleClose}
                className="rounded-lg px-4 py-2 text-sm text-text-muted transition-colors hover:bg-surface-hover"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={!label.trim() || createMutation.isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-40"
              >
                {createMutation.isPending && <Loader2 size={14} className="animate-spin" />}
                Create
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
