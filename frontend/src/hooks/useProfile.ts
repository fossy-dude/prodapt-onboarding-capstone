import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getProfile,
  updateProfile,
  type ProfileData,
  type ProfileUpdatePayload,
} from "../lib/api";

/**
 * TanStack Query keys + hooks for the subscriber profile (Story 1.9; §1.9.3).
 *
 * The profile query is invalidated (and optimistically seeded) on a successful
 * edit so the read view reflects the PATCH response without a manual refetch.
 */
export const PROFILE_QUERY_KEY = ["profile"] as const;

/** Read the authenticated subscriber's decrypted profile. */
export function useProfile() {
  return useQuery({ queryKey: PROFILE_QUERY_KEY, queryFn: getProfile });
}

/** Edit email/address; on success refresh the cached profile (invalidate + seed). */
export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation<ProfileData, Error, ProfileUpdatePayload>({
    mutationFn: (payload) => updateProfile(payload),
    onSuccess: (data) => {
      queryClient.setQueryData(PROFILE_QUERY_KEY, data);
      void queryClient.invalidateQueries({ queryKey: PROFILE_QUERY_KEY });
    },
  });
}
