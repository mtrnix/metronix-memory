// Formatting utilities for dashboard widgets

// Format number with thousand separators (12483 → "12,483")
export function formatNumber(num: number): string {
  return new Intl.NumberFormat('en-US').format(num);
}

// Format relative time ("2h ago", "3 days ago")
export function formatRelativeTime(date: string | Date): string {
  const now = new Date();
  const target = typeof date === 'string' ? new Date(date) : date;
  const diffMs = now.getTime() - target.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

  if (diffDay > 0) return rtf.format(-diffDay, 'day');
  if (diffHour > 0) return rtf.format(-diffHour, 'hour');
  if (diffMin > 0) return rtf.format(-diffMin, 'minute');
  return rtf.format(-diffSec, 'second');
}

// Format duration from milliseconds ("1.2s", "3m 12s")
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}

// Format percentage (0.982 → "98.2%")
export function formatPercentage(num: number, decimals = 1): string {
  return `${(num * 100).toFixed(decimals)}%`;
}

// Format USD currency ($0.04, $1.23, $10.53)
export function formatCurrency(amount: number): string {
  if (amount < 0.01 && amount > 0) return '<$0.01';
  return `$${amount.toFixed(2)}`;
}
