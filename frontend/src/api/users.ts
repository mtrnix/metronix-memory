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

export interface UserListOptions {
  limit?: number;
  offset?: number;
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

export function listUsers(options: UserListOptions = {}): Promise<UserListResponse> {
  const { limit, offset } = options;
  if (limit === undefined && offset === undefined) {
    return apiFetch<UserListResponse>('/api/v1/users');
  }

  const params = new URLSearchParams();
  if (limit !== undefined) params.set('limit', String(limit));
  if (offset !== undefined) params.set('offset', String(offset));
  return apiFetch<UserListResponse>(`/api/v1/users?${params}`);
}

const USER_PAGE_SIZE = 200;

export async function listAllUsers(): Promise<AdminUser[]> {
  const users: AdminUser[] = [];

  for (let offset = 0; ; offset += USER_PAGE_SIZE) {
    const page = await listUsers({ limit: USER_PAGE_SIZE, offset });
    users.push(...page.users);

    if (users.length >= page.total || page.users.length === 0) {
      return users;
    }
  }
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
