/**
 * Recharge mutation hook (Story 3.5).
 *
 * Manages the recharge process with optimistic updates and cache invalidation.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createRecharge, type RechargeRequest } from "../lib/api";

type RechargeResult = {
  readonly transaction_id: string;
  readonly new_balance_paise: number;
  readonly plan_activation_timestamp: string;
  readonly receipt_url: string;
};

type RechargeError = {
  readonly message: string;
  readonly code?: string;
};

/**
 * Mutation hook for completing a recharge.
 *
 * On success, invalidates the balance query to refresh wallet display.
 * Returns the transaction result for confirmation screen.
 * Includes error handling for cache invalidation failures.
 */
export function useRecharge() {
  const queryClient = useQueryClient();

  return useMutation<RechargeResult, RechargeError, RechargeRequest>({
    mutationFn: async (payload: RechargeRequest) => {
      return await createRecharge(payload);
    },
    onSuccess: async () => {
      // Invalidate balance query to refresh wallet display
      try {
        await queryClient.invalidateQueries({ queryKey: ["balance"] });
      } catch (error) {
        console.error("Failed to invalidate balance query:", error);
      }
      // Invalidate active plan to show new plan
      try {
        await queryClient.invalidateQueries({ queryKey: ["activePlan"] });
      } catch (error) {
        console.error("Failed to invalidate active plan query:", error);
      }
    },
  });
}
