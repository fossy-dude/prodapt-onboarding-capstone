import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

import { useTraceWebSocket } from './useTraceWebSocket';

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

describe('useTraceWebSocket', () => {
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

  it('opens a connection with the token in the URL', async () => {
    const { result } = renderHook(() => useTraceWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    expect(MockWebSocket.instances[0]?.url).toContain('token=fake-token');
    expect(MockWebSocket.instances[0]?.url).toContain('/ws/simulator/trace');

    act(() => MockWebSocket.instances[0]?.fireOpen());
    expect(result.current.status).toBe('open');
  });

  it('appends incoming stage events to the list in order', async () => {
    const { result } = renderHook(() => useTraceWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;
    act(() => ws.fireOpen());

    act(() =>
      ws.fireMessage({ stage: 'Received', timestamp: 't1', trace_id: 'a'.repeat(32), error: null }),
    );
    act(() =>
      ws.fireMessage({ stage: 'Deduped', timestamp: 't2', trace_id: 'a'.repeat(32), error: null }),
    );

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events[0]?.stage).toBe('Received');
    expect(result.current.events[1]?.stage).toBe('Deduped');
  });

  it('surfaces error field from an event', async () => {
    const { result } = renderHook(() => useTraceWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;

    act(() =>
      ws.fireMessage({ stage: 'Balance Deducted', timestamp: 't1', trace_id: 'b'.repeat(32), error: 'insufficient balance' }),
    );

    expect(result.current.events[0]?.error).toBe('insufficient balance');
  });

  it('clearEvents resets the event list', async () => {
    const { result } = renderHook(() => useTraceWebSocket());
    await waitFor(() => expect(MockWebSocket.instances.length).toBe(1));
    const ws = MockWebSocket.instances[0]!;
    act(() =>
      ws.fireMessage({ stage: 'Received', timestamp: 't1', trace_id: 'c'.repeat(32), error: null }),
    );
    expect(result.current.events).toHaveLength(1);

    act(() => result.current.clearEvents());
    expect(result.current.events).toHaveLength(0);
  });

  it('sets error status when no token is present', () => {
    localStorage.removeItem('sboai_access_token');
    const { result } = renderHook(() => useTraceWebSocket());
    expect(result.current.status).toBe('error');
  });
});
