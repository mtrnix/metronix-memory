import { Menu } from 'lucide-react';

interface HeaderProps {
  title: string;
  onMenuClick: () => void;
}

export default function Header({ title, onMenuClick }: HeaderProps) {
  return (
    <header className="flex h-14 items-center gap-3 border-b border-border bg-surface px-4">
      <button
        onClick={onMenuClick}
        className="lg:hidden text-text-muted hover:text-text"
      >
        <Menu size={20} />
      </button>

      <h1 className="text-lg font-semibold text-text">{title}</h1>
    </header>
  );
}
