import { Brain } from 'lucide-react';

export default function MemoryBrowserPage() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
          <Brain size={32} className="text-primary" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-text">Memory Browser</h2>
        <p className="max-w-md text-sm text-text-muted">
          Browse and inspect stored knowledge memories. This feature will be available in Phase 2 when the Memory API lands.
        </p>
      </div>
    </div>
  );
}
