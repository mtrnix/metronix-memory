import { Bot } from 'lucide-react';

export default function AgentsPage() {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-accent/10">
          <Bot size={32} className="text-accent" />
        </div>
        <h2 className="mb-2 text-xl font-semibold text-text">Agents Overview</h2>
        <p className="max-w-md text-sm text-text-muted">
          View and manage connected AI agents. Coming soon.
        </p>
      </div>
    </div>
  );
}
