import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { SimActivationSimulator } from "./SimActivationSimulator";

vi.mock("../../lib/api", () => ({
  activateSim: vi.fn(),
  toApiError: () => null,
}));

const { activateSim } = await import("../../lib/api");

function renderComponent() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SimActivationSimulator />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SimActivationSimulator", () => {
  beforeEach(() => {
    vi.mocked(activateSim).mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the lookup form with the Activate button disabled until a value is entered", () => {
    renderComponent();
    expect(screen.getByLabelText(/Lookup by/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Registration ID/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Activate/i })).toBeDisabled();
  });

  it("activates a subscriber by registration id and shows the MSISDN + balance", async () => {
    vi.mocked(activateSim).mockResolvedValue({
      order_id: "22222222-2222-4222-8222-222222222222",
      status: "ACTIVATED",
      msisdn: "9876543210",
      balance_paise: 4999,
    });
    const user = userEvent.setup();
    renderComponent();

    await user.type(
      screen.getByLabelText(/Registration ID/i),
      "REG-20260623-deadbeef",
    );
    await user.click(screen.getByRole("button", { name: /Activate/i }));

    await waitFor(() => expect(activateSim).toHaveBeenCalledTimes(1));
    expect(vi.mocked(activateSim).mock.calls[0]?.[0]).toEqual({
      lookup_type: "registration_id",
      lookup_value: "REG-20260623-deadbeef",
    });
    await waitFor(() =>
      expect(screen.getByText("9876543210")).toBeInTheDocument(),
    );
    expect(screen.getByText(/₹49.99/)).toBeInTheDocument();
    expect(screen.getByText(/4999p/)).toBeInTheDocument();
    expect(screen.getByText("ACTIVATED")).toBeInTheDocument();
  });

  it("can look up by MSISDN and passes the selected lookup type", async () => {
    vi.mocked(activateSim).mockResolvedValue({
      order_id: "order-1",
      status: "ACTIVATED",
      msisdn: "9123456780",
      balance_paise: 299,
    });
    const user = userEvent.setup();
    renderComponent();

    await user.selectOptions(screen.getByLabelText(/Lookup by/i), "msisdn");
    await user.type(screen.getByLabelText(/MSISDN/i), "9123456780");
    await user.click(screen.getByRole("button", { name: /Activate/i }));

    await waitFor(() =>
      expect(vi.mocked(activateSim).mock.calls[0]?.[0]).toEqual({
        lookup_type: "msisdn",
        lookup_value: "9123456780",
      }),
    );
  });

  it("surfaces an error when activation fails", async () => {
    vi.mocked(activateSim).mockRejectedValue(new Error("boom"));
    const user = userEvent.setup();
    renderComponent();

    await user.type(screen.getByLabelText(/Registration ID/i), "REG-x");
    await user.click(screen.getByRole("button", { name: /Activate/i }));

    await waitFor(() => expect(activateSim).toHaveBeenCalledTimes(1));
    // toApiError is mocked to null -> falls back to the generic message
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/Activation failed/i),
    );
  });
});
