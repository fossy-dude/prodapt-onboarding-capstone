/**
 * React Query hooks for ops dashboard data fetching.
 * Provides auto-refreshing queries for plan stock and order fulfilment data.
 */

import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../lib/api";

/**
 * Plan stock item returned from the API.
 */
interface PlanStockItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly subscriber_count: number;
}

interface ApiEnvelope<TData> {
  readonly data: TData;
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
      const { data } = await apiClient.get<ApiEnvelope<PlanStockItem[]>>(
        "/ops/plan-stock",
      );
      return data.data;
    },
    refetchInterval: 30000, // 30-second auto-refresh (Story 7.2 AC #6)
    retry: 1,
  });
}

/**
 * Plan demand forecast item returned from the API.
 */
interface PlanDemandForecastItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly predicted_uptake_30d: number;
  readonly predicted_uptake_60d: number;
  readonly predicted_uptake_90d: number;
  readonly uptake_trend_90d: readonly number[];
}

/**
 * Plan demand forecast API response shape.
 */
interface PlanDemandForecastResponse {
  readonly forecasts: readonly PlanDemandForecastItem[];
  readonly model_version: string | null;
  readonly trained_at: string | null;
  readonly cache_expires_at: string | null;
}

/**
 * Custom hook to fetch plan demand forecast data (no auto-refresh; forecasts cached daily).
 * Pass forceRefresh=true to bypass the 24-hour cache.
 */
export function usePlanDemandForecast(forceRefresh = false) {
  return useQuery<PlanDemandForecastResponse>({
    queryKey: ["ops", "forecasts", "plan-demand", forceRefresh],
    queryFn: async () => {
      const { data } = await apiClient.get<ApiEnvelope<PlanDemandForecastResponse>>(
        "/ops/forecasts/plan-demand",
        { params: forceRefresh ? { force_refresh: true } : undefined },
      );
      return data.data;
    },
    retry: 1,
    staleTime: 60 * 60 * 1000, // treat as fresh for 1 hour (server TTL is 24h)
  });
}

/**
 * One daily projection point in the subscriber growth forecast (Story 7.3).
 */
export interface SubscriberGrowthForecastPoint {
  readonly date: string;
  readonly predicted_activations: number;
  readonly predicted_churn: number;
  readonly lower_bound_activations: number;
  readonly upper_bound_activations: number;
  readonly lower_bound_churn: number;
  readonly upper_bound_churn: number;
}

/**
 * Forecast quality metrics reported on the most-recent holdout window (Story 7.3).
 */
export interface SubscriberGrowthForecastMetrics {
  readonly mape_activations: number;
  readonly mape_churn: number;
  readonly passed_mape_threshold: boolean;
  readonly holdout_days: number;
}

/**
 * Subscriber growth forecast API response shape (the `data` payload, Story 7.3).
 */
export interface SubscriberGrowthForecastData {
  readonly forecast_type: string;
  readonly model_version: string;
  readonly trained_at: string;
  readonly cache_expires_at: string;
  readonly horizon_days: number;
  readonly from_cache: boolean;
  readonly metrics: SubscriberGrowthForecastMetrics;
  readonly forecasts: readonly SubscriberGrowthForecastPoint[];
}

/**
 * Custom hook to fetch the subscriber growth forecast (no auto-refresh; cached daily).
 * Pass forceRefresh=true to bypass the 24-hour server cache and retrain on demand.
 */
export function useSubscriberGrowthForecast(forceRefresh = false) {
  return useQuery<SubscriberGrowthForecastData>({
    queryKey: ["ops", "forecasts", "subscriber-growth", forceRefresh],
    queryFn: async () => {
      const { data } = await apiClient.get<ApiEnvelope<SubscriberGrowthForecastData>>(
        "/ops/forecasts/subscriber-growth",
        { params: forceRefresh ? { force_refresh: true } : undefined },
      );
      return data.data;
    },
    retry: 1,
    staleTime: 24 * 60 * 60 * 1000, // 24h — forecasts are cached daily, no auto-refresh
  });
}

/**
 * Custom hook to fetch order fulfilment counts with 30-second auto-refresh.
 */
export function useOrderCounts() {
  return useQuery<OrderFulfilmentCounts>({
    queryKey: ["ops", "order-counts"],
    queryFn: async () => {
      const { data } = await apiClient.get<ApiEnvelope<OrderFulfilmentCounts>>(
        "/ops/orders",
      );
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
      const { data } = await apiClient.get<ApiEnvelope<OrderItem[]>>("/ops/orders", {
        params: { status, limit, offset },
      });
      return data.data;
    },
    refetchInterval: 30000, // 30-second auto-refresh
    retry: 1,
  });
}
