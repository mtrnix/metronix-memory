// Error message component

interface ErrorMessageProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export default function ErrorMessage({ message, onRetry, className = '' }: ErrorMessageProps) {
  return (
    <div className={`rounded-lg border border-error/20 bg-error/10 p-4 ${className}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <p className="text-sm font-medium text-error">Error</p>
          <p className="mt-1 text-sm text-text-muted">{message}</p>
        </div>
        
        {onRetry && (
          <button
            onClick={onRetry}
            className="text-sm font-medium text-error hover:text-error/80 transition-colors"
          >
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
