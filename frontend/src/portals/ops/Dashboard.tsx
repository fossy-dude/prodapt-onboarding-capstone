/**
 * Ops Dashboard - main dashboard for operations team (Story 7.2 Task 3; Story 7.4 Task 8).
 * Displays plan stock, order fulfilment, and demand forecast views.
 */

import { PlanStock, type PlanStockItem } from "./PlanStock";
import { OrderFulfilment, type OrderItem } from "./OrderFulfilment";
import { Forecasts } from "./Forecasts";
import { usePlanStock, useOrderCounts, useOrdersByStatus } from "./hooks";

function Dashboard() {
  // Fetch data using React Query hooks with 30-second auto-refresh
  const {
    data: plans = [],
    isLoading: plansIsLoading,
    error: plansError,
  } = usePlanStock();

  const {
    data: counts = {},
    isLoading: countsIsLoading,
    error: countsError,
  } = useOrderCounts();

  // For initial implementation, show all orders regardless of plan selection
  // TODO: Implement plan filtering in Task 4
  const {
    data: orders = [],
    isLoading: ordersIsLoading,
    error: ordersError,
  } = useOrdersByStatus("CREATED"); // Default to CREATED status for initial load

  // Error handling
  if (plansError || countsError || ordersError) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h2 className="mb-2 text-lg font-semibold text-red-900">Error loading dashboard data</h2>
        <p className="text-sm text-red-700">
          {(plansError as Error)?.message ||
            (countsError as Error)?.message ||
            (ordersError as Error)?.message ||
            "Unknown error"}
        </p>
        <button
          onClick={() => window.location.reload()}
          className="mt-4 rounded bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-neutral-900">Operations Dashboard</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Real-time plan adoption and order fulfilment monitoring. Auto-refreshes every 30 seconds.
        </p>
      </div>

      <PlanStock plans={plans} isLoading={plansIsLoading} />

      <OrderFulfilment
        counts={counts}
        countsIsLoading={countsIsLoading}
        orders={orders}
        ordersIsLoading={ordersIsLoading}
      />

      <div>
        <h2 className="mb-3 text-lg font-semibold text-neutral-900">Demand Forecasts</h2>
        <Forecasts />
      </div>
    </div>
  );
}

export { Dashboard };
