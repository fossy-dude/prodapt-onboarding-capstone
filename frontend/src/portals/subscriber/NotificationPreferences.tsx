/**
 * Notification Preferences management page (Story 4.2).
 *
 * Allows authenticated subscribers to manage which notification types
 * they receive. Only shows alerts the subscriber has opted into.
 *
 * @see AC #1, #3 - Notification preferences UI functionality
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getNotificationPreferences,
  patchNotificationPreference,
  type NotificationPreferenceItem,
} from "../../lib/api";

import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";

/**
 * Display configuration for each notification type.
 */
const NOTIFICATION_TYPE_CONFIG = {
  LOW_BALANCE: {
    label: "Low Balance Alert",
    description: "Get notified when your balance falls below the threshold",
  },
  BALANCE_DEPLETED: {
    label: "Balance Depleted",
    description: "Get notified when your balance is exhausted",
  },
  PLAN_EXPIRY_REMINDER: {
    label: "Plan Expiry Reminder",
    description: "Get notified before your plan expires",
  },
  DATA_NUDGE: {
    label: "Data Usage Nudge",
    description: "Get notified about your data usage patterns",
  },
} as const;

/**
 * Toggle switch component for notification preferences.
 */
function ToggleSwitch({
  enabled,
  onToggle,
  disabled,
}: {
  readonly enabled: boolean;
  readonly onToggle: () => void;
  readonly disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled}
      className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 ${
        disabled ? "opacity-50 cursor-not-allowed" : ""
      } ${enabled ? "bg-brand-600" : "bg-neutral-200"}`}
      role="switch"
      aria-checked={enabled}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
          enabled ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}

/**
 * Individual notification preference row.
 */
function PreferenceRow({
  preference,
  onToggle,
  isLoading,
}: {
  readonly preference: NotificationPreferenceItem;
  readonly onToggle: (enabled: boolean) => void;
  readonly isLoading: boolean;
}) {
  const config = NOTIFICATION_TYPE_CONFIG[preference.notification_type as keyof typeof NOTIFICATION_TYPE_CONFIG];

  return (
    <div className="flex items-center justify-between border-b border-neutral-200 py-4 last:border-0">
      <div className="flex-1">
        <h3 className="text-sm font-medium text-neutral-900">{config?.label || preference.notification_type}</h3>
        <p className="text-xs text-neutral-500">{config?.description}</p>
      </div>
      <ToggleSwitch
        enabled={preference.is_enabled}
        onToggle={() => onToggle(!preference.is_enabled)}
        disabled={isLoading}
      />
    </div>
  );
}

/**
 * Notification Preferences page component.
 *
 * Renders the list of all 4 notification types with toggle switches.
 * Supports optimistic updates for better UX.
 */
export function NotificationPreferences() {
  const queryClient = useQueryClient();

  // Server state: notification preferences
  const {
    data: preferences = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: getNotificationPreferences,
  });

  // Mutation for updating preferences
  const updateMutation = useMutation({
    mutationFn: async ({
      notification_type,
      is_enabled,
    }: {
      readonly notification_type: string;
      readonly is_enabled: boolean;
    }) => {
      const response = await patchNotificationPreference({ notification_type, is_enabled });
      return response;
    },
    onSuccess: async () => {
      try {
        await queryClient.invalidateQueries({ queryKey: ["notification-preferences"] });
      } catch (err) {
        console.error("Failed to invalidate notification preferences query:", err);
      }
    },
  });

  const handleToggle = (notification_type: string, is_enabled: boolean) => {
    updateMutation.mutate({ notification_type, is_enabled });
  };

  if (error) {
    return (
      <main className="px-4 py-10">
        <div className="mx-auto max-w-2xl">
          <div className="rounded-md border border-danger-200 bg-danger-50 p-4">
            <h2 className="text-lg font-medium text-danger-900">Error Loading Preferences</h2>
            <p className="mt-1 text-sm text-danger-700">
              Failed to load notification preferences. Please try again later.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="px-4 py-10">
      <div className="mx-auto max-w-2xl">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-neutral-900">Notification Preferences</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Manage which notifications you receive. Only opted-in alerts will be sent to you.
          </p>
        </div>

        {isLoading ? (
          <Card>
            <div className="space-y-4 p-6">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="animate-pulse">
                  <div className="h-4 w-48 bg-neutral-200 rounded" />
                  <div className="mt-2 h-3 w-64 bg-neutral-200 rounded" />
                </div>
              ))}
            </div>
          </Card>
        ) : (
          <Card>
            <div className="p-6">
              {preferences.map((preference) => (
                <PreferenceRow
                  key={preference.notification_type}
                  preference={preference}
                  onToggle={(enabled) => handleToggle(preference.notification_type, enabled)}
                  isLoading={updateMutation.isPending}
                />
              ))}
            </div>
          </Card>
        )}

        <div className="mt-4 rounded-md border border-info-200 bg-info-50 p-4">
          <p className="text-xs text-info-700">
            <strong>Note:</strong> Changes to your notification preferences take effect immediately. You can update these
            settings at any time.
          </p>
        </div>
      </div>
    </main>
  );
}
