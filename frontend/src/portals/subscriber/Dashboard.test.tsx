import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Dashboard } from "./Dashboard";

vi.mock("../../lib/api", () => ({
  getBalance: vi.fn(),
  getUsage: vi.fn(),
  getActivePlan: vi.fn(),
}));

const { getBalance, getUsage, getActivePlan } = await import("../../lib/api");

const BALANCE_DATA = {
  subscriber_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  msisdn: "9876543210",
  msisdn_masked: "***3210",
  balance_paise: 50000,
  balance_inr: "₹500.00",
  last_updated_at: null,
};

const USAGE_DATA = {
  subscriber_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  plan_period: {
    start: "2026-01-01T00:00:00Z",
    end: "2026-01-29T00:00:00Z",
  },
  voice_minutes: { used: 120, allowance: 600, unlimited: false },
  data_mb: 2048,
  data_gb: 2,
  data: { used: 2048, allowance: 10240, unlimited: false },
  sms: { used: 30, allowance: 100, unlimited: false },
  roaming_mb: { used: 0, allowance: null, unlimited: true },
};

const ACTIVE_PLAN_DATA = {
  plan_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  plan_name: "Test Plan",
  validity_expiry: "2026-01-29T00:00:00Z",
  validity_days: 28,
  days_remaining: 20,
  quotas: { data_gb: 10, voice_minutes: 600, sms_count: 100 },
  roaming_enabled: false,
};

function renderDashboard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.mocked(getBalance).mockReset();
    vi.mocked(getUsage).mockReset();
    vi.mocked(getActivePlan).mockReset();
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE_PLAN_DATA);
  });

  it("renders INR balance after fetch (AC #1)", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByText("₹500.00")).toBeInTheDocument(),
    );
    expect(screen.getByText("9876543210")).toBeInTheDocument();
  });

  it("shows 'Balance depleted' banner when balance is zero (AC #3)", async () => {
    vi.mocked(getBalance).mockResolvedValue({
      ...BALANCE_DATA,
      balance_paise: 0,
      balance_inr: "₹0.00",
    });
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByText("Balance depleted")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /Recharge Now/i }),
    ).toBeInTheDocument();
  });

  it("renders usage rings for voice, data, SMS, roaming (AC #4, #5)", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() => expect(screen.getByText("Voice")).toBeInTheDocument());
    expect(screen.getByText("Data")).toBeInTheDocument();
    expect(screen.getByText("SMS")).toBeInTheDocument();
    expect(screen.getByText("Roaming")).toBeInTheDocument();
  });

  it("shows 'Unlimited' label when roaming has no cap (AC #5)", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByText("Unlimited")).toBeInTheDocument(),
    );
  });

  it("shows error state when balance fetch fails", async () => {
    vi.mocked(getBalance).mockRejectedValue(new Error("Network error"));
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByText("Failed to load balance.")).toBeInTheDocument(),
    );
  });

  it("has a Refresh button for manual balance refetch (AC #6)", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    renderDashboard();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Refresh balance/i }),
      ).toBeInTheDocument(),
    );
  });

  it("shows the 'Expiring soon' badge when the active plan is within 3 days (AC #2)", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    vi.mocked(getActivePlan).mockResolvedValue({
      ...ACTIVE_PLAN_DATA,
      days_remaining: 2,
    });
    renderDashboard();
    await waitFor(() =>
      expect(screen.getByText("Expiring soon")).toBeInTheDocument(),
    );
  });
});
