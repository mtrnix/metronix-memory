import { apiFetch } from './client';
import type { HealthResponse, MetricsResponse } from './types';

export function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health');
}

export function getReady(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/ready');
}

export function getMetrics(): Promise<MetricsResponse> {
  return apiFetch<MetricsResponse>('/metrics');
}
