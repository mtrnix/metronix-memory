import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/shared', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/shared';
import {
  createApiKey,
  listApiKeys,
  listUsers,
  revokeApiKey,
} from './users';

describe('user admin API', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it('lists users with the backend response shape', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ users: [], total: 0 });

    await expect(listUsers()).resolves.toEqual({ users: [], total: 0 });
    expect(apiFetch).toHaveBeenCalledWith('/api/v1/users');
  });

  it('lists keys using an encoded user ID', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ keys: [], user_id: 'user/id' });

    await expect(listApiKeys('user/id')).resolves.toMatchObject({ keys: [] });
    expect(apiFetch).toHaveBeenCalledWith('/api/v1/users/user%2Fid/api-keys');
  });

  it('creates a labelled key and returns its one-time raw value', async () => {
    vi.mocked(apiFetch).mockResolvedValue({
      raw_key: 'mtk_once',
      user_id: 'u1',
      label: 'hermes',
    });

    await expect(createApiKey('u1', 'hermes')).resolves.toMatchObject({
      raw_key: 'mtk_once',
    });
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/v1/users/u1/api-keys',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ label: 'hermes' }),
      }),
    );
  });

  it('revokes an encoded key prefix for the user', async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined);

    await expect(revokeApiKey('user/id', 'mtk/a')).resolves.toBeUndefined();
    expect(apiFetch).toHaveBeenCalledWith(
      '/api/v1/users/user%2Fid/api-keys/mtk%2Fa',
      { method: 'DELETE' },
    );
  });
});
