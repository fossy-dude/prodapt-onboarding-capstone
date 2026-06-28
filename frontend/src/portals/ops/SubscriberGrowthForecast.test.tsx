/**
 * Tests for SubscriberGrowthForecast container (Story 7.3 Task 8).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SubscriberGrowthForecast } from "./SubscriberGrowthForecast";

// Mock the forecast hook; the container's loading/error/success branches are
// driven entirely by this return value.
vi.mock("./hooks", () => ({
  useSubscriberGrowthForecast: vi.fn(),
}));

const successData = {
  forecast_type: "subscriber_growth",
  model_version: "gradient_boosting_v1",
  trained_at: "2026-06-26T10:00:00+00:00",
  cache_expires_at: "2026-06-27T10:00:00+00:00",
  horizon_days: 90,
  from_cache: true,
  metrics: {
    mape_activations: 8.2,
    mape_churn: 12.5,
    passed_mape_threshold: true,
    holdout_days: 30,
  },
  forecasts: [
    {
      date: "2026-07-01",
      predicted_activations: 150,
      predicted_churn: 30,
      lower_bound_activations: 140,
      upper_bound_activations: 160,
      lower_bound_churn: 25,
      upper_bound_churn: 35,
    },
  ],
};

describe("SubscriberGrowthForecast", () => {
  it("renders the chart and model metadata on success", async () => {
    const { useSubscriberGrowthForecast } = await import("./hooks");
    (useSubscriberGrowthForecast as ReturnType<typeof vi.fn>).mockReturnValue({
      data: successData,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<SubscriberGrowthForecast />);

    expect(
      screen.getByText("Subscriber Growth Forecast (90-Day Projection)"),
    ).toBeInTheDocument();
    expect(screen.getByText(/gradient_boosting_v1/)).toBeInTheDocument();
    expect(screen.getByText(/Served from cache/)).toBeInTheDocument();
    expect(screen.getByText(/activations 8.2%/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Refresh Forecast" }),
    ).toBeInTheDocument();
  });

  it("renders a limited-data warning above the forecast", async () => {
    const { useSubscriberGrowthForecast } = await import("./hooks");
    (useSubscriberGrowthForecast as ReturnType<typeof vi.fn>).mockReturnValue({
      data: {
        ...successData,
        warning: {
          code: "INSUFFICIENT_FORECAST_DATA",
          message:
            "Forecast is based on limited data: 2 data points over the last 90 days.",
          data_points: 2,
          window_days: 90,
        },
      },
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    render(<SubscriberGrowthForecast />);

    expect(screen.getByText("Limited data forecast.")).toBeInTheDocument();
    expect(
      screen.getByText(/2 data points over the last 90 days/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Subscriber Growth Forecast (90-Day Projection)"),
    ).toBeInTheDocument();
  });

  it("renders the loading state", async () => {
    const { useSubscriberGrowthForecast } = await import("./hooks");
    (useSubscriberGrowthForecast as ReturnType<typeof vi.fn>).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
      refetch: vi.fn(),
    });

    render(<SubscriberGrowthForecast />);

    expect(screen.getByText(/Loading forecast/)).toBeInTheDocument();
  });

  it("renders the error state with a retry control", async () => {
    const { useSubscriberGrowthForecast } = await import("./hooks");
    (useSubscriberGrowthForecast as ReturnType<typeof vi.fn>).mockReturnValue({
      data: undefined,
      isLoading: false,
      error: new Error("boom"),
      refetch: vi.fn(),
    });

    render(<SubscriberGrowthForecast />);

    expect(
      screen.getByText(/Failed to load subscriber growth forecast/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
