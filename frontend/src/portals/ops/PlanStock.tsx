/**
 * PlanStock component - displays plan adoption metrics (Story 7.2 Task 4).
 * Shows a table of plans with subscriber counts, sortable by column.
 */

import { useDeferredValue, useState } from "react";

interface PlanStockItem {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly subscriber_count: number;
  readonly l1m_additions?: number | null;
  readonly p1m_additions?: number | null;
  readonly growth_percent?: number | null;
}

interface PlanStockProps {
  readonly plans: PlanStockItem[];
  readonly isLoading: boolean;
  readonly maxVisibleRows?: number;
  readonly onRowClick?: (planId: string) => void;
}

type SortField = "plan_name" | "subscriber_count" | "l1m_additions" | "growth";
type SortDirection = "asc" | "desc";

const DEFAULT_MAX_VISIBLE_ROWS = 20;
const HEADER_HEIGHT_PX = 45;
const ROW_HEIGHT_PX = 53;

function getGrowthPercent(plan: PlanStockItem): number | null {
  if (plan.growth_percent !== undefined) return plan.growth_percent;
  if (plan.l1m_additions === null || plan.l1m_additions === undefined)
    return null;
  if (plan.p1m_additions === null || plan.p1m_additions === undefined)
    return null;
  if (plan.p1m_additions === 0) return plan.l1m_additions === 0 ? 0 : null;
  return ((plan.l1m_additions - plan.p1m_additions) / plan.p1m_additions) * 100;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : value.toLocaleString();
}

function formatGrowth(value: number | null): string {
  if (value === null) return "Null";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function getSortValue(
  plan: PlanStockItem,
  field: SortField,
): string | number | null {
  if (field === "growth") return getGrowthPercent(plan);
  if (field === "l1m_additions") return plan.l1m_additions ?? null;
  return plan[field];
}

function SortIndicator({
  field,
  sortField,
  sortDirection,
}: {
  readonly field: SortField;
  readonly sortField: SortField;
  readonly sortDirection: SortDirection;
}) {
  if (sortField !== field) return null;
  return (
    <span className="ml-1 text-neutral-500">
      {sortDirection === "asc" ? "↑" : "↓"}
    </span>
  );
}

function PlanStock({
  plans,
  isLoading,
  maxVisibleRows = DEFAULT_MAX_VISIBLE_ROWS,
  onRowClick,
}: PlanStockProps) {
  const [sortField, setSortField] = useState<SortField>("subscriber_count");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);

  // Handle sorting
  const handleSort = (field: SortField) => {
    if (sortField === field) {
      // Toggle direction
      setSortDirection(sortDirection === "asc" ? "desc" : "asc");
    } else {
      // New field, default to descending for numeric metrics, ascending for name
      setSortField(field);
      setSortDirection(field === "plan_name" ? "asc" : "desc");
    }
  };

  const normalizedSearchQuery = deferredSearchQuery.trim().toLocaleLowerCase();
  const filteredPlans =
    normalizedSearchQuery.length === 0
      ? plans
      : plans.filter(
          (plan) =>
            plan.plan_name
              .toLocaleLowerCase()
              .includes(normalizedSearchQuery) ||
            plan.plan_id.toLocaleLowerCase().includes(normalizedSearchQuery),
        );

  const sortedPlans = [...filteredPlans].sort((a, b) => {
    const aVal = getSortValue(a, sortField);
    const bVal = getSortValue(b, sortField);

    if (aVal === null && bVal === null) return 0;
    if (aVal === null) return 1;
    if (bVal === null) return -1;

    if (sortDirection === "asc") {
      return aVal > bVal ? 1 : -1;
    }

    return aVal < bVal ? 1 : -1;
  });
  const tableMaxHeightPx =
    HEADER_HEIGHT_PX + ROW_HEIGHT_PX * Math.max(1, maxVisibleRows);

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
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-neutral-900">Plan Stock</h2>
          <p className="mt-1 text-xs text-neutral-500">
            Showing {sortedPlans.length.toLocaleString()} of{" "}
            {plans.length.toLocaleString()} plans.
          </p>
        </div>
        <label className="flex flex-col gap-1 text-xs font-medium text-neutral-600 sm:w-72">
          Search plans
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by plan name or ID"
            className="rounded-lg border border-neutral-300 px-3 py-2 text-sm font-normal text-neutral-900 placeholder:text-neutral-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100"
          />
        </label>
      </div>
      <div
        aria-label="Scrollable plan stock table"
        className="overflow-auto"
        style={{ maxHeight: `${tableMaxHeightPx}px` }}
      >
        <table className="min-w-full divide-y divide-neutral-200">
          <thead className="sticky top-0 z-10 bg-neutral-50">
            <tr>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("plan_name")}
              >
                Plan Name
                <SortIndicator
                  field="plan_name"
                  sortField={sortField}
                  sortDirection={sortDirection}
                />
              </th>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("subscriber_count")}
              >
                Subscribers
                <SortIndicator
                  field="subscriber_count"
                  sortField={sortField}
                  sortDirection={sortDirection}
                />
              </th>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("l1m_additions")}
              >
                L1M Additions
                <SortIndicator
                  field="l1m_additions"
                  sortField={sortField}
                  sortDirection={sortDirection}
                />
              </th>
              <th
                scope="col"
                className="cursor-pointer px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-neutral-700 hover:bg-neutral-100"
                onClick={() => handleSort("growth")}
              >
                Growth vs P1M
                <SortIndicator
                  field="growth"
                  sortField={sortField}
                  sortDirection={sortDirection}
                />
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-200">
            {sortedPlans.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  className="px-4 py-8 text-center text-sm text-neutral-500"
                >
                  No plans match the search.
                </td>
              </tr>
            )}
            {sortedPlans.map((plan) => {
              const growthPercent = getGrowthPercent(plan);
              const isPositiveGrowth =
                growthPercent !== null && growthPercent > 0;
              const isNegativeGrowth =
                growthPercent !== null && growthPercent < 0;

              return (
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
                  <td className="whitespace-nowrap px-4 py-4 text-right text-sm text-neutral-500">
                    {formatNumber(plan.l1m_additions)}
                  </td>
                  <td
                    className={`whitespace-nowrap px-4 py-4 text-right text-sm font-medium ${
                      isPositiveGrowth
                        ? "text-emerald-600"
                        : isNegativeGrowth
                          ? "text-red-600"
                          : "text-neutral-500"
                    }`}
                  >
                    {formatGrowth(growthPercent)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export type { PlanStockItem };
export { PlanStock };
