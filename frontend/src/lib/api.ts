import axios, { AxiosError, type AxiosInstance } from 'axios';

import type { RegisterPayload, RegisterResponseEnvelope } from '../types/subscriber';

// Base URL for the service_webapp REST API. Vite exposes VITE_-prefixed env vars.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10_000,
});

/** Error codes the API returns in the standard error envelope (§1.11.3). */
export const ERROR_CODES = {
  DUPLICATE_MSISDN: 'DUPLICATE_MSISDN',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
} as const;

export interface ApiError {
  readonly code: string;
  readonly message: string;
  readonly detail: Record<string, unknown>;
}

/** Extract the standard error envelope from an axios error, if present. */
export function toApiError(error: unknown): ApiError | null {
  if (!(error instanceof AxiosError) || error.response === undefined) {
    return null;
  }
  const body = error.response.data as { error?: ApiError } | undefined;
  return body?.error ?? null;
}

/** POST /subscriber/register — create a subscriber registration (Story 1.6). */
export async function registerSubscriber(payload: RegisterPayload): Promise<RegisterResponseEnvelope> {
  const { data } = await apiClient.post<RegisterResponseEnvelope>('/subscriber/register', payload);
  return data;
}

export { apiClient };
