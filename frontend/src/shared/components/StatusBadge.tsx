// Status badge component with color variants

type BadgeVariant = 'success' | 'warning' | 'error' | 'info';

interface StatusBadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

const VARIANT_STYLES: Record<BadgeVariant, string> = {
  success: 'bg-success/10 text-success border-success/20',
  warning: 'bg-warning/10 text-warning border-warning/20',
  error: 'bg-error/10 text-error border-error/20',
  info: 'bg-primary/10 text-primary border-primary/20',
};

export default function StatusBadge({ variant, children, className = '' }: StatusBadgeProps) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${VARIANT_STYLES[variant]} ${className}`}>
      {children}
    </span>
  );
}
