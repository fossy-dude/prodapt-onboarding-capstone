/**
 * Tests for Forecasts tabbed component (Story 7.4 Task 9).
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Forecasts } from "./Forecasts";

vi.mock("./hooks", () => ({
  usePlanDemandForecast: vi.fn(() => ({
    data: {
      forecasts: [
        {
          plan_id: "plan-1",
          plan_name: "Basic Plan",
          predicted_uptake_30d: 100,
          predicted_uptake_60d: 200,
          predicted_uptake_90d: 300,
          uptake_trend_90d: Array.from({ length: 90 }, () => 5),
        },
      ],
      model_version: "holt_winters_v1",
      trained_at: "2026-06-26T03:00:00Z",
      cache_expires_at: "2026-06-27T03:00:00Z",
    },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  useSubscriberGrowthForecast: vi.fn(() => ({
    data: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  })),
  usePlanStock: vi.fn(() => ({ data: [], isLoading: false, error: null })),
  useOrderCounts: vi.fn(() => ({ data: {}, isLoading: false, error: null })),
  useOrdersByStatus: vi.fn(() => ({ data: [], isLoading: false, error: null })),
}));

vi.mock("recharts", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({
      children,
    }: {
      readonly children: React.ReactNode;
    }) => <div>{children}</div>,
  };
});

describe("Forecasts", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  const wrapper = ({ children }: { readonly children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("renders Plan Demand tab by default", () => {
    render(<Forecasts />, { wrapper });

    expect(screen.getByText("Plan Demand")).toBeInTheDocument();
    expect(screen.getByText("Basic Plan")).toBeInTheDocument();
  });

  it("renders Subscriber Growth tab", async () => {
    const user = userEvent.setup();
    render(<Forecasts />, { wrapper });

    await user.click(screen.getByText("Subscriber Growth"));

    // SubscriberGrowthForecast renders with no data — shows empty chart area
    expect(screen.getAllByText("Subscriber Growth").length).toBeGreaterThan(0);
  });

  it("shows model metadata when available", () => {
    render(<Forecasts />, { wrapper });

    expect(screen.getByText(/holt_winters_v1/i)).toBeInTheDocument();
  });

  it("shows Refresh Forecast button on Plan Demand tab", () => {
    render(<Forecasts />, { wrapper });

    expect(
      screen.getByRole("button", { name: /Refresh Forecast/i }),
    ).toBeInTheDocument();
  });

  it("runs forecast for selected plans", async () => {
    const user = userEvent.setup();
    const { usePlanDemandForecast, usePlanStock } = await import("./hooks");
    vi.mocked(usePlanStock).mockReturnValue({
      data: [
        {
          plan_id: "plan-2",
          plan_name: "Premium Plan",
          subscriber_count: 42,
        },
      ],
      isLoading: false,
      error: null,
    } as ReturnType<typeof usePlanStock>);

    render(<Forecasts />, { wrapper });

    await user.click(screen.getByRole("checkbox", { name: /Premium Plan/i }));
    await user.click(screen.getByRole("button", { name: /Run forecast/i }));

    await waitFor(() => {
      expect(vi.mocked(usePlanDemandForecast)).toHaveBeenLastCalledWith(
        expect.objectContaining({
          forceRefresh: true,
          planIds: ["plan-2"],
        }),
      );
    });
  });

  it("shows error and retry when query fails", async () => {
    const { usePlanDemandForecast } = await import("./hooks");
    vi.mocked(usePlanDemandForecast).mockReturnValueOnce({
      data: undefined,
      isLoading: false,
      error: new Error("Network error"),
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof usePlanDemandForecast>);

    render(<Forecasts />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load forecast data/i),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});
