import { useState, useEffect, useCallback } from 'react';
import { X, Eye, EyeOff, Loader2, Check, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import type { Connection, ConnectorSchema } from '@/api/connections';
import { revealSecrets } from '@/api/connections';
import {
  useCreateConnection,
  useUpdateConnection,
  useTestConnection,
} from '@/hooks/useConnections';

interface ConnectionDialogProps {
  open: boolean;
  onClose: () => void;
  schemas: Record<string, ConnectorSchema>;
  category: 'connector' | 'channel';
  workspaceId: string;
  editConnection?: Connection | null;
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

export default function ConnectionDialog({
  open,
  onClose,
  schemas,
  category,
  workspaceId,
  editConnection,
}: ConnectionDialogProps) {
  const isEdit = !!editConnection;
  const [step, setStep] = useState<'select' | 'form'>(isEdit ? 'form' : 'select');
  const [selectedType, setSelectedType] = useState<string | null>(
    editConnection?.connector_type ?? null,
  );
  const [name, setName] = useState(editConnection?.name ?? '');
  const [config, setConfig] = useState<Record<string, string>>(
    editConnection?.config ?? {},
  );
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({});
  const [maskedConfig, setMaskedConfig] = useState<Record<string, string>>({});
  const [revealedConfig, setRevealedConfig] = useState<Record<string, string> | null>(null);
  const [revealLoading, setRevealLoading] = useState(false);

  const createMutation = useCreateConnection();
  const updateMutation = useUpdateConnection();
  const testMutation = useTestConnection();

  // Reset state when dialog opens/closes or editConnection changes
  useEffect(() => {
    if (open) {
      if (editConnection) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setStep('form');
        setSelectedType(editConnection.connector_type);
        setName(editConnection.name);
        setConfig({ ...editConnection.config });
        setMaskedConfig({ ...editConnection.config });
      } else {
        setStep('select');
        setSelectedType(null);
        setName('');
        setConfig({});
        setMaskedConfig({});
      }
      setShowSecrets({});
      setRevealedConfig(null);
      testMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editConnection]);

  const handleToggleSecret = useCallback(
    async (fieldName: string) => {
      const isCurrentlyVisible = showSecrets[fieldName];

      if (isCurrentlyVisible) {
        // Hide: restore masked value if user hasn't edited it
        setShowSecrets((prev) => ({ ...prev, [fieldName]: false }));
        if (revealedConfig && config[fieldName] === revealedConfig[fieldName]) {
          setConfig((prev) => ({ ...prev, [fieldName]: maskedConfig[fieldName] }));
        }
        return;
      }

      // Show: need to fetch revealed secrets if not yet fetched
      if (!revealedConfig && isEdit && editConnection) {
        setRevealLoading(true);
        try {
          const revealed = await revealSecrets(editConnection.id, workspaceId);
          setRevealedConfig(revealed.config);
          // Only replace fields that still hold the masked value
          setConfig((prev) => {
            const updated = { ...prev };
            if (prev[fieldName] === maskedConfig[fieldName]) {
              updated[fieldName] = revealed.config[fieldName] ?? prev[fieldName];
            }
            return updated;
          });
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Failed to reveal secrets';
          toast.error(message);
          setRevealLoading(false);
          return;
        }
        setRevealLoading(false);
      } else if (revealedConfig) {
        // Already fetched — just swap in the revealed value if not edited
        if (config[fieldName] === maskedConfig[fieldName]) {
          setConfig((prev) => ({
            ...prev,
            [fieldName]: revealedConfig[fieldName] ?? prev[fieldName],
          }));
        }
      }

      setShowSecrets((prev) => ({ ...prev, [fieldName]: true }));
    },
    [showSecrets, revealedConfig, isEdit, editConnection, workspaceId, config, maskedConfig],
  );

  if (!open) return null;

  const filteredSchemas = Object.values(schemas).filter(
    (s) => s.category === category,
  );
  const schema = selectedType ? schemas[selectedType] : null;

  function handleSelectType(type: string) {
    setSelectedType(type);
    setName('');
    setConfig({});
    setStep('form');
  }

  function handleConfigChange(fieldName: string, value: string) {
    setConfig((prev) => ({ ...prev, [fieldName]: value }));
  }

  function isFormValid(): boolean {
    if (!name.trim()) return false;
    if (!schema) return false;
    for (const field of schema.fields) {
      if (field.required && !config[field.name]?.trim()) return false;
    }
    return true;
  }

  function handleSave() {
    if (!selectedType || !schema) return;

    if (isEdit && editConnection) {
      updateMutation.mutate(
        { id: editConnection.id, data: { name, config } },
        {
          onSuccess: () => {
            toast.success('Connection updated');
            onClose();
          },
          onError: (e) => toast.error(e.message),
        },
      );
    } else {
      createMutation.mutate(
        { connector_type: selectedType, name, config },
        {
          onSuccess: () => {
            toast.success('Connection created');
            onClose();
          },
          onError: (e) => toast.error(e.message),
        },
      );
    }
  }

  function handleTest() {
    if (!editConnection) return;
    testMutation.mutate(editConnection.id);
  }

  const saving = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-xl border border-border bg-surface p-6 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-text">
            {isEdit
              ? 'Edit Connection'
              : step === 'select'
                ? `Add ${category === 'connector' ? 'Connection' : 'Channel'}`
                : `New ${schema?.label ?? ''} Connection`}
          </h2>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Step 1: Type selection */}
        {step === 'select' && (
          filteredSchemas.length > 0 ? (
            <div className="grid grid-cols-3 gap-3">
              {filteredSchemas.map((s) => {
                const color = CONNECTOR_COLORS[s.type] ?? '#6366f1';
                const icon = CONNECTOR_ICONS[s.type] ?? '🔗';
                return (
                  <button
                    key={s.type}
                    onClick={() => handleSelectType(s.type)}
                    className="flex flex-col items-center gap-2 rounded-xl border border-border p-4 hover:border-border-light hover:bg-surface-hover transition-colors"
                  >
                    <div
                      className="flex h-12 w-12 items-center justify-center rounded-xl text-xl"
                      style={{ backgroundColor: color + '20', color }}
                    >
                      {icon}
                    </div>
                    <span className="text-xs font-medium text-text">{s.label}</span>
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="py-8 text-center">
              <p className="text-sm text-text-muted">No connection types available.</p>
              <p className="mt-1 text-xs text-text-dim">
                Connection schemas could not be loaded. Close and try again.
              </p>
            </div>
          )
        )}

        {/* Step 2: Form */}
        {step === 'form' && schema && (
          <div className="space-y-4">
            {/* Back button in add mode */}
            {!isEdit && (
              <button
                onClick={() => setStep('select')}
                className="text-xs text-text-muted hover:text-text transition-colors"
              >
                ← Back to type selection
              </button>
            )}

            {/* Name field */}
            <div>
              <label className="mb-1 block text-xs font-medium text-text-muted">
                Connection Name
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`My ${schema.label}`}
                className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none transition-colors"
              />
            </div>

            {/* Dynamic fields from schema */}
            {schema.fields.map((field) => (
              <div key={field.name}>
                <label className="mb-1 flex items-center gap-1 text-xs font-medium text-text-muted">
                  {field.label}
                  {field.required && <span className="text-error">*</span>}
                </label>
                <div className="relative">
                  <input
                    type={
                      field.type === 'secret' && !showSecrets[field.name]
                        ? 'password'
                        : 'text'
                    }
                    value={config[field.name] ?? ''}
                    onChange={(e) => handleConfigChange(field.name, e.target.value)}
                    placeholder={field.placeholder}
                    className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none transition-colors pr-10"
                  />
                  {field.type === 'secret' && isEdit && (
                    <button
                      type="button"
                      disabled={revealLoading}
                      onClick={() => handleToggleSecret(field.name)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-text-dim hover:text-text-muted transition-colors disabled:opacity-40"
                    >
                      {revealLoading && !showSecrets[field.name] ? (
                        <Loader2 size={14} className="animate-spin" />
                      ) : showSecrets[field.name] ? (
                        <EyeOff size={14} />
                      ) : (
                        <Eye size={14} />
                      )}
                    </button>
                  )}
                </div>
                {field.type === 'secret' && isEdit && config[field.name] === '***' && (
                  <p className="mt-1 text-xs text-text-dim">
                    Click the eye icon to reveal, or clear and type a new value.
                  </p>
                )}
              </div>
            ))}

            {/* Test result */}
            {testMutation.isSuccess && (
              <div
                className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs ${
                  testMutation.data.success
                    ? 'bg-success/10 text-success'
                    : 'bg-error/10 text-error'
                }`}
              >
                {testMutation.data.success ? (
                  <Check size={14} />
                ) : (
                  <AlertCircle size={14} />
                )}
                {testMutation.data.success
                  ? testMutation.data.message ?? 'Connection successful'
                  : testMutation.data.error ?? 'Connection failed'}
              </div>
            )}
            {testMutation.isError && (
              <div className="flex items-center gap-2 rounded-lg bg-error/10 px-3 py-2 text-xs text-error">
                <AlertCircle size={14} />
                {testMutation.error.message}
              </div>
            )}

            {/* Actions */}
            <div className="flex items-center justify-between pt-2">
              <div>
                {isEdit && editConnection && (
                  <button
                    onClick={handleTest}
                    disabled={testMutation.isPending}
                    className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs text-text-muted hover:border-border-light hover:text-text disabled:opacity-40 transition-colors"
                  >
                    {testMutation.isPending && (
                      <Loader2 size={13} className="animate-spin" />
                    )}
                    Test Connection
                  </button>
                )}
              </div>
              <div className="flex gap-2">
                <button
                  onClick={onClose}
                  className="rounded-lg px-4 py-2 text-sm text-text-muted hover:text-text transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  disabled={!isFormValid() || saving}
                  className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-40 transition-colors"
                >
                  {saving && <Loader2 size={14} className="animate-spin" />}
                  {isEdit ? 'Update' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
