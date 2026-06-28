/**
 * Tests for Ops Dashboard component (Story 7.2 Task 7).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Dashboard } from "./Dashboard";

// Mock the hooks
vi.mock("./hooks", () => ({
  usePlanStock: vi.fn(() => ({
    data: [
      {
        plan_id: "plan-1",
        plan_name: "Basic Plan",
        subscriber_count: 150,
      },
    ],
    isLoading: false,
    error: null,
  })),
  useOrderCounts: vi.fn(() => ({
    data: {
      CREATED: 10,
      ACTIVATED: 5,
    },
    isLoading: false,
    error: null,
  })),
  useOrdersByStatus: vi.fn(() => ({
    data: [],
    isLoading: false,
    error: null,
  })),
  usePlanDemandForecast: vi.fn(() => ({
    data: {
      forecasts: [],
      model_version: null,
      trained_at: null,
      cache_expires_at: null,
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
}));

describe("Dashboard", () => {
  let queryClient: QueryClient;

  beforeEach(async () => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });

    // Reset the overview hooks to success defaults before each test so a per-test
    // override (the error-state test) cannot leak into sibling tests.
    const { usePlanStock, useOrderCounts, useOrdersByStatus } =
      await import("./hooks");
    (usePlanStock as ReturnType<typeof vi.fn>).mockReturnValue({
      data: [
        {
          plan_id: "plan-1",
          plan_name: "Basic Plan",
          subscriber_count: 150,
        },
      ],
      isLoading: false,
      error: null,
    });
    (useOrderCounts as ReturnType<typeof vi.fn>).mockReturnValue({
      data: {
        CREATED: 10,
        ACTIVATED: 5,
      },
      isLoading: false,
      error: null,
    });
    (useOrdersByStatus as ReturnType<typeof vi.fn>).mockReturnValue({
      data: [],
      isLoading: false,
      error: null,
    });
  });

  const wrapper = ({ children }: { readonly children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("renders dashboard with title and description", () => {
    render(<Dashboard />, { wrapper });

    expect(screen.getByText("Operations Dashboard")).toBeInTheDocument();
    expect(
      screen.getByText(
        /Real-time plan adoption and order fulfilment monitoring/,
      ),
    ).toBeInTheDocument();
  });

  it("displays PlanStock and OrderFulfilment components", () => {
    render(<Dashboard />, { wrapper });

    expect(screen.getByText("Plan Stock")).toBeInTheDocument();
    expect(screen.getByText("Order Fulfilment")).toBeInTheDocument();
  });

  it("shows error state when data fetching fails", async () => {
    const { usePlanStock } = await import("./hooks");
    (usePlanStock as ReturnType<typeof vi.fn>).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Failed to fetch"),
    });

    render(<Dashboard />, { wrapper });

    await waitFor(() => {
      expect(
        screen.getByText("Error loading dashboard data"),
      ).toBeInTheDocument();
      expect(screen.getByText("Retry")).toBeInTheDocument();
    });
  });

  it("shows auto-refresh indicator in description", () => {
    render(<Dashboard />, { wrapper });

    expect(
      screen.getByText(/Auto-refreshes every 30 seconds/),
    ).toBeInTheDocument();
  });
});
