import { useEffect, useRef, useState } from 'react';
import { login, setToken } from '../api/auth';
import { useAuthStore } from '../stores/auth';

interface LoginPageProps {
  onSuccess: () => void;
}

export default function LoginPage({ onSuccess }: LoginPageProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password.trim() || loading) return;

    setLoading(true);
    setError('');

    try {
      const res = await login(email, password);
      setToken(res.token);
      useAuthStore.getState().setAuth(res.user_id, res.role, res.email, res.display_name);
      onSuccess();
    } catch {
      setError('Invalid email or password');
      setPassword('');
      inputRef.current?.focus();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full items-center justify-center bg-bg p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-2xl border border-border bg-surface p-8"
      >
        <div className="mb-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-accent text-lg font-bold text-white">
            M
          </div>
          <h1 className="text-xl font-semibold text-text">Metronix</h1>
          <p className="mt-1 text-sm text-text-muted">Knowledge Fabric</p>
        </div>

        <div className="space-y-4">
          <div>
            <input
              ref={inputRef}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Email"
              className="w-full rounded-xl border border-border bg-bg px-4 py-3 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
            />
          </div>
          <div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              className="w-full rounded-xl border border-border bg-bg px-4 py-3 text-sm text-text placeholder:text-text-dim focus:border-primary focus:outline-none"
            />
            {error && (
              <p className="mt-2 text-xs text-error">{error}</p>
            )}
          </div>

          <button
            type="submit"
            disabled={loading || !password.trim() || !email.trim()}
            className="w-full rounded-xl bg-primary py-3 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50 transition-colors"
          >
            {loading ? 'Signing in...' : 'Sign in'}
          </button>
        </div>
      </form>
    </div>
  );
}
