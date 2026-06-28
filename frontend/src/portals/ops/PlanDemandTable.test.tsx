/**
 * Tests for PlanDemandTable component (Story 7.4 Task 9).
 */

import type * as Recharts from "recharts";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PlanDemandTable } from "./PlanDemandTable";

vi.mock("recharts", async () => {
  const actual = await vi.importActual<typeof Recharts>("recharts");
  return {
    ...actual,
    ResponsiveContainer: ({
      children,
    }: {
      readonly children: React.ReactNode;
    }) => <div data-testid="responsive-container">{children}</div>,
  };
});

const MOCK_ITEMS = [
  {
    plan_id: "plan-a",
    plan_name: "Alpha Plan",
    predicted_uptake_30d: 100,
    predicted_uptake_60d: 200,
    predicted_uptake_90d: 300,
    uptake_trend_90d: Array.from({ length: 90 }, (_, i) => i + 1),
  },
  {
    plan_id: "plan-b",
    plan_name: "Beta Plan",
    predicted_uptake_30d: 50,
    predicted_uptake_60d: 80,
    predicted_uptake_90d: 120,
    uptake_trend_90d: Array.from({ length: 90 }, (_, i) => 90 - i),
  },
];

describe("PlanDemandTable", () => {
  it("renders plan names and uptake columns", () => {
    render(<PlanDemandTable items={MOCK_ITEMS} isLoading={false} />);

    expect(screen.getByText("Alpha Plan")).toBeInTheDocument();
    expect(screen.getByText("Beta Plan")).toBeInTheDocument();
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("shows loading skeleton when isLoading is true", () => {
    render(<PlanDemandTable items={[]} isLoading={true} />);

    const skeletons = document.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows empty state when no items", () => {
    render(<PlanDemandTable items={[]} isLoading={false} />);

    expect(screen.getByText(/No forecast data/i)).toBeInTheDocument();
  });

  it("sorts by plan_name ascending on click", async () => {
    const user = userEvent.setup();
    render(<PlanDemandTable items={MOCK_ITEMS} isLoading={false} />);

    await user.click(screen.getByText("Plan Name"));

    const rows = screen.getAllByRole("row");
    // header + 2 data rows
    expect(rows).toHaveLength(3);
    expect(rows[1]).toHaveTextContent("Alpha Plan");
    expect(rows[2]).toHaveTextContent("Beta Plan");
  });

  it("sorts by 90-day uptake descending by default", () => {
    render(<PlanDemandTable items={MOCK_ITEMS} isLoading={false} />);

    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("Alpha Plan");
    expect(rows[2]).toHaveTextContent("Beta Plan");
  });

  it("renders sparkline container per row", () => {
    render(<PlanDemandTable items={MOCK_ITEMS} isLoading={false} />);

    const sparklines = screen.getAllByTestId("responsive-container");
    expect(sparklines).toHaveLength(MOCK_ITEMS.length);
  });

  it("shows dash when uptake_trend_90d is empty", () => {
    const mockItem = MOCK_ITEMS[0]!;
    const itemWithNoTrend = [
      {
        plan_id: mockItem.plan_id,
        plan_name: mockItem.plan_name,
        predicted_uptake_30d: mockItem.predicted_uptake_30d,
        predicted_uptake_60d: mockItem.predicted_uptake_60d,
        predicted_uptake_90d: mockItem.predicted_uptake_90d,
        uptake_trend_90d: [] as readonly number[],
      },
    ];
    render(<PlanDemandTable items={itemWithNoTrend} isLoading={false} />);

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
