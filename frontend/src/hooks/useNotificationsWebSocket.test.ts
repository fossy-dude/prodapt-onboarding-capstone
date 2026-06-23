import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

import { useNotificationsWebSocket } from './useNotificationsWebSocket';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((evt: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(): void {}

  close(): void {
    this.closed = true;
  }

  fireOpen() {
    this.onopen?.();
  }

  fireMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) });
  }
}

describe('useNotificationsWebSocket', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', MockWebSocket);
    MockWebSocket.instances = [];
    localStorage.setItem('sboai_access_token', 'fake-token');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    localStorage.clear();
  });

  it('opens a connection to /ws/notifications with the token in the URL', async () => {
    renderHook(() => useNotificationsWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    expect(MockWebSocket.instances[0]?.url).toContain('/ws/notifications');
    expect(MockWebSocket.instances[0]?.url).toContain('token=fake-token');
  });

  it('prepends incoming notifications newest-first', async () => {
    const { result } = renderHook(() => useNotificationsWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;
    act(() => ws.fireOpen());

    act(() =>
      ws.fireMessage({
        msisdn_suffix: '3210',
        notification_type: 'SIM_ACTIVATION',
        message_preview: 'first',
        timestamp: 't1',
        trace_id: 'a'.repeat(32),
      }),
    );
    act(() =>
      ws.fireMessage({
        msisdn_suffix: '4321',
        notification_type: 'LOW_BALANCE',
        message_preview: 'second',
        timestamp: 't2',
        trace_id: 'b'.repeat(32),
      }),
    );

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events[0]?.notification_type).toBe('LOW_BALANCE'); // newest first
    expect(result.current.events[1]?.notification_type).toBe('SIM_ACTIVATION');
  });

  it('caps the live feed to the most recent 50 events', async () => {
    const { result } = renderHook(() => useNotificationsWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;
    act(() => ws.fireOpen());

    act(() => {
      for (let i = 0; i < 60; i += 1) {
        ws.fireMessage({
          msisdn_suffix: String(i),
          notification_type: 'SIM_ACTIVATION',
          message_preview: `msg-${i}`,
          timestamp: `t${i}`,
          trace_id: 'c'.repeat(32),
        });
      }
    });

    expect(result.current.events).toHaveLength(50);
    // newest-first: the last pushed (59) should be first
    expect(result.current.events[0]?.message_preview).toBe('msg-59');
  });

  it('clearEvents resets the feed', async () => {
    const { result } = renderHook(() => useNotificationsWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;
    act(() =>
      ws.fireMessage({
        msisdn_suffix: '3210',
        notification_type: 'SIM_ACTIVATION',
        message_preview: 'x',
        timestamp: 't1',
        trace_id: 'a'.repeat(32),
      }),
    );
    expect(result.current.events).toHaveLength(1);

    act(() => result.current.clearEvents());
    expect(result.current.events).toHaveLength(0);
  });

  it('sets error status when no token is present', () => {
    localStorage.removeItem('sboai_access_token');
    const { result } = renderHook(() => useNotificationsWebSocket());
    expect(result.current.status).toBe('error');
  });
});
