import { create } from 'zustand';
import type { WorkspaceResponse } from '../api/types';

interface WorkspaceState {
  workspaces: WorkspaceResponse[];
  active: WorkspaceResponse | null;
  loading: boolean;
  setWorkspaces: (workspaces: WorkspaceResponse[]) => void;
  setActive: (workspace: WorkspaceResponse | null) => void;
  setLoading: (loading: boolean) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  workspaces: [],
  active: null,
  loading: true,
  setWorkspaces: (workspaces) => set({ workspaces }),
  setActive: (active) => set({ active }),
  setLoading: (loading) => set({ loading }),
}));
