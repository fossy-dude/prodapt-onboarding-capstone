/**
 * PlanStock component - displays plan adoption metrics (Story 7.2 Task 4).
 * Shows a table of plans with subscriber counts, sortable by column.
 */

import { useState } from "react";

interface PlanStockItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly subscriber_count: number;
}

interface PlanStockProps {
  readonly plans: PlanStockItem[];
  readonly isLoading: boolean;
  readonly onRowClick?: (planId: string) => void;
}

type SortField = "plan_name" | "subscriber_count";
type SortDirection = "asc" | "desc";

function PlanStock({ plans, isLoading, onRowClick }: PlanStockProps) {
  const [sortField, setSortField] = useState<SortField>("subscriber_count");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");

  // Handle sorting
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      // Toggle direction
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      // New field, default to descending for subscriber_count, ascending for name
      setSortField(field);
      setSortDirection(field === "subscriber_count" ? "desc" : "asc");
    }
  };

  // Sort plans
  const sortedPlans = [...plans].sort((a, b) => {
    const aVal = a[sortField];
    const bVal = b[sortField];

    if (sortDirection === "asc") {
      return aVal > bVal ? 1 : -1;
    } else {
      return aVal < bVal ? 1 : -1;
    }
  });

  // Render sort indicator
  const SortIndicator = ({ field }: { readonly field: SortField }) => {
    if (sortField !== field) return null;
    return (
      <span className="ml-1 text-neutral-500">
        {sortDirection === "asc" ? "↑" : "↓"}
      </span>
    );
  };

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-neutral-900">
          Plan Stock
        </h2>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded bg-neutral-200"
            />
          ))}
        </div>
      </div>
    );
  }

  // Empty state
  if (plans.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-neutral-900">
          Plan Stock
        </h2>
        <p className="text-sm text-neutral-500">No plans found.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6">
      <h2 className="mb-4 text-lg font-semibold text-neutral-900">
        Plan Stock
      </h2>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-neutral-200">
          <thead className="bg-neutral-50">
            <tr>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("plan_name")}
              >
                Plan Name
                <SortIndicator field="plan_name" />
              </th>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("subscriber_count")}
              >
                Subscribers
                <SortIndicator field="subscriber_count" />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200">
            {sortedPlans.map((plan) => (
              <tr
                key={plan.plan_id}
                className={`transition-colors hover:bg-neutral-50 ${
                  onRowClick ? "cursor-pointer" : ""
                }`}
                onClick={() => onRowClick?.(plan.plan_id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && onRowClick) {
                    onRowClick(plan.plan_id);
                  }
                }}
                role={onRowClick ? "button" : "row"}
                tabIndex={onRowClick ? 0 : undefined}
              >
                <td className="whitespace-nowrap px-4 py-4 text-sm font-medium text-neutral-900">
                  {plan.plan_name}
                </td>
                <td className="whitespace-nowrap px-4 py-4 text-right text-sm text-neutral-500">
                  {plan.subscriber_count.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export type { PlanStockItem };
export { PlanStock };
