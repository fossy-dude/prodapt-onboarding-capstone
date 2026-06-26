import { useQuery } from "@tanstack/react-query";

import { listPlans, type PlanCatalogueItem } from "../lib/api";

export const PLANS_QUERY_KEY = ["plans"] as const;

/** Read the active-plan catalogue shared across subscribers (GET /plans). */
export function usePlans() {
  return useQuery<readonly PlanCatalogueItem[], Error>({
    queryKey: PLANS_QUERY_KEY,
    queryFn: listPlans,
  });
}
