/**
 * Tests for Ops Dashboard component (Story 7.2 Task 7).
 */

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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
}));

describe("Dashboard", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
      },
    });
  });

  const wrapper = ({ children }: { readonly children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );

  it("renders dashboard with title and description", () => {
    render(<Dashboard />, { wrapper });

    expect(screen.getByText("Operations Dashboard")).toBeInTheDocument();
    expect(
      screen.getByText(/Real-time plan adoption and order fulfilment monitoring/)
    ).toBeInTheDocument();
  });

  it("displays PlanStock and OrderFulfilment components", () => {
    render(<Dashboard />, { wrapper });

    expect(screen.getByText("Plan Stock")).toBeInTheDocument();
    expect(screen.getByText("Order Fulfilment")).toBeInTheDocument();
  });

  it("shows error state when data fetching fails", async () => {
    const { usePlanStock } = await import("./hooks");
    (usePlanStock as any).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("Failed to fetch"),
    });

    render(<Dashboard />, { wrapper });

    await waitFor(() => {
      expect(screen.getByText("Error loading dashboard data")).toBeInTheDocument();
      expect(screen.getByText("Retry")).toBeInTheDocument();
    });
  });

  it("shows auto-refresh indicator in description", () => {
    render(<Dashboard />, { wrapper });

    expect(screen.getByText(/Auto-refreshes every 30 seconds/)).toBeInTheDocument();
  });
});
