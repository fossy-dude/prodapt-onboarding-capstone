import { useQuery } from "@tanstack/react-query";

import { getActiveOrder, getOrderStatus } from "../lib/api";

/**
 * Discover the subscriber's active order then poll its status every 10 seconds.
 * Polling stops once status reaches 'ACTIVATED' (terminal state) or on any query
 * error (403/404/network) to avoid retrying a permanently-failing request.
 *
 * Architecture: TanStack Query + refetchInterval (Story 1.7 AC #2; §1.9.3).
 * No manual setInterval — polling is managed entirely by the query layer.
 */
export function useOrderStatus() {
  const activeQuery = useQuery({
    queryKey: ["activeOrder"],
    queryFn: getActiveOrder,
  });

  const orderId = activeQuery.data?.order_id ?? null;

  const statusQuery = useQuery({
    queryKey: ["orderStatus", orderId],
    queryFn: () => getOrderStatus(orderId!),
    enabled: orderId !== null,
    refetchInterval: (query) => {
      if (query.state.error) return false;
      if (query.state.data?.status === "ACTIVATED") return false;
      return 10_000;
    },
  });

  return {
    orderId,
    hasActiveOrder: orderId !== null,
    status: statusQuery.data?.status ?? null,
    msisdn: statusQuery.data?.msisdn ?? null,
    updatedAt: statusQuery.data?.updated_at ?? null,
    isLoading:
      activeQuery.isLoading || (orderId !== null && statusQuery.isLoading),
    isError: activeQuery.isError || statusQuery.isError,
    error: activeQuery.error ?? statusQuery.error,
  };
}
