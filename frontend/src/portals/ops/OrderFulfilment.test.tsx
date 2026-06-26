/**
 * Tests for OrderFulfilment component (Story 7.2 Task 7).
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { OrderFulfilment, type OrderItem } from "./OrderFulfilment";

describe("OrderFulfilment", () => {
  const mockCounts = {
    CREATED: 10,
    KYC_PENDING: 5,
    KYC_VERIFIED: 3,
    ACTIVATED: 2,
  };

  const mockOrders: OrderItem[] = [
    {
      order_id: "order-1",
      subscriber_id: "sub-1-aaa-bbbb",
      created_at: "2026-01-01T10:00:00Z",
      updated_at: "2026-01-01T10:05:00Z",
      status: "CREATED",
    },
    {
      order_id: "order-2",
      subscriber_id: "sub-2-ccc-dddd",
      created_at: "2026-01-01T11:00:00Z",
      updated_at: "2026-01-01T11:05:00Z",
      status: "CREATED",
    },
  ];

  it("renders status board with counts", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    expect(screen.getByText("Order Fulfilment")).toBeInTheDocument();
    expect(screen.getByText("CREATED")).toBeInTheDocument();
    expect(screen.getByText("KYC PENDING")).toBeInTheDocument();
    expect(screen.getByText("KYC VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("ACTIVATED")).toBeInTheDocument();
  });

  it("displays correct counts for each status", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    expect(screen.getByText("10")).toBeInTheDocument(); // CREATED
    expect(screen.getByText("5")).toBeInTheDocument(); // KYC_PENDING
    expect(screen.getByText("3")).toBeInTheDocument(); // KYC_VERIFIED
    expect(screen.getByText("2")).toBeInTheDocument(); // ACTIVATED
  });

  it("shows loading skeleton while counts are loading", () => {
    render(
      <OrderFulfilment
        counts={{}}
        countsIsLoading={true}
        orders={[]}
        ordersIsLoading={false}
      />
    );

    expect(screen.getByText("Order Fulfilment")).toBeInTheDocument();
    // Should show skeleton elements
    expect(screen.queryByText("CREATED")).not.toBeInTheDocument();
  });

  it("filters orders when status card is clicked", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.click();

    expect(screen.getByText(/CREATED Orders \(2\)/)).toBeInTheDocument();
  });

  it("toggles status selection when clicking same card", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.click(); // Select
    createdCard?.click(); // Deselect

    expect(screen.queryByText(/CREATED Orders/)).not.toBeInTheDocument();
  });

  it("displays order list when status is selected", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.click();

    expect(screen.getByText("Order ID")).toBeInTheDocument();
    expect(screen.getByText("Subscriber")).toBeInTheDocument();
    expect(screen.getByText("Created")).toBeInTheDocument();
    expect(screen.getByText("Updated")).toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
  });

  it("masks subscriber IDs to show last 4 digits only (PII hygiene)", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.click();

    expect(screen.getByText("XXXX-bbbb")).toBeInTheDocument();
    expect(screen.getByText("XXXX-dddd")).toBeInTheDocument();
  });

  it("shows empty state when no orders for selected status", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={[]}
        ordersIsLoading={false}
      />
    );

    const activatedCard = screen.getByText("ACTIVATED").closest("div");
    activatedCard?.click();

    expect(screen.getByText("No orders in this status.")).toBeInTheDocument();
  });

  it("shows pagination when orders exceed page size", () => {
    // Create 25 orders to test pagination (PAGE_SIZE = 20)
    const largeOrderList: OrderItem[] = Array.from({ length: 25 }, (_, i) => ({
      order_id: `order-${i}`,
      subscriber_id: `sub-${i}`,
      created_at: "2026-01-01T10:00:00Z",
      updated_at: "2026-01-01T10:05:00Z",
      status: "CREATED",
    }));

    const largeCounts = { ...mockCounts, CREATED: 25 };

    render(
      <OrderFulfilment
        counts={largeCounts}
        countsIsLoading={false}
        orders={largeOrderList}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.click();

    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Next")).toBeInTheDocument();
  });

  it("supports keyboard navigation for status selection", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
      />
    );

    const createdCard = screen.getByText("CREATED").closest("div");
    createdCard?.focus();
    createdCard?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    expect(screen.getByText(/CREATED Orders/)).toBeInTheDocument();
  });

  it("displays filtered indicator when plan is selected", () => {
    render(
      <OrderFulfilment
        counts={mockCounts}
        countsIsLoading={false}
        orders={mockOrders}
        ordersIsLoading={false}
        selectedPlanId="plan-123"
      />
    );

    expect(screen.getByText("(Filtered by Plan)")).toBeInTheDocument();
  });
});
