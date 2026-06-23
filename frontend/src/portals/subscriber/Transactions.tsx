/**
 * Transaction History page (Story 3.3).
 *
 * STUB — wired into /subscriber/history by the shared App.tsx route table so the
 * build stays green. The Story 3.3 implementation replaces this placeholder with
 * the real paginated ledger (useTransactions + Table + copyable CDR reference).
 */
function Transactions() {
  return (
    <main className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold text-neutral-900">
        Transaction History
      </h1>
      <p className="mt-2 text-sm text-neutral-500">Loading transactions...</p>
    </main>
  );
}

export { Transactions };
