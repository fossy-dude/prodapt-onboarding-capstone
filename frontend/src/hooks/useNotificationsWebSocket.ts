import { useCallback, useEffect, useRef, useState } from "react";

import { getToken } from "../lib/auth";

export interface NotificationEvent {
  readonly msisdn_suffix: string;
  readonly notification_type: string;
  readonly message_preview: string;
  readonly timestamp: string;
  readonly trace_id: string;
}

type ConnectionStatus = "connecting" | "open" | "closed" | "error";

interface UseNotificationsWebSocketResult {
  readonly events: readonly NotificationEvent[];
  readonly status: ConnectionStatus;
  readonly clearEvents: () => void;
}

const WS_BASE_URL =
  (import.meta.env.VITE_WS_BASE_URL as string | undefined) ??
  "ws://localhost:8000";
// Cap the live feed so a long-running portal session never grows unbounded.
const MAX_EVENTS = 50;

/**
 * Subscribe to the Notification Portal WebSocket (Story 2.9 AC #3, #4).
 *
 * Connects to ``ws://localhost:8000/ws/notifications`` (dev JWT via ``?token=``),
 * prepends each broadcast notification to a newest-first list capped at
 * ``MAX_EVENTS``, and reconnects 3s after an unexpected close. MSISDNs arrive
 * already masked to ``[-4:]`` from the server — the client never sees the full number.
 */
export function useNotificationsWebSocket(): UseNotificationsWebSocketResult {
  const [events, setEvents] = useState<readonly NotificationEvent[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearEvents = useCallback(() => setEvents([]), []);

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const token = getToken();
      const url = token
        ? `${WS_BASE_URL}/ws/notifications?token=${encodeURIComponent(token)}`
        : `${WS_BASE_URL}/ws/notifications`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus("connecting");

      ws.onopen = () => {
        if (!cancelled) setStatus("open");
      };

      ws.onmessage = (evt: MessageEvent<string>) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(evt.data) as NotificationEvent;
          setEvents((prev) => [msg, ...prev].slice(0, MAX_EVENTS));
        } catch {
          // ignore malformed messages
        }
      };

      ws.onerror = () => {
        if (!cancelled) setStatus("error");
      };

      ws.onclose = () => {
        if (!cancelled) {
          setStatus("closed");
          reconnectRef.current = setTimeout(connect, 3000);
        }
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectRef.current !== null) clearTimeout(reconnectRef.current);
      wsRef.current?.close();
    };
  }, []);

  return { events, status, clearEvents };
}
