/**
 * Tests for SubscriberGrowthChart component (Story 7.3 Task 8).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SubscriberGrowthChart } from "./SubscriberGrowthChart";
import type { SubscriberGrowthForecastPoint } from "./hooks";

const mockPoints: readonly SubscriberGrowthForecastPoint[] = [
  {
    date: "2026-07-01",
    predicted_activations: 150,
    predicted_churn: 30,
    lower_bound_activations: 140,
    upper_bound_activations: 160,
    lower_bound_churn: 25,
    upper_bound_churn: 35,
  },
  {
    date: "2026-07-02",
    predicted_activations: 155,
    predicted_churn: 31,
    lower_bound_activations: 145,
    upper_bound_activations: 165,
    lower_bound_churn: 26,
    upper_bound_churn: 36,
  },
];

describe("SubscriberGrowthChart", () => {
  it("renders the chart heading when forecast data is present", () => {
    render(<SubscriberGrowthChart data={mockPoints} />);

    expect(
      screen.getByText("Subscriber Growth Forecast (90-Day Projection)"),
    ).toBeInTheDocument();
  });

  it("mounts the Recharts container when forecast data is present", () => {
    const { container } = render(<SubscriberGrowthChart data={mockPoints} />);

    // jsdom does not compute layout, so ResponsiveContainer receives no size and
    // its Recharts children do not paint; the reliable mount signal is the
    // responsive-container element itself. The empty-state must NOT show.
    expect(container.querySelector(".recharts-responsive-container")).not.toBeNull();
    expect(screen.queryByText(/No forecast data available/)).toBeNull();
  });

  it("renders the empty-state message when there is no forecast data", () => {
    render(<SubscriberGrowthChart data={[]} />);

    expect(screen.getByText(/No forecast data available/)).toBeInTheDocument();
  });
});
