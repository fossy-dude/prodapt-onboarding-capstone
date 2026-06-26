/**
 * OrderFulfilment component - displays order fulfilment status board and list (Story 7.2 Task 5).
 * Shows status cards with counts and a paginated order list.
 */

import { useState } from "react";

interface OrderItem {
  readonly order_id: string;
  readonly subscriber_id: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly status: string;
}

interface OrderFulfilmentCounts {
  readonly [key: string]: number;
}

interface OrderFulfilmentProps {
  readonly counts: OrderFulfilmentCounts;
  readonly countsIsLoading: boolean;
  readonly orders: OrderItem[];
  readonly ordersIsLoading: boolean;
  readonly selectedPlanId?: string;
}

// Status badge colors
const STATUS_COLORS: Record<
  string,
  { readonly bg: string; readonly text: string }
> = {
  CREATED: { bg: "bg-blue-100", text: "text-blue-800" },
  KYC_PENDING: { bg: "bg-yellow-100", text: "text-yellow-800" },
  KYC_VERIFIED: { bg: "bg-purple-100", text: "text-purple-800" },
  ACTIVATED: { bg: "bg-green-100", text: "text-green-800" },
};

function OrderFulfilment({
  counts,
  countsIsLoading,
  orders,
  ordersIsLoading,
  selectedPlanId,
}: OrderFulfilmentProps) {
  const [selectedStatus, setSelectedStatus] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(0);

  // Statuses to display
  const statuses = ["CREATED", "KYC_PENDING", "KYC_VERIFIED", "ACTIVATED"];

  // Handle status card click
  const handleStatusClick = (status: string) => {
    if (selectedStatus === status) {
      setSelectedStatus(null); // Toggle off
    } else {
      setSelectedStatus(status);
      setCurrentPage(0); // Reset pagination
    }
  };

  // Get orders for selected status or all orders
  const filteredOrders = selectedStatus
    ? orders.filter((order) => order.status === selectedStatus)
    : orders;

  // Pagination
  const PAGE_SIZE = 20;
  const totalPages = Math.ceil(filteredOrders.length / PAGE_SIZE);
  const paginatedOrders = filteredOrders.slice(
    currentPage * PAGE_SIZE,
    (currentPage + 1) * PAGE_SIZE,
  );

  // Mask subscriber ID (show last 4 digits only) - PII hygiene (NFR-16)
  const maskMsisdn = (subscriberId: string): string => {
    return `XXXX-${subscriberId.slice(-4)}`;
  };

  // Loading skeleton for status cards
  if (countsIsLoading) {
    return (
      <div className="rounded-lg border border-neutral-200 bg-white p-6">
        <h2 className="mb-4 text-lg font-semibold text-neutral-900">
          Order Fulfilment
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {statuses.map((status) => (
            <div
              key={status}
              className="h-24 animate-pulse rounded bg-neutral-200"
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-6">
      <h2 className="mb-4 text-lg font-semibold text-neutral-900">
        Order Fulfilment
        {selectedPlanId && (
          <span className="ml-2 text-sm font-normal text-neutral-500">
            (Filtered by Plan)
          </span>
        )}
      </h2>

      {/* Status cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statuses.map((status) => {
          const count = counts[status] || 0;
          const isSelected = selectedStatus === status;
          const colors = STATUS_COLORS[status] || {
            bg: "bg-gray-100",
            text: "text-gray-800",
          };

          return (
            <div
              key={status}
              className={`cursor-pointer rounded-lg border-2 p-4 transition-colors ${
                isSelected
                  ? "border-brand-primary bg-brand-primary/5"
                  : "border-neutral-200 hover:border-neutral-300"
              }`}
              onClick={() => handleStatusClick(status)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  handleStatusClick(status);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <div className="text-sm font-medium text-neutral-600">
                {status.replace("_", " ")}
              </div>
              <div className="mt-2 text-2xl font-bold text-neutral-900">
                {count.toLocaleString()}
              </div>
            </div>
          );
        })}
      </div>

      {/* Order list */}
      {selectedStatus && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-neutral-700">
            {selectedStatus.replace("_", " ")} Orders ({filteredOrders.length})
          </h3>

          {ordersIsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-16 animate-pulse rounded bg-neutral-200"
                />
              ))}
            </div>
          ) : paginatedOrders.length === 0 ? (
            <p className="text-sm text-neutral-500">
              No orders in this status.
            </p>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-neutral-200">
                  <thead className="bg-neutral-50">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700">
                        Order ID
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700">
                        Subscriber
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700">
                        Created
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700">
                        Updated
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-700">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-neutral-200">
                    {paginatedOrders.map((order) => (
                      <tr key={order.order_id}>
                        <td className="whitespace-nowrap px-4 py-4 text-sm font-mono text-neutral-900">
                          {order.order_id.slice(0, 8)}...
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-neutral-500">
                          {maskMsisdn(order.subscriber_id)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-neutral-500">
                          {new Date(order.created_at).toLocaleString()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm text-neutral-500">
                          {new Date(order.updated_at).toLocaleString()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-4 text-sm">
                          <span
                            className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${
                              STATUS_COLORS[order.status]?.bg || "bg-gray-100"
                            } ${STATUS_COLORS[order.status]?.text || "text-gray-800"}`}
                          >
                            {order.status.replace("_", " ")}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="mt-4 flex items-center justify-between">
                  <button
                    onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
                    disabled={currentPage === 0}
                    className="rounded px-3 py-1 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-neutral-100"
                  >
                    Previous
                  </button>
                  <span className="text-sm text-neutral-600">
                    Page {currentPage + 1} of {totalPages}
                  </span>
                  <button
                    onClick={() =>
                      setCurrentPage((p) => Math.min(totalPages - 1, p + 1))
                    }
                    disabled={currentPage === totalPages - 1}
                    className="rounded px-3 py-1 text-sm disabled:opacity-50 disabled:cursor-not-allowed hover:bg-neutral-100"
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {!selectedStatus && (
        <p className="text-sm text-neutral-500">
          Select a status card above to view orders in that category.
        </p>
      )}
    </div>
  );
}

export type { OrderItem };
export { OrderFulfilment };
