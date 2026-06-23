import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';

import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { dispatchCdr, toApiError } from '../../lib/api';
import { useTraceWebSocket } from '../../hooks/useTraceWebSocket';
import type { TraceStageEvent } from '../../hooks/useTraceWebSocket';

type CdrType = 'voice' | 'data' | 'sms';

interface DispatchForm {
  readonly subscriberMsisdn: string;
  readonly cdrType: CdrType;
  readonly durationSeconds: string;
  readonly volumeMb: string;
  readonly messageDirection: 'MO' | 'MT';
  readonly timestamp: string;
}

const STAGE_ORDER: readonly string[] = ['Received', 'Deduped', 'Balance Deducted', 'Notification Queued'];

const STAGE_LABELS: Record<string, string> = {
  Received: 'Received',
  Deduped: 'Deduped',
  'Balance Deducted': 'Balance Deducted',
  'Notification Queued': 'Notification Queued',
};

interface StageRowProps {
  readonly event: TraceStageEvent;
}

function StageRow({ event }: StageRowProps) {
  return (
    <div className="flex items-start gap-3 rounded border border-neutral-200 bg-white p-3">
      <span
        className={`mt-0.5 h-2 w-2 flex-shrink-0 rounded-full ${event.error !== null ? 'bg-danger-500' : 'bg-success-500'}`}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-neutral-900">
            {STAGE_LABELS[event.stage] ?? event.stage}
          </span>
          <span className="font-mono text-xs text-neutral-400">{event.timestamp}</span>
        </div>
        {event.error !== null && (
          <p className="mt-1 text-xs text-danger-600" role="alert">
            {event.error}
          </p>
        )}
        <p className="mt-0.5 font-mono text-xs text-neutral-500">trace: {event.trace_id}</p>
      </div>
    </div>
  );
}

const DEFAULT_FORM: DispatchForm = {
  subscriberMsisdn: '+919876543210',
  cdrType: 'voice',
  durationSeconds: '60',
  volumeMb: '10',
  messageDirection: 'MO',
  timestamp: '',
};

/**
 * CDR Simulator tool — dispatch synthetic CDR events and watch pipeline trace
 * stages stream in real-time via WebSocket (Story 2.8 AC #1–#5).
 * Route: /simulator/cdr. Requires `dev` role.
 */
export function CdrSimulator() {
  const [form, setForm] = useState<DispatchForm>(DEFAULT_FORM);
  const [dispatchError, setDispatchError] = useState<string | null>(null);
  const [lastTraceId, setLastTraceId] = useState<string | null>(null);

  const { events, status: wsStatus, clearEvents } = useTraceWebSocket();

  const traceEvents = lastTraceId !== null ? events.filter((e) => e.trace_id === lastTraceId) : [];

  const mutation = useMutation({
    mutationFn: () =>
      dispatchCdr({
        cdr_type: form.cdrType,
        subscriber_msisdn: form.subscriberMsisdn,
        duration_seconds: form.cdrType === 'voice' ? parseInt(form.durationSeconds, 10) : undefined,
        volume_mb: form.cdrType === 'data' ? parseFloat(form.volumeMb) : undefined,
        message_direction: form.cdrType === 'sms' ? form.messageDirection : undefined,
        timestamp: form.timestamp !== '' ? form.timestamp : undefined,
      }),
    onSuccess: (data) => {
      setLastTraceId(data.trace_id);
      setDispatchError(null);
    },
    onError: (err) => {
      const api = toApiError(err);
      setDispatchError(api?.message ?? 'Dispatch failed. Please try again.');
    },
  });

  function handleField<K extends keyof DispatchForm>(key: K, value: DispatchForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleDispatch() {
    clearEvents();
    setLastTraceId(null);
    setDispatchError(null);
    mutation.mutate();
  }

  const wsStatusLabel: Record<string, string> = {
    connecting: 'Connecting…',
    open: 'Connected',
    closed: 'Disconnected (reconnecting)',
    error: 'Connection error',
  };

  return (
    <main className="px-4 py-10">
      <div className="mx-auto max-w-3xl space-y-6">
        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h1 className="text-xl font-bold text-neutral-900">CDR Simulator</h1>
            <span
              className={`text-xs font-medium ${wsStatus === 'open' ? 'text-success-700' : 'text-neutral-400'}`}
              aria-live="polite"
            >
              {wsStatusLabel[wsStatus]}
            </span>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="cdr-msisdn" className="mb-1 block text-sm font-medium text-neutral-700">
                Subscriber MSISDN
              </label>
              <input
                id="cdr-msisdn"
                type="text"
                value={form.subscriberMsisdn}
                onChange={(e) => handleField('subscriberMsisdn', e.target.value)}
                placeholder="+919876543210"
                className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>

            <div>
              <label htmlFor="cdr-type" className="mb-1 block text-sm font-medium text-neutral-700">
                Event Type
              </label>
              <select
                id="cdr-type"
                value={form.cdrType}
                onChange={(e) => handleField('cdrType', e.target.value as CdrType)}
                className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              >
                <option value="voice">Voice</option>
                <option value="data">Data</option>
                <option value="sms">SMS</option>
              </select>
            </div>

            {form.cdrType === 'voice' && (
              <div>
                <label htmlFor="cdr-duration" className="mb-1 block text-sm font-medium text-neutral-700">
                  Duration (seconds)
                </label>
                <input
                  id="cdr-duration"
                  type="number"
                  min="0"
                  value={form.durationSeconds}
                  onChange={(e) => handleField('durationSeconds', e.target.value)}
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                />
              </div>
            )}

            {form.cdrType === 'data' && (
              <div>
                <label htmlFor="cdr-volume" className="mb-1 block text-sm font-medium text-neutral-700">
                  Volume (MB)
                </label>
                <input
                  id="cdr-volume"
                  type="number"
                  min="0"
                  step="0.1"
                  value={form.volumeMb}
                  onChange={(e) => handleField('volumeMb', e.target.value)}
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                />
              </div>
            )}

            {form.cdrType === 'sms' && (
              <div>
                <label htmlFor="cdr-direction" className="mb-1 block text-sm font-medium text-neutral-700">
                  Message Direction
                </label>
                <select
                  id="cdr-direction"
                  value={form.messageDirection}
                  onChange={(e) => handleField('messageDirection', e.target.value as 'MO' | 'MT')}
                  className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
                >
                  <option value="MO">MO (Mobile Originated)</option>
                  <option value="MT">MT (Mobile Terminated)</option>
                </select>
              </div>
            )}

            <div>
              <label htmlFor="cdr-timestamp" className="mb-1 block text-sm font-medium text-neutral-700">
                Timestamp (optional)
              </label>
              <input
                id="cdr-timestamp"
                type="datetime-local"
                value={form.timestamp}
                onChange={(e) => handleField('timestamp', e.target.value)}
                className="w-full rounded border border-neutral-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
            </div>
          </div>

          <div className="mt-6 flex items-center gap-4">
            <Button onClick={handleDispatch} disabled={mutation.isPending}>
              {mutation.isPending ? 'Dispatching…' : 'Dispatch CDR'}
            </Button>
            {mutation.isSuccess && lastTraceId !== null && (
              <p className="font-mono text-xs text-success-700">
                Dispatched — trace: {lastTraceId}
              </p>
            )}
            {dispatchError !== null && (
              <p className="text-xs text-danger-600" role="alert">
                {dispatchError}
              </p>
            )}
          </div>
        </Card>

        <Card>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-semibold text-neutral-900">Pipeline Trace</h2>
            {traceEvents.length > 0 && (
              <span className="text-xs text-neutral-500">
                {traceEvents.length} / {STAGE_ORDER.length} stages
              </span>
            )}
          </div>

          {lastTraceId === null ? (
            <p className="text-sm text-neutral-400">Dispatch a CDR to see trace stages here.</p>
          ) : traceEvents.length === 0 ? (
            <p className="text-sm text-neutral-400" role="status">
              Waiting for pipeline stages…
            </p>
          ) : (
            <div className="space-y-2" aria-label="Pipeline trace stages" aria-live="polite">
              {traceEvents.map((event, idx) => (
                <StageRow key={`${event.trace_id}-${idx}`} event={event} />
              ))}
            </div>
          )}
        </Card>
      </div>
    </main>
  );
}
