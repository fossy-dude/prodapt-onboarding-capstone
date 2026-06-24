/**
 * Tests for NotificationPreferences component (Story 4.2).
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NotificationPreferences } from "./NotificationPreferences";
import * as api from "../../lib/api";

// Mock the API module
vi.mock("../../lib/api", () => ({
  getNotificationPreferences: vi.fn(),
  patchNotificationPreference: vi.fn(),
}));

describe("NotificationPreferences", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          retry: false,
        },
        mutations: {
          retry: false,
        },
      },
    });
  });

  const mockPreferences = [
    { notification_type: "LOW_BALANCE", is_enabled: true },
    { notification_type: "BALANCE_DEPLETED", is_enabled: false },
    { notification_type: "PLAN_EXPIRY_REMINDER", is_enabled: true },
    { notification_type: "DATA_NUDGE", is_enabled: false },
  ] as const;

  it("renders loading state initially", () => {
    vi.mocked(api.getNotificationPreferences).mockImplementation(
      () => new Promise(() => {}), // Never resolves
    );

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("heading", { name: /notification preferences/i }),
    ).toBeInTheDocument();
  });

  it("renders notification preferences when loaded", async () => {
    vi.mocked(api.getNotificationPreferences).mockResolvedValue(
      mockPreferences,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Low Balance Alert")).toBeInTheDocument();
      expect(screen.getByText("Balance Depleted")).toBeInTheDocument();
      expect(screen.getByText("Plan Expiry Reminder")).toBeInTheDocument();
      expect(screen.getByText("Data Usage Nudge")).toBeInTheDocument();
    });
  });

  it("displays error state on API failure", async () => {
    vi.mocked(api.getNotificationPreferences).mockRejectedValue(
      new Error("API Error"),
    );

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/error loading preferences/i),
      ).toBeInTheDocument();
    });
  });

  it("renders all 4 notification types with correct labels", async () => {
    vi.mocked(api.getNotificationPreferences).mockResolvedValue(
      mockPreferences,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Low Balance Alert")).toBeInTheDocument();
      expect(screen.getByText("Balance Depleted")).toBeInTheDocument();
      expect(screen.getByText("Plan Expiry Reminder")).toBeInTheDocument();
      expect(screen.getByText("Data Usage Nudge")).toBeInTheDocument();
    });
  });

  it("shows toggle switches for each preference", async () => {
    vi.mocked(api.getNotificationPreferences).mockResolvedValue(
      mockPreferences,
    );

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      const toggles = screen.getAllByRole("switch");
      expect(toggles).toHaveLength(4);
    });
  });

  it("calls patch API when toggle is changed", async () => {
    vi.mocked(api.getNotificationPreferences).mockResolvedValue(
      mockPreferences,
    );
    vi.mocked(api.patchNotificationPreference).mockResolvedValue({
      notification_type: "LOW_BALANCE",
      is_enabled: false,
    });

    render(
      <QueryClientProvider client={queryClient}>
        <NotificationPreferences />
      </QueryClientProvider>,
    );

    await waitFor(() => {
      const toggles = screen.getAllByRole("switch");
      expect(toggles).toHaveLength(4);
    });

    const toggles = screen.getAllByRole("switch");
    const lowBalanceToggle = toggles[0];

    lowBalanceToggle.click();

    await waitFor(() => {
      expect(api.patchNotificationPreference).toHaveBeenCalledWith({
        notification_type: "LOW_BALANCE",
        is_enabled: false,
      });
    });
  });
});
