import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { useNotificationsWebSocket } from "../../hooks/useNotificationsWebSocket";
import type { NotificationEvent } from "../../hooks/useNotificationsWebSocket";

const STATUS_LABELS: Record<string, string> = {
  connecting: "Connecting…",
  open: "Connected",
  closed: "Disconnected (reconnecting)",
  error: "Connection error",
};

interface NotificationRowProps {
  readonly event: NotificationEvent;
}

function formatTimestamp(timestamp: string): string {
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) {
      return "Just now";
    } else if (diffMins < 60) {
      return `${diffMins}m ago`;
    } else if (diffHours < 24) {
      return `${diffHours}h ago`;
    } else if (diffDays < 7) {
      return `${diffDays}d ago`;
    } else {
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  } catch {
    return timestamp;
  }
}

function NotificationRow({ event }: NotificationRowProps) {
  return (
    <div className="grid grid-cols-[120px_1fr] sm:grid-cols-[120px_100px_1fr] gap-2 sm:gap-3 rounded border border-neutral-200 bg-white p-3 items-start">
      <div className="font-mono text-xs text-neutral-500">
        <span className="text-neutral-400">…{event.msisdn_suffix}</span>
      </div>
      <div className="hidden sm:block font-mono text-xs text-neutral-400">
        {formatTimestamp(event.timestamp)}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1 sm:hidden">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-brand-50 text-brand-700">
            {event.notification_type}
          </span>
          <span className="font-mono text-xs text-neutral-400">
            {formatTimestamp(event.timestamp)}
          </span>
        </div>
        <div className="hidden sm:flex items-center gap-2 mb-1">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-brand-50 text-brand-700">
            {event.notification_type}
          </span>
        </div>
        <p className="text-sm text-neutral-700 whitespace-pre-wrap break-words">
          {event.message_preview}
        </p>
      </div>
    </div>
  );
}

/**
 * Notification Portal — a live-updating feed of every simulated notification (SMS,
 * push, OTP) broadcast on ``notification.events`` (Story 2.9 AC #4, #5). MSISDNs
 * arrive already masked to ``[-4:]`` from the server (PII hygiene).
 *
 * Route: /simulator/notifications. Requires `dev` role.
 */
export function NotificationPortal() {
  const { events, status, clearEvents } = useNotificationsWebSocket();

  return (
    <main className="px-4 py-10">
      <div className="mx-auto max-w-4xl space-y-6">
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-neutral-900">
              Notification Portal
            </h1>
            <span
              className={`text-xs font-medium ${status === "open" ? "text-success-700" : "text-neutral-400"}`}
              aria-live="polite"
            >
              {STATUS_LABELS[status]}
            </span>
          </div>

          {events.length === 0 ? (
            <p className="text-sm text-neutral-400" role="status">
              Waiting for notifications…
            </p>
          ) : (
            <>
              {/* Column Headers */}
              <div className="hidden sm:grid grid-cols-[120px_100px_1fr] gap-3 pb-2 border-b border-neutral-200 mb-2 text-xs font-medium text-neutral-500 uppercase tracking-wide">
                <div>Subscriber</div>
                <div>Time</div>
                <div>Notification</div>
              </div>

              {/* Notifications */}
              <div
                className="space-y-2"
                aria-label="Notification feed"
                aria-live="polite"
              >
                {events.map((event, idx) => (
                  <NotificationRow
                    key={`${event.trace_id}-${event.timestamp}-${idx}`}
                    event={event}
                  />
                ))}
              </div>
            </>
          )}

          {events.length > 0 && (
            <div className="mt-4">
              <Button
                variant="secondary"
                className="text-xs"
                onClick={clearEvents}
              >
                Clear
              </Button>
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}
