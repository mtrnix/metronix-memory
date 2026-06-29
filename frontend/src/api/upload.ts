import type { UploadResponse } from './types';
import { getToken } from '@/shared';

export async function uploadFile(
  file: File,
  workspaceId?: string,
): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  if (workspaceId) {
    form.append('workspace_id', workspaceId);
  }

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch('/api/v1/upload', {
    method: 'POST',
    headers,
    body: form,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(
      (body as { detail?: string }).detail || `HTTP ${res.status}`,
    );
  }

  return res.json() as Promise<UploadResponse>;
}
