import { useState } from "react";

import { Table, type TableColumn } from "../../components/ui/Table";
import { useTransactions } from "../../hooks/useTransactions";
import { getFailedRecharges, type FailedRechargeItem } from "../../lib/api";
import type { TransactionItem } from "../../lib/api";
import { useQuery } from "@tanstack/react-query";

/** Friendly labels for raw stored transaction_type values (Story 3.3 variance:
 * the backend returns the writer's value, e.g. `cdr_deduction`). */
const TYPE_LABELS: Readonly<Record<string, string>> = {
  cdr_deduction: "Charge",
  charge: "Charge",
  recharge: "Recharge",
  refund: "Refund",
};

function formatType(type: string): string {
  return TYPE_LABELS[type] ?? type;
}

function formatInr(paise: number): string {
  return `₹${(paise / 100).toFixed(2)}`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" });
}

const COLUMNS: readonly TableColumn[] = [
  { key: "type", header: "Type" },
  { key: "description", header: "Description" },
  { key: "amount", header: "Amount" },
  { key: "balance", header: "Balance After" },
  { key: "cdr", header: "CDR Reference" },
  { key: "date", header: "Date" },
];

const FAILED_COLUMNS: readonly TableColumn[] = [
  { key: "plan", header: "Plan Attempted" },
  { key: "amount", header: "Amount" },
  { key: "reason", header: "Failure Reason" },
  { key: "date", header: "Date" },
];

/** Renders the CDR reference as a copyable code, or an em-dash when absent. */
function CdrReferenceCell({
  cdrReference,
}: {
  readonly cdrReference: string | null;
}) {
  const [copied, setCopied] = useState(false);

  if (cdrReference === null) {
    return <span className="text-neutral-400">—</span>;
  }

  const ref: string = cdrReference;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(ref);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard unavailable (e.g. insecure context) — copy silently no-ops.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="font-mono text-xs text-indigo-600 hover:text-indigo-800"
      aria-label={`Copy CDR reference ${ref}`}
    >
      {copied ? "Copied!" : ref}
    </button>
  );
}

function renderRow(txn: TransactionItem) {
  return (
    <tr key={txn.id} className="border-b border-neutral-100">
      <td className="py-2 pr-4">{formatType(txn.transaction_type)}</td>
      <td className="py-2 pr-4 text-neutral-600">{txn.description ?? "—"}</td>
      <td className="py-2 pr-4 tabular-nums">{formatInr(txn.amount_paise)}</td>
      <td className="py-2 pr-4 tabular-nums">
        {formatInr(txn.balance_after_paise)}
      </td>
      <td className="py-2 pr-4">
        <CdrReferenceCell cdrReference={txn.cdr_reference} />
      </td>
      <td className="py-2 pr-4 text-neutral-500">
        {formatDate(txn.created_at)}
      </td>
    </tr>
  );
}

function renderFailedRow(item: FailedRechargeItem) {
  return (
    <tr key={item.transaction_id} className="border-b border-neutral-100">
      <td className="py-2 pr-4 font-medium">{item.plan_attempted}</td>
      <td className="py-2 pr-4 tabular-nums">{formatInr(item.amount_paise)}</td>
      <td className="py-2 pr-4 text-neutral-600">
        {item.failure_reason ?? "—"}
      </td>
      <td className="py-2 pr-4 text-neutral-500">
        {formatDate(item.created_at)}
      </td>
    </tr>
  );
}

function RefundEligibleView() {
  const {
    data: failedItems = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["failed-recharges"],
    queryFn: getFailedRecharges,
  });

  return (
    <div className="mt-4 space-y-4">
      <div
        role="note"
        className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3"
      >
        <p className="text-sm text-amber-800">
          Actual refund processing is handled by the operator&apos;s billing
          team. Contact support for assistance.
        </p>
      </div>

      <div className="rounded-xl bg-white shadow p-6">
        {isLoading ? (
          <div className="animate-pulse h-40" />
        ) : isError ? (
          <div className="rounded-lg bg-red-50 border border-red-200 p-4">
            <p className="text-sm text-red-600">
              Failed to load refund-eligible transactions.
            </p>
          </div>
        ) : (
          <Table
            columns={FAILED_COLUMNS}
            rows={failedItems as FailedRechargeItem[]}
            renderRow={renderFailedRow}
            emptyState="No refund-eligible transactions found. Failed recharges appear here."
            caption="Refund-eligible failed recharges"
          />
        )}
      </div>
    </div>
  );
}

function Transactions() {
  const [showRefundEligible, setShowRefundEligible] = useState(false);

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

  return (
    <main className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-neutral-900">
        Transaction History
      </h1>
      <p className="mt-1 text-sm text-neutral-500">
        Every charge, recharge, and refund on your account (newest first).
      </p>

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => {
            setShowRefundEligible(false);
            // Preserve pagination state when switching back
          }}
          className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${
            !showRefundEligible
              ? "bg-indigo-600 text-white"
              : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
          }`}
        >
          All Transactions
        </button>
        <button
          type="button"
          onClick={() => {
            setShowRefundEligible(true);
            // Preserve pagination state when switching views
          }}
          className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-colors ${
            showRefundEligible
              ? "bg-amber-500 text-white"
              : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200"
          }`}
        >
          Refund-eligible
        </button>
      </div>

      {showRefundEligible ? (
        <RefundEligibleView />
      ) : (
        <div className="mt-4 rounded-xl bg-white shadow p-6">
          {isLoading ? (
            <div className="animate-pulse h-40" />
          ) : isError ? (
            <div className="rounded-lg bg-red-50 border border-red-200 p-4">
              <p className="text-sm text-red-600">
                Failed to load transactions.
              </p>
            </div>
          ) : (
            <>
              <Table
                columns={COLUMNS}
                rows={items}
                renderRow={renderRow}
                emptyState="No transactions yet."
                caption="Transaction ledger (newest first)"
              />
              <div className="mt-4 flex items-center justify-between">
                <button
                  type="button"
                  onClick={prevPage}
                  disabled={!hasPrev}
                  className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:text-neutral-300 disabled:hover:text-neutral-300"
                >
                  Previous
                </button>
                <button
                  type="button"
                  onClick={nextPage}
                  disabled={!hasNext || isFetching}
                  className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 disabled:text-neutral-300 disabled:hover:text-neutral-300"
                >
                  Next
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </main>
  );
}

export { Transactions };
