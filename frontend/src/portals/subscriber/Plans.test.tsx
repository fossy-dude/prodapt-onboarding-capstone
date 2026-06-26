import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Plans } from "./Plans";

vi.mock("../../lib/api", () => ({
  listPlans: vi.fn(),
  getActivePlan: vi.fn(),
}));

const { listPlans, getActivePlan } = await import("../../lib/api");

const PLANS = [
  {
    id: "p-28a",
    name: "Basic 28",
    data_gb: 10,
    voice_minutes: 600,
    sms_count: 100,
    validity_days: 28,
    price_paise: 29900,
    plan_type: null,
    is_active: true,
  },
  {
    id: "p-28b",
    name: "Basic 28 Cheap",
    data_gb: 5,
    voice_minutes: 300,
    sms_count: 50,
    validity_days: 28,
    price_paise: 19900,
    plan_type: null,
    is_active: true,
  },
  {
    id: "p-56",
    name: "Long 56",
    data_gb: 20,
    voice_minutes: 1000,
    sms_count: 200,
    validity_days: 56,
    price_paise: 49900,
    plan_type: null,
    is_active: true,
  },
];

const ACTIVE = {
  plan_id: "p-28a",
  plan_name: "Basic 28",
  validity_expiry: "2026-02-01T00:00:00Z",
  validity_days: 28,
  days_remaining: 28,
  quotas: { data_gb: 10, voice_minutes: 600, sms_count: 100 },
  roaming_enabled: false,
};

function renderPlans() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Plans />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Plans catalogue", () => {
  beforeEach(() => {
    vi.mocked(listPlans).mockReset();
    vi.mocked(getActivePlan).mockReset();
  });

  it("renders all active plans after fetch (AC #3)", async () => {
    vi.mocked(listPlans).mockResolvedValue(PLANS);
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE);
    renderPlans();
    await waitFor(() =>
      expect(screen.getByText("Long 56")).toBeInTheDocument(),
    );
    expect(screen.getByText("Basic 28")).toBeInTheDocument();
    expect(screen.getByText("Basic 28 Cheap")).toBeInTheDocument();
  });

  it("shows the Current Plan badge on the active plan (AC #5)", async () => {
    vi.mocked(listPlans).mockResolvedValue(PLANS);
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE);
    renderPlans();
    await waitFor(() =>
      expect(screen.getByText("Current Plan")).toBeInTheDocument(),
    );
  });

  it("filters by validity 28 and hides the 56-day plan (AC #4)", async () => {
    vi.mocked(listPlans).mockResolvedValue(PLANS);
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE);
    renderPlans();
    await waitFor(() =>
      expect(screen.getByText("Long 56")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Filter plans by validity"), {
      target: { value: "28" },
    });
    await waitFor(() =>
      expect(screen.queryByText("Long 56")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("Basic 28")).toBeInTheDocument();
  });

  it("sorts by price descending (AC #4)", async () => {
    vi.mocked(listPlans).mockResolvedValue(PLANS);
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE);
    renderPlans();
    await waitFor(() =>
      expect(screen.getByText("Long 56")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Sort plans"), {
      target: { value: "price-desc" },
    });
    const names = screen
      .getAllByRole("heading", { level: 3 })
      .map((h) => h.textContent);
    expect(names).toEqual(["Long 56", "Basic 28", "Basic 28 Cheap"]);
  });

  it("shows an error state when the catalogue fetch fails", async () => {
    vi.mocked(listPlans).mockRejectedValue(new Error("Network error"));
    vi.mocked(getActivePlan).mockResolvedValue(ACTIVE);
    renderPlans();
    await waitFor(() =>
      expect(screen.getByText("Failed to load plans.")).toBeInTheDocument(),
    );
  });
});
