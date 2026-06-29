import { apiFetch } from './client';
import type { LoginRequest, LoginResponse } from './types';

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password } satisfies LoginRequest),
  });
}

export function getToken(): string | null {
  return sessionStorage.getItem('metronix_token');
}

export function setToken(token: string): void {
  sessionStorage.setItem('metronix_token', token);
}

export function clearToken(): void {
  sessionStorage.removeItem('metronix_token');
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
