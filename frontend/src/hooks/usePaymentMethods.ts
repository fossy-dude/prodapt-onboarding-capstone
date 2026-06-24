/**
 * Payment methods hook (Story 1.10, reused in Story 3.5).
 *
 * Manages the subscriber's saved payment methods.
 */

import { useQuery } from "@tanstack/react-query";
import { getPaymentMethods } from "../lib/api";
import { type PaymentMethod } from "../types/payment-method";

/**
 * Query hook for fetching the subscriber's saved payment methods.
 *
 * Returns the list of payment methods with caching and stale-time
 * to avoid excessive API calls.
 */
export function usePaymentMethods() {
  return useQuery<readonly PaymentMethod[]>({
    queryKey: ["paymentMethods"],
    queryFn: async () => {
      const response = await getPaymentMethods();
      return response.data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}
