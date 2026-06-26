/**
 * Tests for PlanStock component (Story 7.2 Task 7).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlanStock, type PlanStockItem } from "./PlanStock";

describe("PlanStock", () => {
  const mockPlans: PlanStockItem[] = [
    {
      plan_id: "plan-1",
      plan_name: "Basic Plan",
      subscriber_count: 150,
    },
    {
      plan_id: "plan-2",
      plan_name: "Premium Plan",
      subscriber_count: 300,
    },
    {
      plan_id: "plan-3",
      plan_name: "Enterprise Plan",
      subscriber_count: 50,
    },
  ];

  it("renders plan stock table with data", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    expect(screen.getByText("Plan Stock")).toBeInTheDocument();
    expect(screen.getByText("Basic Plan")).toBeInTheDocument();
    expect(screen.getByText("Premium Plan")).toBeInTheDocument();
    expect(screen.getByText("Enterprise Plan")).toBeInTheDocument();
  });

  it("displays subscriber counts with proper formatting", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    expect(screen.getByText("300")).toBeInTheDocument(); // Premium
    expect(screen.getByText("150")).toBeInTheDocument(); // Basic
    expect(screen.getByText("50")).toBeInTheDocument(); // Enterprise
  });

  it("sorts plans by subscriber count descending by default", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    const rows = screen.getAllByRole("row");
    // First data row should be Premium (300 subscribers)
    expect(rows[1]).toHaveTextContent("Premium Plan300");
  });

  it("allows sorting by plan name", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    const planNameHeader = screen.getByText("Plan Name");
    planNameHeader.click();

    const rows = screen.getAllByRole("row");
    // After sorting by name ascending, Basic should be first
    expect(rows[1]).toHaveTextContent("Basic Plan150");
  });

  it("toggles sort direction when clicking same column", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    const subscriberHeader = screen.getByText("Subscribers");
    subscriberHeader.click(); // First click - should already be desc

    const rows = screen.getAllByRole("row");
    // Still descending (Premium first with 300)
    expect(rows[1]).toHaveTextContent("Premium Plan300");
  });

  it("shows loading skeleton while data is loading", () => {
    render(<PlanStock plans={[]} isLoading={true} />);

    expect(screen.getByText("Plan Stock")).toBeInTheDocument();
    // Should show skeleton elements (no plan names)
    expect(screen.queryByText("Basic Plan")).not.toBeInTheDocument();
  });

  it("shows empty state when no plans available", () => {
    render(<PlanStock plans={[]} isLoading={false} />);

    expect(screen.getByText("No plans found.")).toBeInTheDocument();
  });

  it("calls onRowClick when a plan row is clicked", () => {
    const onRowClick = vi.fn();

    render(<PlanStock plans={mockPlans} isLoading={false} onRowClick={onRowClick} />);

    const basicRow = screen.getByText("Basic Plan").closest("tr");
    basicRow?.click();

    expect(onRowClick).toHaveBeenCalledWith("plan-1");
  });

  it("supports keyboard navigation for row selection", () => {
    const onRowClick = vi.fn();

    render(<PlanStock plans={mockPlans} isLoading={false} onRowClick={onRowClick} />);

    const premiumRow = screen.getByText("Premium Plan").closest("tr");
    premiumRow?.focus();
    premiumRow?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));

    expect(onRowClick).toHaveBeenCalledWith("plan-2");
  });
});
