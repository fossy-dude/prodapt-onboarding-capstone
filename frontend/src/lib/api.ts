import axios, { AxiosError, type AxiosInstance } from 'axios';

import type { RegisterPayload, RegisterResponseEnvelope } from '../types/subscriber';
import { getToken, removeToken } from './auth';

// Base URL for the service_webapp REST API. Vite exposes VITE_-prefixed env vars.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10_000,
});

// ── Auth interceptors (Story 1.8, AC #4) ─────────────────────────────────────

/** Attach `Authorization: Bearer {token}` to every outgoing request. */
apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token !== null) {
    config.headers['Authorization'] = `Bearer ${token}`;
  }
  return config;
});

/** On 401 response: clear the stored token and redirect to /login. */
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (error instanceof AxiosError && error.response?.status === 401) {
      removeToken();
      window.location.href = '/login';
    }
    return Promise.reject(error);
  },
);

// ─────────────────────────────────────────────────────────────────────────────

/** Error codes the API returns in the standard error envelope (§1.11.3). */
export const ERROR_CODES = {
  DUPLICATE_MSISDN: 'DUPLICATE_MSISDN',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  UNAUTHENTICATED: 'UNAUTHENTICATED',
  FORBIDDEN: 'FORBIDDEN',
  OTP_INVALID: 'OTP_INVALID',
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

// ── Registration (Story 1.6) ──────────────────────────────────────────────────

/** POST /subscriber/register — create a subscriber registration (Story 1.6). */
export async function registerSubscriber(payload: RegisterPayload): Promise<RegisterResponseEnvelope> {
  const { data } = await apiClient.post<RegisterResponseEnvelope>('/subscriber/register', payload);
  return data;
}

// ── Auth / Login (Story 1.8) ─────────────────────────────────────────────────

interface LoginInitiateResponse {
  readonly data: { readonly session: string };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

interface LoginVerifyResponse {
  readonly data: {
    readonly access_token: string;
    readonly refresh_token: string;
    readonly id_token: string;
    readonly token_type: string;
  };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/**
 * POST /auth/login/initiate — start Cognito Custom Auth Flow (AC #1, #2).
 * Returns `{ session }` to pass to `verifyLoginOtp`.
 */
export async function initiateLogin(identifier: string): Promise<{ session: string }> {
  const { data } = await apiClient.post<LoginInitiateResponse>('/auth/login/initiate', { identifier });
  return data.data;
}

/**
 * POST /auth/login/verify — respond to OTP challenge and receive JWT tokens (AC #1, #2).
 */
export async function verifyLoginOtp(
  identifier: string,
  session: string,
  otp: string,
): Promise<LoginVerifyResponse['data']> {
  const { data } = await apiClient.post<LoginVerifyResponse>('/auth/login/verify', {
    identifier,
    session,
    otp,
  });
  return data.data;
}

export { apiClient };
