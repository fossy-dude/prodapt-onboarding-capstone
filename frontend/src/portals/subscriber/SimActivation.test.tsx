import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { SimActivation } from "./SimActivation";

// Mock api module: getActiveOrder + getOrderStatus are replaceable per-test.
vi.mock("../../lib/api", () => ({
  getActiveOrder: vi.fn(),
  getOrderStatus: vi.fn(),
  toApiError: () => null,
}));

const { getActiveOrder, getOrderStatus } = await import("../../lib/api");

const ORDER_ID = "order-uuid-1234";
const MSISDN = "9876543210";

function renderComponent() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SimActivation />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SimActivation subscriber tracker", () => {
  beforeEach(() => {
    vi.mocked(getActiveOrder).mockReset();
    vi.mocked(getOrderStatus).mockReset();
  });

  afterEach(() => {
    // Guard against fake-timer leakage from the polling-recurrence test.
    vi.useRealTimers();
  });

  it("shows loading state initially", () => {
    vi.mocked(getActiveOrder).mockReturnValue(new Promise(() => {})); // pending
    renderComponent();
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("renders step indicator for CREATED state", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "CREATED",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "CREATED",
      updated_at: "",
      msisdn: null,
    });
    renderComponent();
    await waitFor(() =>
      expect(screen.getByText("Order Created")).toBeInTheDocument(),
    );
    // CREATED is step 1 (index 0) — should be highlighted (active)
    expect(screen.getByText("KYC Pending")).toBeInTheDocument();
    expect(screen.getByText("KYC Verified")).toBeInTheDocument();
    expect(screen.getByText("Activated")).toBeInTheDocument();
    // No success banner
    expect(
      screen.queryByText(/your sim is activated/i),
    ).not.toBeInTheDocument();
    // No MSISDN shown
    expect(screen.queryByText(MSISDN)).not.toBeInTheDocument();
  });

  it("renders step indicator with checkmark for completed steps on KYC_PENDING", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "KYC_PENDING",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "KYC_PENDING",
      updated_at: "",
      msisdn: null,
    });
    renderComponent();
    await waitFor(() =>
      expect(screen.getByText("KYC Pending")).toBeInTheDocument(),
    );
    // Step 1 (CREATED) should show checkmark (✓)
    const steps = screen.getAllByText("✓");
    expect(steps).toHaveLength(1); // one completed step
    expect(screen.queryByText(MSISDN)).not.toBeInTheDocument();
  });

  it("renders three checkmarks for KYC_VERIFIED state", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "KYC_VERIFIED",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "KYC_VERIFIED",
      updated_at: "",
      msisdn: null,
    });
    renderComponent();
    await waitFor(() =>
      expect(screen.getByText("KYC Verified")).toBeInTheDocument(),
    );
    const checkmarks = screen.getAllByText("✓");
    expect(checkmarks).toHaveLength(2); // CREATED + KYC_PENDING done
    expect(screen.queryByText(MSISDN)).not.toBeInTheDocument();
  });

  it("renders success banner with MSISDN on ACTIVATED", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "ACTIVATED",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "ACTIVATED",
      updated_at: "",
      msisdn: MSISDN,
    });
    renderComponent();
    await waitFor(() =>
      expect(screen.getByLabelText("Activation complete")).toBeInTheDocument(),
    );
    expect(screen.getByText(/your sim is activated/i)).toBeInTheDocument();
    expect(screen.getByText(MSISDN)).toBeInTheDocument();
  });

  it("does not show MSISDN when status is not ACTIVATED", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "CREATED",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "CREATED",
      updated_at: "",
      msisdn: null,
    });
    renderComponent();
    await waitFor(() =>
      expect(
        screen.queryByRole("status", { name: /loading/i }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByText(MSISDN)).not.toBeInTheDocument();
  });

  it("shows error state when getActiveOrder fails", async () => {
    vi.mocked(getActiveOrder).mockRejectedValue(new Error("Network error"));
    renderComponent();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/unable to load/i);
  });

  it("re-fetches status on the 10s polling interval (polling actually recurs)", async () => {
    // Strengthened (P10): the old test only asserted the initial fetch, so a
    // regression that deleted refetchInterval entirely still passed. Advance fake
    // timers past one interval and assert getOrderStatus is called again.
    vi.useFakeTimers();
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "CREATED",
      updated_at: "",
    });
    vi.mocked(getOrderStatus).mockResolvedValue({
      status: "CREATED",
      updated_at: "",
      msisdn: null,
    });
    renderComponent();
    // Let the initial fetch chain settle first (flush microtasks, no clock advance),
    // so the refetch timer is scheduled before we advance time.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(vi.mocked(getOrderStatus)).toHaveBeenCalledWith(ORDER_ID);
    // Advance one full interval; CREATED is non-terminal so a refetch should fire.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    // Initial fetch + at least one scheduled refetch ⇒ refetchInterval is wired.
    expect(vi.mocked(getOrderStatus).mock.calls.length).toBeGreaterThanOrEqual(
      2,
    );
  });

  it("shows an empty state (not an error) when the subscriber has no active order", async () => {
    // D7: a 200 + null active order renders an empty/CTA state, not the error page.
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: null,
      status: null,
      updated_at: null,
    });
    renderComponent();
    await waitFor(() =>
      expect(
        screen.getByLabelText("No activation in progress"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/no sim activation in progress/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/unable to load/i)).not.toBeInTheDocument();
  });

  it("getOrderStatus is NOT called when ACTIVATED (polling stops)", async () => {
    vi.mocked(getActiveOrder).mockResolvedValue({
      order_id: ORDER_ID,
      status: "ACTIVATED",
      updated_at: "",
    });
    const statusMock = vi.mocked(getOrderStatus).mockResolvedValue({
      status: "ACTIVATED",
      updated_at: "",
      msisdn: MSISDN,
    });
    renderComponent();
    await waitFor(() => expect(screen.getByText(MSISDN)).toBeInTheDocument());
    // After initial resolution, no further refetch triggered immediately
    expect(statusMock).toHaveBeenCalledTimes(1);
  });
});
