import { useMemo, useState } from "react";

import { useActivePlan } from "../../hooks/useActivePlan";
import { usePlans } from "../../hooks/usePlans";
import type { PlanCatalogueItem } from "../../lib/api";
import { PlanCard } from "./PlanCard";

type ValidityFilter = "all" | 28 | 56 | 84;
type SortKey = "price-asc" | "price-desc" | "data-desc";

interface Option<T extends string | number> {
  readonly value: T;
  readonly label: string;
}

const VALIDITY_OPTIONS: readonly Option<ValidityFilter>[] = [
  { value: "all", label: "All validity" },
  { value: 28, label: "28 days" },
  { value: 56, label: "56 days" },
  { value: 84, label: "84 days" },
];

const SORT_OPTIONS: readonly Option<SortKey>[] = [
  { value: "price-asc", label: "Price: Low to High" },
  { value: "price-desc", label: "Price: High to Low" },
  { value: "data-desc", label: "Data: High to Low" },
];

/** Parse a select string back into the discriminated ValidityFilter (no casts). */
function toValidity(v: string): ValidityFilter {
  if (v === "all") {
    return "all";
  }
  if (v === "28") {
    return 28;
  }
  if (v === "56") {
    return 56;
  }
  return 84;
}

/** Parse a select string back into SortKey, defaulting safely (no casts). */
function toSortKey(v: string): SortKey {
  if (v === "price-asc" || v === "price-desc" || v === "data-desc") {
    return v;
  }
  return "price-asc";
}

/** Client-side sort (no backend round-trip). Null data_gb sorts last on data-desc. */
function sortPlans(
  plans: readonly PlanCatalogueItem[],
  key: SortKey,
): readonly PlanCatalogueItem[] {
  const sorted = [...plans];
  if (key === "price-asc") {
    sorted.sort((a, b) => a.price_paise - b.price_paise);
  } else if (key === "price-desc") {
    sorted.sort((a, b) => b.price_paise - a.price_paise);
  } else {
    sorted.sort((a, b) => (b.data_gb ?? -1) - (a.data_gb ?? -1));
  }
  return sorted;
}

/** Plan catalogue: client-side filter by validity + sort, with a Current Plan badge. */
function Plans() {
  const { data: plans, isLoading, isError } = usePlans();
  const { data: activePlan } = useActivePlan();
  const [validity, setValidity] = useState<ValidityFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("price-asc");

  const activePlanId = activePlan?.plan_id ?? null;

  const visible = useMemo(() => {
    if (plans === undefined) {
      return [];
    }
    const filtered = plans.filter(
      (p) => validity === "all" || p.validity_days === validity,
    );
    return sortPlans(filtered, sortKey);
  }, [plans, validity, sortKey]);

  if (isLoading) {
    return (
      <main className="max-w-3xl mx-auto px-4 py-8">
        <div className="rounded-xl bg-white shadow p-6 animate-pulse h-40" />
      </main>
    );
  }
  if (isError) {
    return (
      <main className="max-w-3xl mx-auto px-4 py-8">
        <div className="rounded-xl bg-red-50 border border-red-200 p-6">
          <p className="text-sm text-red-600">Failed to load plans.</p>
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-6">
      <h1 className="text-2xl font-bold text-neutral-900">Plans</h1>

      <div className="flex flex-wrap items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-neutral-500">Validity</span>
          <select
            value={String(validity)}
            onChange={(e) => setValidity(toValidity(e.target.value))}
            className="rounded-md border border-neutral-300 px-2 py-1"
            aria-label="Filter plans by validity"
          >
            {VALIDITY_OPTIONS.map((o) => (
              <option key={String(o.value)} value={String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-neutral-500">Sort</span>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(toSortKey(e.target.value))}
            className="rounded-md border border-neutral-300 px-2 py-1"
            aria-label="Sort plans"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {visible.length === 0 ? (
        <p className="text-sm text-neutral-500">
          No plans match the selected filter.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {visible.map((plan) => (
            <PlanCard
              key={plan.id}
              plan={plan}
              isCurrent={plan.id === activePlanId}
            />
          ))}
        </div>
      )}
    </main>
  );
}

export { Plans };
