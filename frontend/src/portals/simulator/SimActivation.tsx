import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { advanceOrderState, toApiError } from '../../lib/api';

const STATE_LABELS: Record<string, string> = {
  CREATED: 'Created',
  KYC_PENDING: 'KYC Pending',
  KYC_VERIFIED: 'KYC Verified',
  ACTIVATED: 'Activated',
};

interface OrderRow {
  readonly order_id: string;
  readonly current_status: string;
}

interface SimActivationProps {
  readonly orders?: readonly OrderRow[];
}

function OrderAdvanceRow({ order }: { readonly order: OrderRow }) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => advanceOrderState(order.order_id),
    onSuccess: (data) => {
      setResult(`${STATE_LABELS[data.previous_status] ?? data.previous_status} → ${STATE_LABELS[data.status] ?? data.status}`);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['orderStatus'] });
    },
    onError: (err) => {
      const api = toApiError(err);
      setError(api?.message ?? 'Failed to advance order state.');
      setResult(null);
    },
  });

  const isTerminal = order.current_status === 'ACTIVATED';

  return (
    <tr className="border-t border-neutral-200">
      <td className="py-2 pr-4 font-mono text-xs text-neutral-700">{order.order_id.slice(0, 8)}…</td>
      <td className="py-2 pr-4 text-sm">
        {STATE_LABELS[order.current_status] ?? order.current_status}
      </td>
      <td className="py-2 pr-4">
        <Button
          variant="secondary"
          disabled={isTerminal || mutation.isPending}
          onClick={() => mutation.mutate()}
          className="text-xs"
        >
          {mutation.isPending ? 'Advancing…' : 'Advance'}
        </Button>
      </td>
      <td className="py-2 text-xs">
        {result && <span className="text-success-700">{result}</span>}
        {error && <span className="text-danger-600">{error}</span>}
        {isTerminal && <span className="text-neutral-400">Terminal</span>}
      </td>
    </tr>
  );
}

/**
 * Simulator developer tool — advance ops_order_fulfilment through the state machine (Story 1.7 AC #6).
 * Route: /simulator/activate (behind /simulator/* RoleGuard — dev role only).
 * NOT subscriber-facing.
 */
export function SimActivation({ orders = [] }: SimActivationProps) {
  return (
    <main className="px-4 py-10">
      <Card>
        <h1 className="mb-2 text-xl font-bold text-neutral-900">SIM Activation — Simulator Tool</h1>
        <p className="mb-6 text-sm text-neutral-500">
          Advance order fulfilment state for testing. Forward transitions only.
        </p>
        {orders.length === 0 ? (
          <p className="text-sm text-neutral-500">No orders loaded. Provide order rows via props.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-neutral-300 text-xs text-neutral-500">
                  <th className="pb-2 pr-4">Order ID</th>
                  <th className="pb-2 pr-4">Current State</th>
                  <th className="pb-2 pr-4">Action</th>
                  <th className="pb-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <OrderAdvanceRow key={o.order_id} order={o} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </main>
  );
}
