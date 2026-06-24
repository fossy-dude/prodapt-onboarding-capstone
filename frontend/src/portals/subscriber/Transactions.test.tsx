import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import { Transactions } from "./Transactions";

vi.mock("../../lib/api", () => ({
  getTransactions: vi.fn(),
  getFailedRecharges: vi.fn(),
}));

const { getTransactions, getFailedRecharges } = await import("../../lib/api");
import type { TransactionsPage, FailedRechargeItem } from "../../lib/api";

const PAGE_1: TransactionsPage = {
  items: [
    {
      id: "t1",
      transaction_type: "cdr_deduction",
      amount_paise: 500,
      balance_after_paise: 49500,
      cdr_reference: "cdr-abc-123",
      description: "Data session",
      created_at: "2026-06-01T10:00:00Z",
    },
    {
      id: "t2",
      transaction_type: "recharge",
      amount_paise: 10000,
      balance_after_paise: 50000,
      cdr_reference: null,
      description: "Wallet top-up",
      created_at: "2026-06-01T09:00:00Z",
    },
  ],
  nextCursor: "cursor-2",
};

const PAGE_2: TransactionsPage = {
  items: [
    {
      id: "t3",
      transaction_type: "cdr_deduction",
      amount_paise: 200,
      balance_after_paise: 9800,
      cdr_reference: "cdr-xyz-9",
      description: "Voice call",
      created_at: "2026-05-30T10:00:00Z",
    },
  ],
  nextCursor: null,
};

function renderTransactions() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Transactions />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Transactions", () => {
  beforeEach(() => {
    vi.mocked(getTransactions).mockReset();
    vi.mocked(getTransactions).mockImplementation(async (query = {}) => {
      if (!query.cursor) return PAGE_1;
      return PAGE_2;
    });
  });

  it("renders rows with friendly type labels and INR amounts (AC #1)", async () => {
    renderTransactions();
    await waitFor(() => expect(screen.getByText("Charge")).toBeInTheDocument());
    expect(screen.getByText("Recharge")).toBeInTheDocument();
    expect(screen.getByText("₹5.00")).toBeInTheDocument();
    expect(screen.getByText("₹100.00")).toBeInTheDocument();
    expect(screen.getByText("Data session")).toBeInTheDocument();
  });

  it("shows an em-dash for rows without a CDR reference and a copy button otherwise (AC #4)", async () => {
    renderTransactions();
    await waitFor(() => expect(screen.getByText("Charge")).toBeInTheDocument());
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Copy CDR reference cdr-abc-123/i }),
    ).toBeInTheDocument();
  });

  it("copies the CDR reference to the clipboard and confirms (AC #4)", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    renderTransactions();
    const copyBtn = await screen.findByRole("button", {
      name: /Copy CDR reference cdr-abc-123/i,
    });
    fireEvent.click(copyBtn);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("cdr-abc-123"));
    await waitFor(() =>
      expect(screen.getByText("Copied!")).toBeInTheDocument(),
    );
  });

  it("disables Next on the last page and Prev on the first page (AC #3)", async () => {
    renderTransactions();
    const next = await screen.findByRole("button", { name: "Next" });
    const prev = screen.getByRole("button", { name: "Previous" });
    await waitFor(() => expect(next).toBeEnabled());
    expect(prev).toBeDisabled();

    fireEvent.click(next);
    await waitFor(() =>
      expect(screen.getByText("Voice call")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await waitFor(() =>
      expect(screen.getByText("Wallet top-up")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("offers no edit or delete affordance (immutable ledger, AC #5)", async () => {
    renderTransactions();
    await waitFor(() => expect(screen.getByText("Charge")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /delete/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /edit/i })).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("shows an error state when the fetch fails", async () => {
    vi.mocked(getTransactions).mockReset();
    vi.mocked(getTransactions).mockRejectedValue(new Error("Network error"));
    renderTransactions();
    await waitFor(() =>
      expect(
        screen.getByText("Failed to load transactions."),
      ).toBeInTheDocument(),
    );
  });
});

describe("Transactions — Refund-eligible filter (Story 3.7)", () => {
  const FAILED_ITEMS: readonly FailedRechargeItem[] = [
    {
      transaction_id: "f1",
      plan_attempted: "Basic Plan",
      amount_paise: 9900,
      failure_reason: "Payment gateway timeout",
      created_at: "2026-06-24T10:00:00Z",
    },
  ];

  beforeEach(() => {
    vi.mocked(getTransactions).mockReset();
    vi.mocked(getTransactions).mockResolvedValue({
      items: [],
      nextCursor: null,
    });
    vi.mocked(getFailedRecharges).mockReset();
    vi.mocked(getFailedRecharges).mockResolvedValue(FAILED_ITEMS);
  });

  it("shows Refund-eligible filter button (AC #1)", async () => {
    renderTransactions();
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Refund-eligible" }),
      ).toBeInTheDocument(),
    );
  });

  it("clicking Refund-eligible calls getFailedRecharges and renders failed rows (AC #1, #2)", async () => {
    renderTransactions();
    const btn = await screen.findByRole("button", { name: "Refund-eligible" });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(screen.getByText("Basic Plan")).toBeInTheDocument(),
    );
    expect(screen.getByText("Payment gateway timeout")).toBeInTheDocument();
    expect(vi.mocked(getFailedRecharges)).toHaveBeenCalled();
  });

  it("shows the refund banner when filter is active (AC #3)", async () => {
    renderTransactions();
    const btn = await screen.findByRole("button", { name: "Refund-eligible" });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(
        screen.getByText(
          /Actual refund processing is handled by the operator's billing team/i,
        ),
      ).toBeInTheDocument(),
    );
  });

  it("does NOT render a Request Refund button anywhere (AC #4)", async () => {
    renderTransactions();
    const btn = await screen.findByRole("button", { name: "Refund-eligible" });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(screen.getByText("Basic Plan")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: /request refund/i }),
    ).toBeNull();
  });

  it("shows empty state when no failed recharges exist (MVP simulated-success, AC #1)", async () => {
    vi.mocked(getFailedRecharges).mockResolvedValue([]);
    renderTransactions();
    const btn = await screen.findByRole("button", { name: "Refund-eligible" });
    fireEvent.click(btn);

    await waitFor(() =>
      expect(
        screen.getByText(/No refund-eligible transactions found/i),
      ).toBeInTheDocument(),
    );
  });
});
