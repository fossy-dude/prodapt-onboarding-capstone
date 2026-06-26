import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { PlanDetailsCard } from "./PlanDetailsCard";

vi.mock("../../lib/api", () => ({
  getActivePlan: vi.fn(),
  getUsage: vi.fn(),
}));

const { getActivePlan, getUsage } = await import("../../lib/api");

const PLAN = {
  plan_id: "p-28a",
  plan_name: "Unlimited 5G",
  validity_expiry: "2026-01-29T00:00:00Z",
  validity_days: 28,
  days_remaining: 20,
  quotas: { data_gb: 10, voice_minutes: 600, sms_count: 100 },
  roaming_enabled: false,
};

const USAGE = {
  subscriber_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  plan_period: { start: "2026-01-01T00:00:00Z", end: "2026-01-29T00:00:00Z" },
  voice_minutes: { used: 120, allowance: 600, unlimited: false },
  data_mb: 2048,
  data_gb: 2,
  data: { used: 2048, allowance: 10240, unlimited: false },
  sms: { used: 30, allowance: 100, unlimited: false },
  roaming_mb: { used: 0, allowance: null, unlimited: true },
};

function renderCard() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <PlanDetailsCard />
    </QueryClientProvider>,
  );
}

describe("PlanDetailsCard", () => {
  beforeEach(() => {
    vi.mocked(getActivePlan).mockReset();
    vi.mocked(getUsage).mockReset();
  });

  it("renders plan name, validity and quotas (AC #1)", async () => {
    vi.mocked(getActivePlan).mockResolvedValue(PLAN);
    vi.mocked(getUsage).mockResolvedValue(USAGE);
    renderCard();
    await waitFor(() =>
      expect(screen.getByText("Unlimited 5G")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Valid until/)).toBeInTheDocument();
    expect(screen.getByText("Data 10 GB")).toBeInTheDocument();
    expect(screen.getByText("Voice 600 min")).toBeInTheDocument();
    expect(screen.getByText("SMS 100 msgs")).toBeInTheDocument();
  });

  it("shows 'Expiring soon' badge when days remaining is <= 3 (AC #2)", async () => {
    vi.mocked(getActivePlan).mockResolvedValue({ ...PLAN, days_remaining: 2 });
    vi.mocked(getUsage).mockResolvedValue(USAGE);
    renderCard();
    await waitFor(() =>
      expect(screen.getByText("Expiring soon")).toBeInTheDocument(),
    );
  });

  it("does not show the badge when days remaining is > 3 (AC #2)", async () => {
    vi.mocked(getActivePlan).mockResolvedValue({ ...PLAN, days_remaining: 20 });
    vi.mocked(getUsage).mockResolvedValue(USAGE);
    renderCard();
    await waitFor(() =>
      expect(screen.getByText("Unlimited 5G")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Expiring soon")).not.toBeInTheDocument();
  });
});
