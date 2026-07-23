import { Database, Brain, Activity, KeyRound, X, LogOut } from 'lucide-react';
import { NavLink } from 'react-router-dom';
import { WorkspaceSelector, StatusDot, useHealth, clearToken, useAuthStore } from '@/shared';

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

const NAV_ITEMS = [
  { to: '/sources', label: 'Sources', icon: Database },
  { to: '/memory', label: 'Memory Inspector', icon: Brain },
  { to: '/health', label: 'Health & Stats', icon: Activity },
  { to: '/access-keys', label: 'Access Keys', icon: KeyRound },
];

export default function Sidebar({ open, onClose }: SidebarProps) {
  const { health } = useHealth();
  const allOk =
    health != null &&
    Object.values(health.services).every((s) => s === 'ok');

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-64 flex-col border-r border-border bg-surface transition-transform lg:static lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-accent text-sm font-bold text-white">
            M
          </div>
          <span className="text-lg font-semibold text-text">Metronix Admin</span>
          <button
            onClick={onClose}
            className="ml-auto lg:hidden text-text-muted hover:text-text"
          >
            <X size={18} />
          </button>
        </div>

        {/* Workspace selector */}
        <div className="border-b border-border p-3">
          <WorkspaceSelector />
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={onClose}
              className={({ isActive }) =>
                `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-primary-muted text-primary-hover'
                    : 'text-text-muted hover:bg-surface-hover hover:text-text'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* Status footer */}
        <div className="border-t border-border p-4">
          <div className="flex items-center gap-2 text-xs text-text-muted">
            <StatusDot ok={allOk} />
            <span>
              {health == null
                ? 'Connecting...'
                : allOk
                  ? 'All services online'
                  : 'Some services degraded'}
            </span>
          </div>
        </div>

        {/* Logout */}
        <div className="border-t border-border p-3">
          <button
            onClick={() => {
              useAuthStore.getState().clearAuth();
              clearToken();
              window.location.reload();
            }}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-xs text-text-muted hover:bg-surface-hover hover:text-text transition-colors"
          >
            <LogOut size={14} />
            Logout
          </button>
        </div>
      </aside>
    </>
  );
}
