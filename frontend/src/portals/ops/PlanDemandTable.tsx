/**
 * PlanDemandTable - sortable table of per-plan 30/60/90-day demand forecasts
 * with inline sparkline trend charts (Story 7.4 Task 6).
 */

import { useState } from "react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";

interface PlanDemandItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly predicted_uptake_30d: number;
  readonly predicted_uptake_60d: number;
  readonly predicted_uptake_90d: number;
  readonly uptake_trend_90d: readonly number[];
}

interface PlanDemandTableProps {
  readonly items: readonly PlanDemandItem[];
  readonly isLoading: boolean;
}

type SortField =
  | "plan_name"
  | "predicted_uptake_30d"
  | "predicted_uptake_60d"
  | "predicted_uptake_90d";
type SortDirection = "asc" | "desc";

function trendColor(trend: readonly number[]): string {
  if (trend.length < 7) return "#6b7280";
  const first7 = trend.slice(0, 7).reduce((a, b) => a + b, 0) / 7;
  const last7 = trend.slice(-7).reduce((a, b) => a + b, 0) / 7;
  return last7 >= first7 ? "#16a34a" : "#dc2626";
}

function Sparkline({ data }: { readonly data: readonly number[] }) {
  const color = trendColor(data);
  const chartData = data.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width={80} height={36}>
      <AreaChart
        data={chartData}
        margin={{ top: 2, right: 0, bottom: 2, left: 0 }}
      >
        <Area
          type="monotone"
          dataKey="v"
          stroke={color}
          fill={color}
          fillOpacity={0.15}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

const SortIndicator = ({
  field,
  active,
  direction,
}: {
  readonly field: SortField;
  readonly active: SortField;
  readonly direction: SortDirection;
}) => {
  if (field !== active) return null;
  return (
    <span className="ml-1 text-neutral-400">
      {direction === "asc" ? "↑" : "↓"}
    </span>
  );
};

function PlanDemandTable({ items, isLoading }: PlanDemandTableProps) {
  const [sortField, setSortField] = useState<SortField>("predicted_uptake_90d");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDirection(field === "plan_name" ? "asc" : "desc");
    }
  };

  const sorted = [...items].sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];
    const cmp =
      typeof aVal === "string"
        ? aVal.localeCompare(bVal as string)
        : (aVal as number) - (bVal as number);
    return sortDirection === "asc" ? cmp : -cmp;
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded bg-neutral-200" />
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <p className="text-sm text-neutral-500">No forecast data available.</p>
    );
  }

  const thClass =
    "cursor-pointer px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100";
  const thRight = `${thClass} text-right`;

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full divide-y divide-neutral-200">
        <thead className="bg-neutral-50">
          <tr>
            <th
              scope="col"
              className={thClass}
              onClick={() => handleSort("plan_name")}
            >
              Plan Name
              <SortIndicator
                field="plan_name"
                active={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              scope="col"
              className={thRight}
              onClick={() => handleSort("predicted_uptake_30d")}
            >
              30-day
              <SortIndicator
                field="predicted_uptake_30d"
                active={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              scope="col"
              className={thRight}
              onClick={() => handleSort("predicted_uptake_60d")}
            >
              60-day
              <SortIndicator
                field="predicted_uptake_60d"
                active={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              scope="col"
              className={thRight}
              onClick={() => handleSort("predicted_uptake_90d")}
            >
              90-day
              <SortIndicator
                field="predicted_uptake_90d"
                active={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              scope="col"
              className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700"
            >
              Trend
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-neutral-200 bg-white">
          {sorted.map((item) => (
            <tr key={item.plan_id} className="hover:bg-neutral-50">
              <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-neutral-900">
                {item.plan_name}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right text-sm text-neutral-600">
                {item.predicted_uptake_30d.toLocaleString()}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right text-sm text-neutral-600">
                {item.predicted_uptake_60d.toLocaleString()}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-right text-sm font-semibold text-neutral-900">
                {item.predicted_uptake_90d.toLocaleString()}
              </td>
              <td className="px-4 py-1">
                {item.uptake_trend_90d.length > 0 ? (
                  <Sparkline data={item.uptake_trend_90d} />
                ) : (
                  <span className="text-xs text-neutral-400">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type { PlanDemandItem };
export { PlanDemandTable };
