import { useQuery } from "@tanstack/react-query";

import { getActivePlan, type ActivePlanData } from "../lib/api";

export const ACTIVE_PLAN_QUERY_KEY = ["active-plan"] as const;

/**
 * Read the subscriber's active plan details + quotas (GET /subscriber/plan).
 * Data is `null` (not an error) when the subscriber has no active plan yet.
 * `staleTime` keeps the many consumers (Dashboard, PlanDetailsCard, Chatbot,
 * Plans) from each re-triggering a fetch on mount.
 */
export function useActivePlan() {
  return useQuery<ActivePlanData | null, Error>({
    queryKey: ACTIVE_PLAN_QUERY_KEY,
    queryFn: getActivePlan,
    staleTime: 60_000,
  });
}
