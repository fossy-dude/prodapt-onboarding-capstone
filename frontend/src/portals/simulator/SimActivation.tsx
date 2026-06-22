import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Table, type TableColumn } from '../../components/ui/Table';
import { advanceOrderState, getSimulatorOrders, toApiError } from '../../lib/api';

interface OrderRow {
  readonly order_id: string;
  readonly current_status: string;
  readonly created_at: string | null;
}

const STATE_LABELS: Record<string, string> = {
  CREATED: 'Created',
  KYC_PENDING: 'KYC Pending',
  KYC_VERIFIED: 'KYC Verified',
  ACTIVATED: 'Activated',
};

const COLUMNS: readonly TableColumn[] = [
  { key: 'id', header: 'Order ID' },
  { key: 'state', header: 'Current State' },
  { key: 'action', header: 'Action' },
  { key: 'result', header: 'Result' },
];

function OrderAdvanceRow({ order }: { readonly order: OrderRow }) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => advanceOrderState(order.order_id),
    onSuccess: (data) => {
      setResult(
        `${STATE_LABELS[data.previous_status] ?? data.previous_status} → ${STATE_LABELS[data.status] ?? data.status}`,
      );
      setError(null);
      // Refresh the order list so the row's new state reflects after an advance.
      void queryClient.invalidateQueries({ queryKey: ['simulatorOrders'] });
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
 * Simulator developer tool — list orders and advance ops_order_fulfilment through
 * the activation state machine (Story 1.7 AC #6). Fetches its own order list via
 * GET /api/v1/simulator/orders (dev role). Route: /simulator/activate.
 * NOT subscriber-facing.
 */
export function SimActivation() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['simulatorOrders'],
    queryFn: getSimulatorOrders,
  });
  const orders = data?.orders ?? [];

  return (
    <main className="px-4 py-10">
      <Card>
        <h1 className="mb-2 text-xl font-bold text-neutral-900">SIM Activation — Simulator Tool</h1>
        <p className="mb-6 text-sm text-neutral-500">
          Advance order fulfilment state for testing. Forward transitions only.
        </p>
        {isLoading ? (
          <p className="text-sm text-neutral-500" role="status">
            Loading orders…
          </p>
        ) : isError ? (
          <p className="text-sm text-danger-600" role="alert">
            Failed to load orders. Please refresh.
          </p>
        ) : (
          <Table
            columns={COLUMNS}
            rows={orders}
            renderRow={(order) => <OrderAdvanceRow key={order.order_id} order={order} />}
            emptyState="No orders found."
          />
        )}
      </Card>
    </main>
  );
}
