interface StatusDotProps {
  ok: boolean;
  size?: 'sm' | 'md';
}

export default function StatusDot({ ok, size = 'sm' }: StatusDotProps) {
  const px = size === 'sm' ? 'h-2 w-2' : 'h-3 w-3';
  return (
    <span
      className={`inline-block rounded-full ${px} ${ok ? 'bg-success' : 'bg-error'}`}
    />
  );
}
