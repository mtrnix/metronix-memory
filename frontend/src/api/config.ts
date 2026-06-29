import { apiFetch } from '@/shared';

interface AppConfig {
  plugins: string[];
}

export async function getConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>('/api/v1/config');
}
