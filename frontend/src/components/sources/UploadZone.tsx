import { useCallback, useState, type DragEvent } from 'react';
import { Upload, FileText } from 'lucide-react';

interface UploadZoneProps {
  onUpload: (file: File) => void;
  uploading: boolean;
}

export default function UploadZone({ onUpload, uploading }: UploadZoneProps) {
  const [dragOver, setDragOver] = useState(false);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) onUpload(file);
    },
    [onUpload],
  );

  const handleClick = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.onchange = () => {
      const file = input.files?.[0];
      if (file) onUpload(file);
    };
    input.click();
  }, [onUpload]);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={handleClick}
      className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
        dragOver
          ? 'border-primary bg-primary-muted'
          : 'border-border hover:border-border-light'
      }`}
    >
      <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-surface-hover">
        {uploading ? (
          <FileText size={24} className="text-primary animate-pulse" />
        ) : (
          <Upload size={24} className="text-text-muted" />
        )}
      </div>

      <p className="text-sm font-medium text-text">
        {uploading ? 'Uploading...' : 'Drop files here or click to upload'}
      </p>
      <p className="mt-1 text-xs text-text-muted">
        PDF, TXT, MD, DOCX, CSV, JSON
      </p>
    </div>
  );
}
