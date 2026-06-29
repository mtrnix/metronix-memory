import { useCallback, useEffect } from 'react';
import {
  listWorkspaces,
  createWorkspace,
  activateWorkspace,
} from '../api/workspaces';
import type { WorkspaceCreate } from '../api/types';
import { useWorkspaceStore } from '../stores/workspace';

export function useWorkspaces() {
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const active = useWorkspaceStore((s) => s.active);
  const loading = useWorkspaceStore((s) => s.loading);
  const setWorkspaces = useWorkspaceStore((s) => s.setWorkspaces);
  const setActive = useWorkspaceStore((s) => s.setActive);
  const setLoading = useWorkspaceStore((s) => s.setLoading);

  const refresh = useCallback(async () => {
    try {
      const res = await listWorkspaces();
      const found = res.workspaces.find((w) => w.is_active) ?? res.workspaces[0] ?? null;
      setWorkspaces(res.workspaces);
      setActive(found);
      setLoading(false);
    } catch {
      setLoading(false);
    }
  }, [setWorkspaces, setActive, setLoading]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const create = useCallback(
    async (data: WorkspaceCreate) => {
      const ws = await createWorkspace(data);
      await refresh();
      return ws;
    },
    [refresh],
  );

  const activate = useCallback(
    async (id: string) => {
      await activateWorkspace(id);
      await refresh();
    },
    [refresh],
  );

  return {
    workspaces,
    active,
    loading,
    refresh,
    create,
    activate,
  };
}
