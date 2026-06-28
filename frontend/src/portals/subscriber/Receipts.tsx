import { Table, type TableColumn } from "../../components/ui/Table";
import { Badge } from "../../components/ui/Badge";
import { useTransactions } from "../../hooks/useTransactions";
import type { TransactionItem } from "../../lib/api";

const COLUMNS: readonly TableColumn[] = [
  { key: "date", header: "Date" },
  { key: "description", header: "Description" },
  { key: "amount", header: "Amount" },
  { key: "type", header: "Type" },
];

function formatInr(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

function renderRow(txn: TransactionItem) {
  const isRefund = txn.transaction_type === "refund";
  return (
    <tr key={txn.id} className="border-b border-neutral-100">
      <td className="py-2 pr-4 text-neutral-500 text-sm">
        {formatDate(txn.created_at)}
      </td>
      <td className="py-2 pr-4">{txn.description ?? "—"}</td>
      <td className="py-2 pr-4 tabular-nums">
        <span className={isRefund ? "text-success-600 font-medium" : ""}>
          {formatInr(txn.amount_paise)}
        </span>
      </td>
      <td className="py-2 pr-4">
        <Badge variant={isRefund ? "verified" : "pending"}>
          {isRefund ? "Refund" : "Recharge"}
        </Badge>
      </td>
    </tr>
  );
}

function Receipts() {
  const {
    items,
    hasNext,
    hasPrev,
    nextPage,
    prevPage,
    isLoading,
    isError,
    isFetching,
  } = useTransactions();

  const billingItems = items.filter(
    (txn) =>
      txn.transaction_type === "recharge" || txn.transaction_type === "refund",
  );

  return (
    <main className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-neutral-900">Bills & Receipts</h1>
      <p className="mt-1 text-sm text-neutral-500">
        Your recharge payments and refund records.
      </p>

      <div className="mt-4 rounded-xl bg-white shadow p-6">
        {isLoading ? (
          <div className="animate-pulse h-40" />
        ) : isError ? (
          <div className="rounded-lg bg-danger-50 border border-red-200 p-4">
            <p className="text-sm text-danger-600">
              Failed to load billing history.
            </p>
          </div>
        ) : (
          <>
            <Table
              columns={COLUMNS}
              rows={billingItems}
              renderRow={renderRow}
              emptyState="No recharges or refunds on this page."
              caption="Recharge and refund history"
            />
            <div className="mt-4 flex items-center justify-between">
              <button
                type="button"
                onClick={prevPage}
                disabled={!hasPrev}
                className="text-xs font-semibold text-brand-600 hover:text-brand-700 disabled:text-neutral-300 disabled:hover:text-neutral-300"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={nextPage}
                disabled={!hasNext || isFetching}
                className="text-xs font-semibold text-brand-600 hover:text-brand-700 disabled:text-neutral-300 disabled:hover:text-neutral-300"
              >
                Next
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  );
}

export { Receipts };
