/**
 * SubscriberGrowthChart - 90-day subscriber activation/churn projection with
 * 95% confidence-interval bands (Story 7.3 Task 6, AC #4).
 *
 * Renders predicted activations (blue) and predicted churn (red) as lines, each
 * wrapped in a shaded Recharts Area band drawn between its lower/upper bounds.
 * Recharts renders an array-valued dataKey ([lower, upper]) as a band between the
 * two values, which is how the CI band is produced.
 */

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { SubscriberGrowthForecastPoint } from "./hooks";

/** Row shape fed to Recharts: prediction values plus CI band pairs. */
interface ChartRow {
  readonly date: string;
  readonly predicted_activations: number;
  readonly predicted_churn: number;
  readonly activations_ci: readonly [number, number];
  readonly churn_ci: readonly [number, number];
}

interface SubscriberGrowthChartProps {
  readonly data: readonly SubscriberGrowthForecastPoint[];
}

const ACTIVATIONS_COLOR = "#3b82f6"; // blue
const CHURN_COLOR = "#ef4444"; // red

/** Compact, timezone-stable x-axis tick (avoids UTC/local-day off-by-one). */
function formatTick(value: unknown): string {
  return typeof value === "string" ? value.slice(5) : String(value);
}

function SubscriberGrowthChart({ data }: SubscriberGrowthChartProps) {
  if (data.length === 0) {
    return (
      <p className="text-sm text-neutral-500">
        No forecast data available. A 90-day projection will appear here once the
        model has been trained.
      </p>
    );
  }

  const chartData: readonly ChartRow[] = data.map((point) => ({
    date: point.date,
    predicted_activations: point.predicted_activations,
    predicted_churn: point.predicted_churn,
    activations_ci: [
      point.lower_bound_activations,
      point.upper_bound_activations,
    ] as const,
    churn_ci: [point.lower_bound_churn, point.upper_bound_churn] as const,
  }));

  return (
    <div>
      <h3 className="mb-1 text-lg font-semibold text-neutral-900">
        Subscriber Growth Forecast (90-Day Projection)
      </h3>
      <p className="mb-4 text-xs text-neutral-500">
        Daily predicted activations and churn with 95% confidence bands.
      </p>

      <ResponsiveContainer width="100%" height={320}>
        <ComposedChart
          data={[...chartData]}
          margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis
            dataKey="date"
            tickFormatter={formatTick}
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <YAxis tick={{ fontSize: 11, fill: "#6b7280" }} />
          <Tooltip />
          <Legend />
          <Area
            type="monotone"
            dataKey="activations_ci"
            name="Activations 95% CI"
            stroke="none"
            fill={ACTIVATIONS_COLOR}
            fillOpacity={0.15}
            legendType="none"
          />
          <Line
            type="monotone"
            dataKey="predicted_activations"
            name="Activations"
            stroke={ACTIVATIONS_COLOR}
            strokeWidth={2}
            dot={false}
          />
          <Area
            type="monotone"
            dataKey="churn_ci"
            name="Churn 95% CI"
            stroke="none"
            fill={CHURN_COLOR}
            fillOpacity={0.15}
            legendType="none"
          />
          <Line
            type="monotone"
            dataKey="predicted_churn"
            name="Churn"
            stroke={CHURN_COLOR}
            strokeWidth={2}
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export { SubscriberGrowthChart };
export type { SubscriberGrowthChartProps };
