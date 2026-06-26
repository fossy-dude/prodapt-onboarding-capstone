import { useQuery } from "@tanstack/react-query";

import { getActivePlan, type ActivePlanData } from "../lib/api";

export const ACTIVE_PLAN_QUERY_KEY = ["active-plan"] as const;

/** Read the subscriber's active plan details + quotas (GET /subscriber/plan). */
export function useActivePlan() {
  return useQuery<ActivePlanData, Error>({
    queryKey: ACTIVE_PLAN_QUERY_KEY,
    queryFn: getActivePlan,
  });
}
