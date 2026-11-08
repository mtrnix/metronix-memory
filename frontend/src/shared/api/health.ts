import { apiFetch } from './client';
import { ApiError } from './errors';
import type { HealthResponse, MetricsResponse } from './types';

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health');
}

// /ready answers 503 with the same body when a service is degraded; surface
// that body so the UI can still show which service is down.
export async function getReady(): Promise<HealthResponse> {
  try {
    return await apiFetch<HealthResponse>('/ready');
  } catch (err) {
    if (err instanceof ApiError && err.status === 503 && isHealthResponse(err.body)) {
      return err.body;
    }
    throw err;
  }
}

function isHealthResponse(body: unknown): body is HealthResponse {
  return typeof body === 'object' && body !== null && 'services' in body && 'status' in body;
}

export function getMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>('/metrics');
}
