import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getBalance, type WalletBalanceData } from "../lib/api";

export const BALANCE_QUERY_KEY = ["balance"] as const;

/** Read the subscriber's current wallet balance (Valkey-authoritative via API). */
export function useBalance() {
  return useQuery<WalletBalanceData, Error>({
    queryKey: BALANCE_QUERY_KEY,
    queryFn: getBalance,
  });
}

/** Return an imperative refetch helper that invalidates the cached balance. */
export function useRefreshBalance() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: BALANCE_QUERY_KEY });
}
