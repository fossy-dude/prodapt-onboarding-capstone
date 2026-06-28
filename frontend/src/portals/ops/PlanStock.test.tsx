/**
 * Tests for PlanStock component (Story 7.2 Task 7).
 */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlanStock, type PlanStockItem } from "./PlanStock";

describe("PlanStock", () => {
  const mockPlans: PlanStockItem[] = [
    {
      plan_id: "plan-1",
      plan_name: "Basic Plan",
      subscriber_count: 150,
      l1m_additions: 25,
      p1m_additions: 20,
      growth_percent: 25,
    },
    {
      plan_id: "plan-2",
      plan_name: "Premium Plan",
      subscriber_count: 300,
      l1m_additions: 60,
      p1m_additions: 30,
      growth_percent: 100,
    },
    {
      plan_id: "plan-3",
      plan_name: "Enterprise Plan",
      subscriber_count: 50,
      l1m_additions: 5,
      p1m_additions: 10,
      growth_percent: -50,
    },
  ];

  it("renders plan stock table with data", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    expect(screen.getByText("Plan Stock")).toBeInTheDocument();
    expect(screen.getByText("L1M Additions")).toBeInTheDocument();
    expect(screen.getByText("Growth vs P1M")).toBeInTheDocument();
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
    expect(rows[1]).toHaveTextContent(/Premium Plan.*300/);
  });

  it("allows sorting by plan name", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    const planNameHeader = screen.getByText("Plan Name");
    fireEvent.click(planNameHeader);

    const rows = screen.getAllByRole("row");
    // After sorting by name ascending, Basic should be first
    expect(rows[1]).toHaveTextContent(/Basic Plan.*150/);
  });

  it("toggles sort direction when clicking same column", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    const subscriberHeader = screen.getByText("Subscribers");
    fireEvent.click(subscriberHeader);

    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent(/Enterprise Plan.*50/);
  });

  it("filters plans by search text on the client", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    fireEvent.change(screen.getByLabelText("Search plans"), {
      target: { value: "premium" },
    });

    expect(screen.getByText("Premium Plan")).toBeInTheDocument();
    expect(screen.queryByText("Basic Plan")).not.toBeInTheDocument();
    expect(screen.queryByText("Enterprise Plan")).not.toBeInTheDocument();
  });

  it("uses a configurable maximum visible row count for the scroll area", () => {
    render(
      <PlanStock plans={mockPlans} isLoading={false} maxVisibleRows={2} />,
    );

    expect(screen.getByLabelText("Scrollable plan stock table")).toHaveStyle({
      maxHeight: "151px",
    });
  });

  it("shows last month additions and growth vs previous month", () => {
    render(<PlanStock plans={mockPlans} isLoading={false} />);

    expect(screen.getByText("60")).toBeInTheDocument();
    expect(screen.getByText("+100.0%")).toBeInTheDocument();
    expect(screen.getByText("-50.0%")).toBeInTheDocument();
  });

  it("shows Null growth when previous month additions are zero", () => {
    render(
      <PlanStock
        plans={[
          {
            plan_id: "plan-new",
            plan_name: "New Plan",
            subscriber_count: 12,
            l1m_additions: 12,
            p1m_additions: 0,
            growth_percent: null,
          },
        ]}
        isLoading={false}
      />,
    );

    expect(screen.getAllByText("12")).toHaveLength(2);
    expect(screen.getByText("Null")).toBeInTheDocument();
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

    render(
      <PlanStock plans={mockPlans} isLoading={false} onRowClick={onRowClick} />,
    );

    const basicRow = screen.getByText("Basic Plan").closest("tr");
    basicRow?.click();

    expect(onRowClick).toHaveBeenCalledWith("plan-1");
  });

  it("supports keyboard navigation for row selection", () => {
    const onRowClick = vi.fn();

    render(
      <PlanStock plans={mockPlans} isLoading={false} onRowClick={onRowClick} />,
    );

    const premiumRow = screen.getByText("Premium Plan").closest("tr");
    premiumRow?.focus();
    if (premiumRow !== null) {
      fireEvent.keyDown(premiumRow, { key: "Enter" });
    }

    expect(onRowClick).toHaveBeenCalledWith("plan-2");
  });
});
