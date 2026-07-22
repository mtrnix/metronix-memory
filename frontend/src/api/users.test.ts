import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/shared', () => ({
  apiFetch: vi.fn(),
}));

import { apiFetch } from '@/shared';
import {
  createApiKey,
  listAllUsers,
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

  it('passes user pagination parameters to the API', async () => {
    vi.mocked(apiFetch).mockResolvedValue({ users: [], total: 201 });

    await expect(listUsers({ limit: 200, offset: 200 })).resolves.toEqual({
      users: [],
      total: 201,
    });
    expect(apiFetch).toHaveBeenCalledWith('/api/v1/users?limit=200&offset=200');
  });

  it('loads every user page with the API maximum page size', async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => ({ id: `u${index + 1}` }));
    vi.mocked(apiFetch)
      .mockResolvedValueOnce({
        users: firstPage,
        total: 201,
      })
      .mockResolvedValueOnce({
        users: [{ id: 'u201' }],
        total: 201,
      });

    await expect(listAllUsers()).resolves.toEqual([...firstPage, { id: 'u201' }]);
    expect(apiFetch).toHaveBeenNthCalledWith(1, '/api/v1/users?limit=200&offset=0');
    expect(apiFetch).toHaveBeenNthCalledWith(2, '/api/v1/users?limit=200&offset=200');
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
