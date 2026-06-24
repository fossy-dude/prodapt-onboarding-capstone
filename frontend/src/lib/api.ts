import axios, { AxiosError, type AxiosInstance } from "axios";

import type {
  RegisterPayload,
  RegisterResponseEnvelope,
} from "../types/subscriber";
import type {
  PaymentMethodsListResponse,
  PaymentMethodResponse,
  AddPaymentMethodPayload,
} from "../types/payment-method";
import { getToken, removeToken } from "./auth";

// Base URL for the service_webapp REST API. Vite exposes VITE_-prefixed env vars.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 10_000,
});

// ── Auth interceptors (Story 1.8, AC #4) ─────────────────────────────────────

/** Attach `Authorization: Bearer {token}` to every outgoing request. */
apiClient.interceptors.request.use((config) => {
  const token = getToken();
  if (token !== null) {
    config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

/** Routes that must NOT trigger a /login redirect on 401 (they are part of the login flow). */
const _LOGIN_PATHS = ["/auth/login/initiate", "/auth/login/verify"];

/** On 401 response: clear the stored token and redirect to /login.
 *
 * P7: skip the redirect when the 401 comes from a login endpoint itself —
 * otherwise a wrong OTP causes a redirect loop while the user is already on /login.
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (error instanceof AxiosError && error.response?.status === 401) {
      const url = error.config?.url ?? "";
      const isLoginRoute = _LOGIN_PATHS.some((path) => url.includes(path));
      if (!isLoginRoute) {
        removeToken();
        // P8: window.location.href is a full reload that bypasses React Router.
        // Acceptable for the auth redirect (avoids needing a shared event bus),
        // but guarded to login-route exclusion above to prevent loops.
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

// ─────────────────────────────────────────────────────────────────────────────

/** Error codes the API returns in the standard error envelope (§1.11.3). */
export const ERROR_CODES = {
  DUPLICATE_MSISDN: "DUPLICATE_MSISDN",
  VALIDATION_ERROR: "VALIDATION_ERROR",
  UNAUTHENTICATED: "UNAUTHENTICATED",
  FORBIDDEN: "FORBIDDEN",
  OTP_INVALID: "OTP_INVALID",
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
export async function registerSubscriber(
  payload: RegisterPayload,
): Promise<RegisterResponseEnvelope> {
  const { data } = await apiClient.post<RegisterResponseEnvelope>(
    "/subscriber/register",
    payload,
  );
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
export async function initiateLogin(
  identifier: string,
): Promise<{ session: string }> {
  const { data } = await apiClient.post<LoginInitiateResponse>(
    "/auth/login/initiate",
    { identifier },
  );
  return data.data;
}

/**
 * POST /auth/login/verify — respond to OTP challenge and receive JWT tokens (AC #1, #2).
 */
export async function verifyLoginOtp(
  identifier: string,
  session: string,
  otp: string,
): Promise<LoginVerifyResponse["data"]> {
  const { data } = await apiClient.post<LoginVerifyResponse>(
    "/auth/login/verify",
    {
      identifier,
      session,
      otp,
    },
  );
  return data.data;
}

// ── SIM Activation Order Status (Story 1.7) ──────────────────────────────────

export interface OrderStatusResponse {
  readonly data: {
    readonly status: "CREATED" | "KYC_PENDING" | "KYC_VERIFIED" | "ACTIVATED";
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
export async function getActiveOrder(): Promise<ActiveOrderResponse["data"]> {
  const { data } = await apiClient.get<ActiveOrderResponse>(
    "/subscriber/orders/active",
  );
  return data.data;
}

/** GET /subscriber/orders/{orderId}/status — poll fulfilment state. */
export async function getOrderStatus(
  orderId: string,
): Promise<OrderStatusResponse["data"]> {
  const { data } = await apiClient.get<OrderStatusResponse>(
    `/subscriber/orders/${orderId}/status`,
  );
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
export async function getSimulatorOrders(): Promise<
  SimulatorOrdersResponse["data"]
> {
  const { data } =
    await apiClient.get<SimulatorOrdersResponse>("/simulator/orders");
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
export async function advanceOrderState(
  orderId: string,
): Promise<AdvanceOrderResponse["data"]> {
  const { data } = await apiClient.post<AdvanceOrderResponse>(
    `/simulator/orders/${orderId}/advance`,
  );
  return data.data;
}

// ── Profile (Story 1.9) ───────────────────────────────────────────────────────

/** Saved address on the subscriber profile (fields are null until first edited). */
export interface ProfileAddress {
  readonly line1: string | null;
  readonly line2: string | null;
  readonly city: string | null;
  readonly state: string | null;
  readonly pin_code: string | null;
}

/** Decrypted profile returned to the authenticated owner. */
export interface ProfileData {
  readonly name: string;
  readonly email: string | null;
  readonly address: ProfileAddress;
  readonly kyc_status: string; // 'verified' | 'pending' | 'rejected' (lowercased by the API)
}

/** Editable profile fields (PATCH body; name is read-only). At least one required. */
export interface ProfileUpdatePayload {
  readonly email?: string;
  readonly address_line1?: string;
  readonly address_line2?: string;
  readonly city?: string;
  readonly state?: string;
  readonly pin_code?: string;
}

interface ProfileResponse {
  readonly data: ProfileData;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /subscriber/profile — read the authenticated subscriber's decrypted profile. */
export async function getProfile(): Promise<ProfileData> {
  const { data } = await apiClient.get<ProfileResponse>("/subscriber/profile");
  return data.data;
}

/** PATCH /subscriber/profile — edit email/address (re-writes + audit on the server). */
export async function updateProfile(
  payload: ProfileUpdatePayload,
): Promise<ProfileData> {
  const { data } = await apiClient.patch<ProfileResponse>(
    "/subscriber/profile",
    payload,
  );
  return data.data;
}

// ── Payment Methods (Story 1.10) ───────────────────────────────────────────────

/** GET /account/payment-methods — list subscriber's saved payment methods (AC #5). */
export async function getPaymentMethods(): Promise<PaymentMethodsListResponse> {
  const { data } = await apiClient.get<PaymentMethodsListResponse>(
    "/account/payment-methods",
  );
  return data;
}

/** POST /account/payment-methods — add a new payment method (AC #1, #3). */
export async function addPaymentMethod(
  payload: AddPaymentMethodPayload,
): Promise<PaymentMethodResponse> {
  const { data } = await apiClient.post<PaymentMethodResponse>(
    "/account/payment-methods",
    payload,
  );
  return data;
}

/**
 * PATCH /account/payment-methods/{id}/default — set a payment method as default (AC #5).
 * Clears the default flag on all other methods for this subscriber.
 */
export async function setDefaultPaymentMethod(
  id: string,
): Promise<PaymentMethodResponse> {
  const { data } = await apiClient.patch<PaymentMethodResponse>(
    `/account/payment-methods/${id}/default`,
  );
  return data;
}

/**
 * DELETE /account/payment-methods/{id} — remove a saved payment method.
 */
export async function deletePaymentMethod(id: string): Promise<void> {
  await apiClient.delete(`/account/payment-methods/${id}`);
}

// ── Balance & Usage (Story 3.2) ───────────────────────────────────────────────

export interface WalletBalanceData {
  readonly subscriber_id: string;
  readonly msisdn_masked: string;
  readonly balance_paise: number;
  readonly balance_inr: string;
  readonly last_updated_at: string | null;
}

interface WalletBalanceResponse {
  readonly data: WalletBalanceData;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

export interface UsageAllowance {
  readonly used: number;
  readonly allowance: number | null;
  readonly unlimited: boolean;
}

export interface UsageData {
  readonly subscriber_id: string;
  readonly plan_period: { readonly start: string; readonly end: string | null };
  readonly voice_minutes: UsageAllowance;
  readonly data_mb: number;
  readonly data_gb: number;
  readonly data: UsageAllowance;
  readonly sms: UsageAllowance;
  readonly roaming_mb: UsageAllowance;
}

interface UsageResponse {
  readonly data: UsageData;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /subscriber/balance — current wallet balance (Valkey-authoritative). */
export async function getBalance(): Promise<WalletBalanceData> {
  const { data } = await apiClient.get<WalletBalanceResponse>(
    "/subscriber/balance",
  );
  return data.data;
}

/** GET /subscriber/usage — per-type CDR usage vs plan allowances. */
export async function getUsage(): Promise<UsageData> {
  const { data } = await apiClient.get<UsageResponse>("/subscriber/usage");
  return data.data;
}

// ── CDR Simulator (Story 2.8) ──────────────────────────────────────────────────

export interface CdrDispatchPayload {
  readonly cdr_type: "voice" | "data" | "sms";
  readonly subscriber_msisdn: string;
  readonly duration_seconds?: number;
  readonly volume_mb?: number;
  readonly message_direction?: "MO" | "MT";
  readonly timestamp?: string;
}

interface CdrDispatchResponse {
  readonly data: {
    readonly trace_id: string;
    readonly cdr_type: string;
    readonly subscriber_msisdn: string;
  };
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** POST /simulator/cdr — dispatch a synthetic CDR event (Story 2.8, AC #1). */
export async function dispatchCdr(
  payload: CdrDispatchPayload,
): Promise<{ trace_id: string; cdr_type: string; subscriber_msisdn: string }> {
  const { data } = await apiClient.post<CdrDispatchResponse>(
    "/simulator/cdr",
    payload,
  );
  return data.data;
}

// ── SIM Activation Simulator (Story 2.9) ────────────────────────────────────────

export type SimLookupType = "msisdn" | "registration_id";

export interface SimActivatePayload {
  readonly lookup_type: SimLookupType;
  readonly lookup_value: string;
}

export interface SimActivateResult {
  readonly order_id: string;
  readonly status: string;
  readonly msisdn: string;
  readonly balance_paise: number;
}

interface SimActivateResponse {
  readonly data: SimActivateResult;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/**
 * POST /simulator/activate — drive a subscriber's NEW_ACTIVATION order to ACTIVATED
 * (resolves by MSISDN or Registration ID), seed the wallet + Valkey balance, and
 * publish a notification event (Story 2.9, AC #1, #2).
 */
export async function activateSim(
  payload: SimActivatePayload,
): Promise<SimActivateResult> {
  const { data } = await apiClient.post<SimActivateResponse>(
    "/simulator/activate",
    payload,
  );
  return data.data;
}

// ── Transactions ledger (Story 3.3) ────────────────────────────────────────────

/** One row of the subscriber transaction ledger (CHARGE | RECHARGE | REFUND).
 * `transaction_type` is the raw stored writer value (e.g. `cdr_deduction`);
 * `cdr_reference` is non-null only for CDR-linked charge rows. */
export interface TransactionItem {
  readonly id: string;
  readonly transaction_type: string;
  readonly amount_paise: number;
  readonly balance_after_paise: number;
  readonly cdr_reference: string | null;
  readonly description: string | null;
  readonly created_at: string;
}

interface TransactionsResponse {
  readonly data: readonly TransactionItem[];
  readonly meta: {
    readonly trace_id: string;
    readonly timestamp: string;
    readonly next_cursor: string | null;
  };
}

/** One page of the cursor-paginated ledger. */
export interface TransactionsPage {
  readonly items: readonly TransactionItem[];
  readonly nextCursor: string | null;
}

/** Cursor-pagination query params for the transactions endpoint. */
export interface TransactionsQuery {
  readonly cursor?: string;
  readonly page_size?: number;
}

/** GET /subscriber/transactions — paginated, immutable transaction ledger. */
export async function getTransactions(
  query: TransactionsQuery = {},
): Promise<TransactionsPage> {
  const { data } = await apiClient.get<TransactionsResponse>(
    "/subscriber/transactions",
    { params: { cursor: query.cursor, page_size: query.page_size } },
  );
  return { items: data.data, nextCursor: data.meta.next_cursor };
}

// ── Refund-eligible view (Story 3.7) ───────────────────────────────────────────

/** One failed recharge row returned by GET /transactions?type=FAILED. */
export interface FailedRechargeItem {
  readonly transaction_id: string;
  readonly plan_attempted: string;
  readonly amount_paise: number;
  readonly failure_reason: string | null;
  readonly created_at: string;
}

interface FailedRechargesResponse {
  readonly data: readonly FailedRechargeItem[];
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /subscriber/transactions?type=FAILED — refund-eligible failed recharges (Story 3.7). */
export async function getFailedRecharges(): Promise<
  readonly FailedRechargeItem[]
> {
  const { data } = await apiClient.get<FailedRechargesResponse>(
    "/subscriber/transactions",
    { params: { type: "FAILED" } },
  );
  return data.data;
}

// ── Plan details & catalogue (Story 3.4) ───────────────────────────────────────

/** Bundled plan quotas (null means unlimited). */
export interface PlanQuotas {
  readonly data_gb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
}

/** Active plan details returned by GET /subscriber/plan. */
export interface ActivePlanData {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly validity_expiry: string | null;
  readonly validity_days: number;
  readonly days_remaining: number | null;
  readonly quotas: PlanQuotas;
  readonly roaming_enabled: boolean;
}

interface ActivePlanResponse {
  readonly data: ActivePlanData;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /subscriber/plan — active plan name, validity expiry, and quotas. */
export async function getActivePlan(): Promise<ActivePlanData> {
  const { data } = await apiClient.get<ActivePlanResponse>("/subscriber/plan");
  return data.data;
}

/** One browsable plan in the catalogue (GET /plans). */
export interface PlanCatalogueItem {
  readonly id: string;
  readonly name: string;
  readonly data_gb: number | null;
  readonly voice_minutes: number | null;
  readonly sms_count: number | null;
  readonly validity_days: number;
  readonly price_paise: number;
  readonly plan_type: string | null;
}

interface PlansCatalogueResponse {
  readonly data: readonly PlanCatalogueItem[];
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/** GET /plans — browse all active plans (catalogue). */
export async function listPlans(): Promise<readonly PlanCatalogueItem[]> {
  const { data } = await apiClient.get<PlansCatalogueResponse>("/plans");
  return data.data;
}

// ── Recharge (Story 3.5) ───────────────────────────────────────────────────────

export interface RechargeRequest {
  readonly plan_id: string;
  readonly payment_method_id: string;
  readonly idempotency_key: string;
}

export interface RechargeResponse {
  readonly transaction_id: string;
  readonly new_balance_paise: number;
  readonly plan_activation_timestamp: string;
  readonly receipt_url: string;
}

interface RechargeResponseEnvelope {
  readonly data: RechargeResponse;
  readonly meta: { readonly trace_id: string; readonly timestamp: string };
}

/**
 * POST /subscriber/recharge — complete a recharge with idempotency (Story 3.5, AC #2, #3, #4, #5, #6).
 * Client generates idempotency_key (UUIDv7) for duplicate protection.
 */
export async function createRecharge(
  payload: RechargeRequest,
): Promise<RechargeResponse> {
  const { data } = await apiClient.post<RechargeResponseEnvelope>(
    "/subscriber/recharge",
    payload,
  );
  return data.data;
}

// ── PDF Receipt (Story 3.6) ────────────────────────────────────────────────────

/**
 * GET /subscriber/receipts/{transaction_id} — download PDF receipt as a Blob.
 * Auth via Bearer interceptor. Caller triggers browser download.
 */
export async function getReceipt(transactionId: string): Promise<Blob> {
  const { data } = await apiClient.get<Blob>(
    `/subscriber/receipts/${transactionId}`,
    { responseType: "blob" },
  );
  return data;
}

export { apiClient };
