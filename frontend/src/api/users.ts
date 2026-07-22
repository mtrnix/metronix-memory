import { apiFetch } from '@/shared';

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
  workspace_ids: string[];
}

export interface UserListResponse {
  users: AdminUser[];
  total: number;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  label: string;
  created_at: string;
}

export interface ApiKeyListResponse {
  keys: ApiKey[];
  user_id: string;
}

export interface CreateApiKeyResponse {
  raw_key: string;
  user_id: string;
  label: string;
}

export function listUsers(): Promise<UserListResponse> {
  return apiFetch<UserListResponse>('/api/v1/users');
}

export function listApiKeys(userId: string): Promise<ApiKeyListResponse> {
  return apiFetch<ApiKeyListResponse>(
    `/api/v1/users/${encodeURIComponent(userId)}/api-keys`,
  );
}

export function createApiKey(
  userId: string,
  label: string,
): Promise<CreateApiKeyResponse> {
  return apiFetch<CreateApiKeyResponse>(
    `/api/v1/users/${encodeURIComponent(userId)}/api-keys`,
    {
      method: 'POST',
      body: JSON.stringify({ label }),
    },
  );
}

export function revokeApiKey(userId: string, keyPrefix: string): Promise<void> {
  return apiFetch<void>(
    `/api/v1/users/${encodeURIComponent(userId)}/api-keys/${encodeURIComponent(keyPrefix)}`,
    { method: 'DELETE' },
  );
}
