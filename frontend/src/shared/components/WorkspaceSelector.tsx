import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Plus } from 'lucide-react';
import { useWorkspaces } from '../hooks/useWorkspaces';
import StatusDot from './StatusDot';

export default function WorkspaceSelector() {
  const { workspaces, active, activate, create } = useWorkspaces();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
        setCreating(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setOpen(false);
        setCreating(false);
      }
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  async function handleCreate() {
    if (!name.trim()) return;
    await create({ name: name.trim(), description: desc.trim() || undefined });
    setName('');
    setDesc('');
    setCreating(false);
    setOpen(false);
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm hover:bg-surface-hover transition-colors"
      >
        {active && <StatusDot ok />}
        <span className="flex-1 truncate text-left">
          {active?.name ?? 'No workspace'}
        </span>
        <ChevronDown size={14} className="text-text-muted" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-lg border border-border bg-surface shadow-xl">
          <div className="max-h-48 overflow-y-auto p-1">
            {workspaces.map((ws) => (
              <button
                key={ws.workspace_id}
                onClick={() => {
                  activate(ws.workspace_id);
                  setOpen(false);
                }}
                className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors ${
                  ws.workspace_id === active?.workspace_id
                    ? 'bg-primary-muted text-primary-hover'
                    : 'hover:bg-surface-hover'
                }`}
              >
                <StatusDot ok={ws.is_active} />
                <span className="truncate">{ws.name}</span>
              </button>
            ))}
          </div>

          <div className="border-t border-border p-1">
            {creating ? (
              <div className="space-y-2 p-2">
                <input
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Workspace name"
                  className="w-full rounded-md border border-border bg-bg px-3 py-1.5 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
                <input
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="Description (optional)"
                  className="w-full rounded-md border border-border bg-bg px-3 py-1.5 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleCreate}
                    className="flex-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-primary-hover transition-colors"
                  >
                    Create
                  </button>
                  <button
                    onClick={() => setCreating(false)}
                    className="rounded-md px-3 py-1.5 text-sm text-text-muted hover:text-text transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-text-muted hover:bg-surface-hover hover:text-text transition-colors"
              >
                <Plus size={14} />
                New workspace
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
