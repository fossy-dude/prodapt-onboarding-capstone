import { useQuery } from "@tanstack/react-query";

import { getUsage, type UsageData } from "../lib/api";

export const USAGE_QUERY_KEY = ["usage"] as const;

/**
 * Read the subscriber's per-type CDR usage for the active plan period.
 * `staleTime` keeps the multiple consumers (Dashboard, PlanDetailsCard) from
 * each re-triggering a fetch on mount.
 */
export function useUsage() {
  return useQuery<UsageData, Error>({
    queryKey: USAGE_QUERY_KEY,
    queryFn: getUsage,
    staleTime: 60_000,
  });
}
