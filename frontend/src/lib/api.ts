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

/** Routes that must NOT trigger a /login redirect on 401 (they are part of the login flow). */
const _LOGIN_PATHS = ['/auth/login/initiate', '/auth/login/verify'];

/** On 401 response: clear the stored token and redirect to /login.
 *
 * P7: skip the redirect when the 401 comes from a login endpoint itself —
 * otherwise a wrong OTP causes a redirect loop while the user is already on /login.
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (error instanceof AxiosError && error.response?.status === 401) {
      const url = error.config?.url ?? '';
      const isLoginRoute = _LOGIN_PATHS.some((path) => url.includes(path));
      if (!isLoginRoute) {
        removeToken();
        // P8: window.location.href is a full reload that bypasses React Router.
        // Acceptable for the auth redirect (avoids needing a shared event bus),
        // but guarded to login-route exclusion above to prevent loops.
        window.location.href = '/login';
      }
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

// ── SIM Activation Order Status (Story 1.7) ──────────────────────────────────

export interface OrderStatusResponse {
  readonly data: {
    readonly status: 'CREATED' | 'KYC_PENDING' | 'KYC_VERIFIED' | 'ACTIVATED';
    readonly updated_at: string;
    readonly msisdn: string | null;
  };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

export interface ActiveOrderResponse {
  readonly data: {
    // order_id/status/updated_at are null when the subscriber has no active order (D7).
    readonly order_id: string | null;
    readonly status: string | null;
    readonly updated_at: string | null;
  };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /subscriber/orders/active — discover the subscriber's active NEW_ACTIVATION order. */
export async function getActiveOrder(): Promise<ActiveOrderResponse['data']> {
  const { data } = await apiClient.get<ActiveOrderResponse>('/subscriber/orders/active');
  return data.data;
}

/** GET /subscriber/orders/{orderId}/status — poll fulfilment state. */
export async function getOrderStatus(orderId: string): Promise<OrderStatusResponse['data']> {
  const { data } = await apiClient.get<OrderStatusResponse>(`/subscriber/orders/${orderId}/status`);
  return data.data;
}

// ── Simulator developer tool (Story 1.7) ─────────────────────────────────────

export interface SimulatorOrder {
  readonly order_id: string;
  readonly current_status: string;
  readonly created_at: string | null;
}

export interface SimulatorOrdersResponse {
  readonly data: { readonly orders: readonly SimulatorOrder[] };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /simulator/orders — list recent orders for the dev tool (dev role). */
export async function getSimulatorOrders(): Promise<SimulatorOrdersResponse['data']> {
  const { data } = await apiClient.get<SimulatorOrdersResponse>('/simulator/orders');
  return data.data;
}

export interface AdvanceOrderResponse {
  readonly data: {
    readonly order_id: string;
    readonly previous_status: string;
    readonly status: string;
  };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** POST /simulator/orders/{orderId}/advance — advance the order state (dev tool). */
export async function advanceOrderState(orderId: string): Promise<AdvanceOrderResponse['data']> {
  const { data } = await apiClient.post<AdvanceOrderResponse>(
    `/simulator/orders/${orderId}/advance`,
  );
  return data.data;
}

export { apiClient };
