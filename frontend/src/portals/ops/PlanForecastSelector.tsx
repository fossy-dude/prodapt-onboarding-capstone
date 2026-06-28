import { useDeferredValue, useState } from "react";

interface PlanForecastSelectorPlan {
  readonly plan_id: string;
  readonly plan_name: string;
  readonly subscriber_count: number;
}

interface PlanForecastSelectorProps {
  readonly plans: readonly PlanForecastSelectorPlan[];
  readonly isLoading: boolean;
  readonly selectedPlanIds: readonly string[];
  readonly onTogglePlan: (planId: string) => void;
  readonly onClear: () => void;
}

const MAX_VISIBLE_PLANS = 12;

function PlanForecastSelector({
  plans,
  isLoading,
  selectedPlanIds,
  onTogglePlan,
  onClear,
}: PlanForecastSelectorProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const selectedPlanIdSet = new Set(selectedPlanIds);
  const normalizedSearchQuery = deferredSearchQuery.trim().toLocaleLowerCase();
  const filteredPlans = plans
    .filter((plan) => {
      if (normalizedSearchQuery.length === 0) return true;
      return (
        plan.plan_name.toLocaleLowerCase().includes(normalizedSearchQuery) ||
        plan.plan_id.toLocaleLowerCase().includes(normalizedSearchQuery)
      );
    })
    .sort((a, b) => a.plan_name.localeCompare(b.plan_name));
  const visiblePlans = filteredPlans.slice(0, MAX_VISIBLE_PLANS);

  return (
    <section className="mb-5 rounded-lg border border-neutral-200 bg-neutral-50 p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <label className="flex flex-1 flex-col gap-1 text-xs font-medium text-neutral-600">
          Search and select plans
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by plan name or ID"
            className="rounded-lg border border-neutral-300 bg-white px-3 py-2 text-sm font-normal text-neutral-900 placeholder:text-neutral-400 focus:border-brand-600 focus:outline-none focus:ring-2 focus:ring-brand-100"
          />
        </label>
        <div className="flex items-center gap-3 text-xs text-neutral-500">
          <span>{selectedPlanIds.length.toLocaleString()} selected</span>
          <button
            type="button"
            onClick={onClear}
            disabled={selectedPlanIds.length === 0}
            className="rounded border border-neutral-300 bg-white px-3 py-2 font-medium text-neutral-600 hover:bg-neutral-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="mt-3 rounded-md border border-neutral-200 bg-white">
        {isLoading ? (
          <div className="space-y-2 p-3">
            {[1, 2, 3].map((item) => (
              <div
                key={item}
                className="h-8 animate-pulse rounded bg-neutral-200"
              />
            ))}
          </div>
        ) : (
          <div className="max-h-72 divide-y divide-neutral-100 overflow-auto">
            {visiblePlans.length === 0 && (
              <p className="px-3 py-4 text-sm text-neutral-500">
                No plans match the search.
              </p>
            )}
            {visiblePlans.map((plan) => (
              <label
                key={plan.plan_id}
                className="flex cursor-pointer items-center justify-between gap-3 px-3 py-2 text-sm hover:bg-neutral-50"
              >
                <span className="flex min-w-0 items-center gap-3">
                  <input
                    type="checkbox"
                    checked={selectedPlanIdSet.has(plan.plan_id)}
                    onChange={() => onTogglePlan(plan.plan_id)}
                    className="h-4 w-4 rounded border-neutral-300 text-brand-600 focus:ring-brand-500"
                  />
                  <span className="truncate font-medium text-neutral-900">
                    {plan.plan_name}
                  </span>
                </span>
                <span className="shrink-0 text-xs text-neutral-500">
                  {plan.subscriber_count.toLocaleString()} subscribers
                </span>
              </label>
            ))}
          </div>
        )}
      </div>

      {filteredPlans.length > visiblePlans.length && (
        <p className="mt-2 text-xs text-neutral-500">
          Showing first {MAX_VISIBLE_PLANS.toLocaleString()} matches. Refine
          search to narrow the list.
        </p>
      )}
    </section>
  );
}

export { PlanForecastSelector };
export type { PlanForecastSelectorPlan };
