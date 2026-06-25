/**
 * React Query hooks for ops dashboard data fetching.
 * Provides auto-refreshing queries for plan stock and order fulfilment data.
 */

import { useQuery } from "@tanstack/react-query";

/**
 * Plan stock item returned from the API.
 */
interface PlanStockItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly subscriber_count: number;
}

/**
 * Order fulfilment status counts.
 */
type OrderFulfilmentCounts = Record<string, number>;

/**
 * Order item returned from the API.
 */
interface OrderItem {
  readonly order_id: string;
  readonly subscriber_id: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly status: string;
}

/**
 * Custom hook to fetch plan stock data with 30-second auto-refresh.
 */
export function usePlanStock() {
  return useQuery<PlanStockItem[]>({
    queryKey: ["ops", "plan-stock"],
    queryFn: async () => {
      const token = localStorage.getItem("token");
      const response = await fetch("/api/v1/ops/plan-stock", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch plan stock: ${response.statusText}`);
      }

      const data = await response.json();
      return data.data;
    },
    refetchInterval: 30000, // 30-second auto-refresh (Story 7.2 AC #6)
    retry: 1,
  });
}

/**
 * Custom hook to fetch order fulfilment counts with 30-second auto-refresh.
 */
export function useOrderCounts() {
  return useQuery<OrderFulfilmentCounts>({
    queryKey: ["ops", "order-counts"],
    queryFn: async () => {
      const token = localStorage.getItem("token");
      const response = await fetch("/api/v1/ops/orders", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch order counts: ${response.statusText}`);
      }

      const data = await response.json();
      return data.data;
    },
    refetchInterval: 30000, // 30-second auto-refresh
    retry: 1,
  });
}

/**
 * Custom hook to fetch orders by status with 30-second auto-refresh.
 * @param status - Order status to filter by
 * @param limit - Pagination limit (default 20)
 * @param offset - Pagination offset (default 0)
 */
export function useOrdersByStatus(
  status: string,
  limit: number = 20,
  offset: number = 0,
) {
  return useQuery<OrderItem[]>({
    queryKey: ["ops", "orders", status, limit, offset],
    queryFn: async () => {
      const token = localStorage.getItem("token");
      const params = new URLSearchParams({
        status,
        limit: limit.toString(),
        offset: offset.toString(),
      });

      const response = await fetch(`/api/v1/ops/orders?${params}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch orders: ${response.statusText}`);
      }

      const data = await response.json();
      return data.data;
    },
    refetchInterval: 30000, // 30-second auto-refresh
    retry: 1,
  });
}
