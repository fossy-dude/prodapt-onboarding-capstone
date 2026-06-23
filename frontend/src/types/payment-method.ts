/**
 * Payment method types and interfaces (Story 1.10).
 *
 * Saved payment methods for quick recharge. Card numbers are tokenised
 * client-side before they reach the API (see tokenize.ts).
 *
 * @see AC #1, #3, #4 - Payment method data model
 */

/** Payment method type variants (AC #3, #4). */
export type PaymentMethodType =
  | "CREDIT_CARD"
  | "UPI"
  | "NET_BANKING"
  | "MOBILE_WALLET";

/** Base payment method record (AC #3). */
export interface PaymentMethod {
  readonly id: string;
  readonly subscriber_id: string;
  readonly type: PaymentMethodType;
  readonly token: string;
  readonly display_label: string;
  readonly is_default: boolean;
}

/** Request payload to add a payment method (AC #1). */
export interface AddPaymentMethodPayload {
  readonly type: PaymentMethodType;
  readonly token: string;
  readonly display_label: string;
}

/** Response envelope for payment method list (AC #6). */
export interface PaymentMethodsListResponse {
  readonly data: readonly PaymentMethod[];
  readonly meta: {
    readonly trace_id: string;
    readonly timestamp: string;
  };
}

/** Response envelope for single payment method operations. */
export interface PaymentMethodResponse {
  readonly data: PaymentMethod;
  readonly meta: {
    readonly trace_id: string;
    readonly timestamp: string;
  };
}
