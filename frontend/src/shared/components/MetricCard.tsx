// Reusable metric card component for KPI displays

interface MetricCardProps {
  label: string;
  value: string | number;
  trend?: {
    value: number;
    isPositive: boolean;
  };
  icon?: React.ReactNode;
  className?: string;
}

export default function MetricCard({ label, value, trend, icon, className = '' }: MetricCardProps) {
  return (
    <div className={`rounded-lg border border-border bg-surface p-6 ${className}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="text-sm font-medium text-text-muted">{label}</h3>
          <p className="mt-2 text-3xl font-bold text-text">{value}</p>
          
          {trend && (
            <div className={`mt-2 flex items-center gap-1 text-sm ${
              trend.isPositive ? 'text-success' : 'text-error'
            }`}>
              <span>{trend.isPositive ? '↑' : '↓'}</span>
              <span>{Math.abs(trend.value).toFixed(1)}%</span>
            </div>
          )}
        </div>
        
        {icon && (
          <div className="text-text-muted">
            {icon}
          </div>
        )}
      </div>
    </div>
  );
}
