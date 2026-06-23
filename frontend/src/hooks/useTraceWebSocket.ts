import { useCallback, useEffect, useRef, useState } from 'react';

import { getToken } from '../lib/auth';

export interface TraceStageEvent {
  readonly stage: string;
  readonly timestamp: string;
  readonly trace_id: string;
  readonly error: string | null;
}

type ConnectionStatus = 'connecting' | 'open' | 'closed' | 'error';

interface UseTraceWebSocketResult {
  readonly events: readonly TraceStageEvent[];
  readonly status: ConnectionStatus;
  readonly clearEvents: () => void;
}

const WS_BASE_URL = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? 'ws://localhost:8000';

export function useTraceWebSocket(): UseTraceWebSocketResult {
  const [events, setEvents] = useState<readonly TraceStageEvent[]>([]);
  const [status, setStatus] = useState<ConnectionStatus>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearEvents = useCallback(() => setEvents([]), []);

  useEffect(() => {
    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const token = getToken();
      if (!token) {
        setStatus('error');
        return;
      }
      const url = `${WS_BASE_URL}/ws/simulator/trace?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(url);
      wsRef.current = ws;
      setStatus('connecting');

      ws.onopen = () => {
        if (!cancelled) setStatus('open');
      };

      ws.onmessage = (evt: MessageEvent<string>) => {
        if (cancelled) return;
        try {
          const msg = JSON.parse(evt.data) as TraceStageEvent;
          setEvents((prev) => [...prev, msg]);
        } catch {
          // ignore malformed messages
        }
      };

      ws.onerror = () => {
        if (!cancelled) setStatus('error');
      };

      ws.onclose = () => {
        if (!cancelled) {
          setStatus('closed');
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
