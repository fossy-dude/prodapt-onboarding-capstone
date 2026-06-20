import { QueryClient } from '@tanstack/react-query';

/**
 * Application QueryClient (UX brief §7.1 — src/lib/queryClient.ts).
 * Retries are disabled so failed mutations (e.g. a 409 duplicate) surface
 * immediately to the form instead of retrying.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
}
