import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { useNotificationsWebSocket } from '../../hooks/useNotificationsWebSocket';
import type { NotificationEvent } from '../../hooks/useNotificationsWebSocket';

const STATUS_LABELS: Record<string, string> = {
  connecting: 'Connecting…',
  open: 'Connected',
  closed: 'Disconnected (reconnecting)',
  error: 'Connection error',
};

interface NotificationRowProps {
  readonly event: NotificationEvent;
}

function NotificationRow({ event }: NotificationRowProps) {
  return (
    <div className="flex items-start gap-3 rounded border border-neutral-200 bg-white p-3">
      <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-brand-500" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-neutral-900">{event.notification_type}</span>
          <time className="font-mono text-xs text-neutral-400">{event.timestamp}</time>
        </div>
        <p className="mt-0.5 truncate text-sm text-neutral-700">{event.message_preview}</p>
        <p className="mt-0.5 font-mono text-xs text-neutral-500">subscriber …{event.msisdn_suffix}</p>
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
      <div className="mx-auto max-w-3xl space-y-6">
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-neutral-900">Notification Portal</h1>
            <span
              className={`text-xs font-medium ${status === 'open' ? 'text-success-700' : 'text-neutral-400'}`}
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
            <div className="space-y-2" aria-label="Notification feed" aria-live="polite">
              {events.map((event, idx) => (
                <NotificationRow key={`${event.trace_id}-${event.timestamp}-${idx}`} event={event} />
              ))}
            </div>
          )}

          {events.length > 0 && (
            <div className="mt-4">
              <Button variant="secondary" className="text-xs" onClick={clearEvents}>
                Clear
              </Button>
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}
