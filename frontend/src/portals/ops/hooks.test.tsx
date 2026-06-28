import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "../../lib/api";
import {
  useOrderCounts,
  useOrdersByStatus,
  usePlanDemandForecast,
  usePlanStock,
  useSubscriberGrowthForecast,
} from "./hooks";

vi.mock("../../lib/api", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

const apiGet = vi.mocked(apiClient.get);

function wrapper({ children }: { readonly children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  apiGet.mockReset();
});

describe("ops hooks", () => {
  it("fetches plan stock through the shared API client", async () => {
    apiGet.mockResolvedValue({ data: { data: [] } });

    const { result } = renderHook(() => usePlanStock(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/ops/plan-stock");
  });

  it("fetches plan demand forecasts through the shared API client", async () => {
    apiGet.mockResolvedValue({
      data: {
        data: {
          forecasts: [],
          model_version: null,
          trained_at: null,
          cache_expires_at: null,
        },
      },
    });

    const { result } = renderHook(() => usePlanDemandForecast(true), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/ops/forecasts/plan-demand", {
      params: { force_refresh: true },
    });
  });

  it("fetches subscriber growth forecasts through the shared API client", async () => {
    apiGet.mockResolvedValue({
      data: {
        data: {
          forecast_type: "subscriber_growth",
          model_version: "test",
          trained_at: "2026-06-28T00:00:00Z",
          cache_expires_at: "2026-06-29T00:00:00Z",
          horizon_days: 90,
          from_cache: true,
          metrics: {
            mape_activations: 1,
            mape_churn: 1,
            passed_mape_threshold: true,
            holdout_days: 30,
          },
          forecasts: [],
        },
      },
    });

    const { result } = renderHook(() => useSubscriberGrowthForecast(true), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/ops/forecasts/subscriber-growth", {
      params: { force_refresh: true },
    });
  });

  it("fetches order counts through the shared API client", async () => {
    apiGet.mockResolvedValue({ data: { data: { CREATED: 1 } } });

    const { result } = renderHook(() => useOrderCounts(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/ops/orders");
  });

  it("fetches filtered orders through the shared API client", async () => {
    apiGet.mockResolvedValue({ data: { data: [] } });

    const { result } = renderHook(() => useOrdersByStatus("CREATED", 20, 0), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiGet).toHaveBeenCalledWith("/ops/orders", {
      params: { status: "CREATED", limit: 20, offset: 0 },
    });
  });
});
