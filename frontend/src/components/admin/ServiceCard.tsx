import { StatusDot } from '@/shared';

interface ServiceCardProps {
  name: string;
  status: 'ok' | 'error' | undefined;
  icon: string;
}

export default function ServiceCard({ name, status, icon }: ServiceCardProps) {
  const isOk = status === 'ok';
  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="flex items-center gap-3">
        <span className="text-2xl">{icon}</span>
        <div className="flex-1">
          <h3 className="text-sm font-semibold text-text">{name}</h3>
          <div className="flex items-center gap-1.5 mt-1">
            <StatusDot ok={isOk} />
            <span className="text-xs text-text-muted">
              {status == null ? 'Unknown' : isOk ? 'Healthy' : 'Error'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
