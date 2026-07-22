import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { StrictMode } from 'react';
import AccessKeysPage from './AccessKeysPage';
import {
  createApiKey,
  listApiKeys,
  listUsers,
  revokeApiKey,
} from '@/api/users';
import { ApiError } from '@/shared/api/errors';

vi.mock('@/api/users', () => ({
  createApiKey: vi.fn(),
  listApiKeys: vi.fn(),
  listUsers: vi.fn(),
  revokeApiKey: vi.fn(),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <AccessKeysPage />
      </QueryClientProvider>
    </StrictMode>,
  );
}

describe('AccessKeysPage', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    vi.mocked(listUsers).mockResolvedValue({
      users: [
        {
          id: 'u1',
          email: 'admin@example.com',
          display_name: 'Admin',
          role: 'admin',
          is_active: true,
          created_at: '2026-07-22T09:00:00Z',
          workspace_ids: [],
        },
        {
          id: 'u2',
          email: 'operator@example.com',
          display_name: 'Operator',
          role: 'user',
          is_active: true,
          created_at: '2026-07-22T09:00:00Z',
          workspace_ids: [],
        },
      ],
      total: 2,
    });
    vi.mocked(listApiKeys).mockImplementation(async (userId) => ({
      user_id: userId,
      keys: userId === 'u1'
        ? [
            {
              id: 'key-1',
              key_prefix: 'mtk_abcd',
              label: 'existing',
              created_at: '2026-07-22T09:00:00Z',
            },
          ]
        : [],
    }));
    vi.mocked(createApiKey).mockResolvedValue({
      raw_key: 'mtk_once',
      user_id: 'u1',
      label: 'hermes-native-production',
    });
    vi.mocked(revokeApiKey).mockResolvedValue(undefined);
  });

  it('loads prefix-only rows for the selected user', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('mtk_abcd')).toBeInTheDocument();
    expect(screen.queryByText('mtk_once')).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('User'), 'u2');

    await waitFor(() => {
      expect(listApiKeys).toHaveBeenLastCalledWith('u2');
    });
    expect(screen.getByText('No access keys for this user.')).toBeInTheDocument();
  });

  it('shows a newly created secret only until the success dialog closes', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('mtk_abcd')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create key' }));
    await user.type(screen.getByLabelText('Label'), 'hermes-native-production');
    await user.click(screen.getByRole('button', { name: 'Create' }));

    expect(await screen.findByText('mtk_once')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Close' }));

    expect(screen.queryByText('mtk_once')).not.toBeInTheDocument();
  });

  it('revokes a key after confirmation and refreshes the key list', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('mtk_abcd')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Revoke mtk_abcd' }));
    await user.click(screen.getByRole('button', { name: 'Revoke' }));

    await waitFor(() => {
      expect(revokeApiKey).toHaveBeenCalledWith('u1', 'mtk_abcd');
      expect(listApiKeys).toHaveBeenCalledTimes(2);
    });
  });

  it('shows the API error when revoking a key fails', async () => {
    vi.mocked(revokeApiKey).mockRejectedValue(
      new ApiError(500, {}, 'Unable to revoke access key.'),
    );
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText('mtk_abcd')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Revoke mtk_abcd' }));
    await user.click(screen.getByRole('button', { name: 'Revoke' }));

    expect(await screen.findByText(/Unable to revoke access key\./)).toBeInTheDocument();
  });
});
