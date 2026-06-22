import { Badge } from '../../components/ui/Badge';
import { Card } from '../../components/ui/Card';
import { useOrderStatus } from '../../hooks/useOrderStatus';

const STEPS = [
  { key: 'CREATED', label: 'Order Created' },
  { key: 'KYC_PENDING', label: 'KYC Pending' },
  { key: 'KYC_VERIFIED', label: 'KYC Verified' },
  { key: 'ACTIVATED', label: 'Activated' },
] as const;

type OrderStatus = (typeof STEPS)[number]['key'];

const STATUS_INDEX: Record<OrderStatus, number> = {
  CREATED: 0,
  KYC_PENDING: 1,
  KYC_VERIFIED: 2,
  ACTIVATED: 3,
};

const KNOWN_STATUSES: ReadonlySet<string> = new Set(STEPS.map((step) => step.key));

/** Narrow an arbitrary API status string to a known tracker step. */
function isOrderStatus(value: unknown): value is OrderStatus {
  return typeof value === 'string' && KNOWN_STATUSES.has(value);
}

function StepIndicator({ currentStatus }: { readonly currentStatus: OrderStatus }) {
  const currentIndex = STATUS_INDEX[currentStatus];
  return (
    <ol className="flex items-center gap-0">
      {STEPS.map((step, idx) => {
        const done = idx < currentIndex;
        const active = idx === currentIndex;
        return (
          <li key={step.key} className="flex flex-1 flex-col items-center">
            <div className="flex items-center w-full">
              {idx > 0 && (
                <div className={`h-0.5 flex-1 ${done || active ? 'bg-brand-600' : 'bg-neutral-200'}`} />
              )}
              <div
                className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold ${
                  done
                    ? 'border-brand-600 bg-brand-600 text-white'
                    : active
                      ? 'border-brand-600 bg-white text-brand-600'
                      : 'border-neutral-300 bg-white text-neutral-400'
                }`}
              >
                {done ? '✓' : idx + 1}
              </div>
              {idx < STEPS.length - 1 && (
                <div className={`h-0.5 flex-1 ${done ? 'bg-brand-600' : 'bg-neutral-200'}`} />
              )}
            </div>
            <span
              className={`mt-1 text-xs text-center ${active ? 'font-semibold text-brand-700' : done ? 'text-neutral-600' : 'text-neutral-400'}`}
            >
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function SimActivationContent() {
  const { status, msisdn, hasActiveOrder, isLoading, isError } = useOrderStatus();

  if (isLoading) {
    return (
      <p className="text-sm text-neutral-500" role="status">
        Loading your activation status…
      </p>
    );
  }

  if (isError) {
    return (
      <p className="text-sm text-danger-600" role="alert">
        Unable to load your activation order. Please refresh or contact support.
      </p>
    );
  }

  // No active order — a legitimate state, not an error (D7: discovery returns 200 null).
  if (!hasActiveOrder) {
    return (
      <div
        className="rounded-lg border border-neutral-200 bg-neutral-50 p-4"
        role="status"
        aria-label="No activation in progress"
      >
        <p className="text-sm font-medium text-neutral-700">No SIM activation in progress.</p>
        <p className="mt-1 text-xs text-neutral-500">
          Once you start a SIM activation, its step-by-step progress will appear here.
        </p>
      </div>
    );
  }

  // Unexpected status value (e.g. REJECTED) — guard before indexing to avoid NaN highlight.
  if (!isOrderStatus(status)) {
    return (
      <p className="text-sm text-danger-600" role="alert">
        Unexpected order status{status ? ` “${status}”` : ''}. Please refresh or contact support.
      </p>
    );
  }

  const orderStatus = status;

  return (
    <div className="space-y-6">
      <StepIndicator currentStatus={orderStatus} />
      {orderStatus === 'ACTIVATED' && msisdn !== null && (
        <div
          className="rounded-lg border border-success-300 bg-success-50 p-4"
          role="status"
          aria-label="Activation complete"
        >
          <p className="text-sm font-medium text-success-800">Your SIM is activated!</p>
          <p className="mt-1 text-sm text-success-700">
            Mobile number: <span className="font-mono font-semibold">{msisdn}</span>
          </p>
          <div className="mt-2">
            <Badge variant="verified">Active</Badge>
          </div>
        </div>
      )}
      {orderStatus !== 'ACTIVATED' && (
        <p className="text-xs text-neutral-500">Status refreshes automatically every 10 seconds.</p>
      )}
    </div>
  );
}

/**
 * Read-only SIM activation order tracker (Story 1.7 AC #1–#4).
 * Route: /subscriber/activate (behind /subscriber/* RoleGuard).
 * Polls GET /api/v1/subscriber/orders/{orderId}/status every 10 s;
 * stops polling and shows a success banner once ACTIVATED.
 */
export function SimActivation() {
  return (
    <main className="flex min-h-screen items-start justify-center px-4 py-10">
      <div className="w-full max-w-lg">
        <Card>
          <h1 className="mb-6 text-xl font-bold text-neutral-900">SIM Activation Status</h1>
          <SimActivationContent />
        </Card>
      </div>
    </main>
  );
}
