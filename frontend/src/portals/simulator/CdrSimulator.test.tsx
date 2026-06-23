import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import { CdrSimulator } from './CdrSimulator';

vi.mock('../../lib/api', () => ({
  dispatchCdr: vi.fn(),
  toApiError: () => null,
}));

vi.mock('../../hooks/useTraceWebSocket', () => ({
  useTraceWebSocket: vi.fn(() => ({
    events: [],
    status: 'open',
    clearEvents: vi.fn(),
  })),
}));

const { dispatchCdr } = await import('../../lib/api');
const { useTraceWebSocket } = await import('../../hooks/useTraceWebSocket');

function renderComponent() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CdrSimulator />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CdrSimulator', () => {
  beforeEach(() => {
    vi.mocked(dispatchCdr).mockReset();
    vi.mocked(useTraceWebSocket).mockReturnValue({
      events: [],
      status: 'open',
      clearEvents: vi.fn(),
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders the form with MSISDN, event type, and dispatch button', () => {
    renderComponent();
    expect(screen.getByLabelText(/Subscriber MSISDN/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Event Type/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Dispatch CDR/i })).toBeInTheDocument();
  });

  it('dispatches a voice CDR on button click', async () => {
    vi.mocked(dispatchCdr).mockResolvedValue({
      trace_id: 'a'.repeat(32),
      cdr_type: 'voice',
      subscriber_msisdn: '+919876543210',
    });
    const user = userEvent.setup();
    renderComponent();

    await user.click(screen.getByRole('button', { name: /Dispatch CDR/i }));

    await waitFor(() => expect(dispatchCdr).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(dispatchCdr).mock.calls[0]?.[0];
    expect(payload?.cdr_type).toBe('voice');
    expect(payload?.subscriber_msisdn).toBe('+919876543210');
  });

  it('shows duration field only for voice type', async () => {
    const user = userEvent.setup();
    renderComponent();

    expect(screen.getByLabelText(/Duration \(seconds\)/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/Event Type/i), 'data');
    expect(screen.queryByLabelText(/Duration \(seconds\)/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Volume \(MB\)/i)).toBeInTheDocument();
  });

  it('shows volume field for data type and message direction for sms', async () => {
    const user = userEvent.setup();
    renderComponent();

    await user.selectOptions(screen.getByLabelText(/Event Type/i), 'sms');
    expect(screen.getByLabelText(/Message Direction/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Volume \(MB\)/i)).not.toBeInTheDocument();
  });

  it('shows the dispatch success trace id after dispatch', async () => {
    vi.mocked(dispatchCdr).mockResolvedValue({
      trace_id: 'deadbeef'.repeat(4),
      cdr_type: 'voice',
      subscriber_msisdn: '+919876543210',
    });
    const user = userEvent.setup();
    renderComponent();

    await user.click(screen.getByRole('button', { name: /Dispatch CDR/i }));

    await waitFor(() =>
      expect(screen.getByText(/Dispatched — trace:/i)).toHaveTextContent('deadbeefdeadbeefdeadbeefdeadbeef'),
    );
  });

  it('renders streamed trace stages filtered by the dispatched trace id', async () => {
    vi.mocked(dispatchCdr).mockResolvedValue({
      trace_id: 'a'.repeat(32),
      cdr_type: 'voice',
      subscriber_msisdn: '+919876543210',
    });
    vi.mocked(useTraceWebSocket).mockReturnValue({
      events: [
        { stage: 'Received', timestamp: 't1', trace_id: 'a'.repeat(32), error: null },
        { stage: 'Deduped', timestamp: 't2', trace_id: 'a'.repeat(32), error: null },
      ],
      status: 'open',
      clearEvents: vi.fn(),
    });
    const user = userEvent.setup();
    renderComponent();

    await user.click(screen.getByRole('button', { name: /Dispatch CDR/i }));

    await waitFor(() => expect(screen.getByText('Received')).toBeInTheDocument());
    expect(screen.getByText('Deduped')).toBeInTheDocument();
  });

  it('surfaces an error string from a failed stage event', async () => {
    vi.mocked(dispatchCdr).mockResolvedValue({
      trace_id: 'a'.repeat(32),
      cdr_type: 'voice',
      subscriber_msisdn: '+919876543210',
    });
    vi.mocked(useTraceWebSocket).mockReturnValue({
      events: [
        { stage: 'Balance Deducted', timestamp: 't1', trace_id: 'a'.repeat(32), error: 'insufficient balance' },
      ],
      status: 'open',
      clearEvents: vi.fn(),
    });
    const user = userEvent.setup();
    renderComponent();

    await user.click(screen.getByRole('button', { name: /Dispatch CDR/i }));

    await waitFor(() => expect(screen.getByText('insufficient balance')).toBeInTheDocument());
  });
});
