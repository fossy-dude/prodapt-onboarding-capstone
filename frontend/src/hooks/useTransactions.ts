import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getTransactions,
  type TransactionItem,
  type TransactionsPage,
} from "../lib/api";

export const TRANSACTIONS_QUERY_KEY = ["transactions"] as const;

/**
 * Cursor-paginated transaction ledger with forward/back navigation.
 *
 * A stack of visited cursors is maintained (index 0 = first page, no cursor) so
 * "Prev" is well-defined: it moves back through pages already fetched. "Next"
 * uses the current page's `nextCursor` and is a no-op when there is none.
 */
function useTransactions() {
  const [cursorStack, setCursorStack] = useState<
    readonly (string | undefined)[]
  >([undefined]);
  const [pageIndex, setPageIndex] = useState(0);

  const cursor = cursorStack[pageIndex];

  const query = useQuery<TransactionsPage, Error>({
    queryKey: [...TRANSACTIONS_QUERY_KEY, cursor ?? "first"],
    queryFn: () => getTransactions({ cursor }),
  });

  const nextCursor = query.data?.nextCursor ?? null;
  const hasNext = nextCursor !== null;
  const hasPrev = pageIndex > 0;

  function nextPage() {
    if (!hasNext || nextCursor === null) return;
    setCursorStack((prev) => {
      const updated = [...prev];
      updated[pageIndex + 1] = nextCursor;
      return updated;
    });
    setPageIndex((index) => index + 1);
  }

  function prevPage() {
    if (!hasPrev) return;
    setPageIndex((index) => index - 1);
  }

  const items: readonly TransactionItem[] = query.data?.items ?? [];

  return {
    items,
    nextCursor,
    hasNext,
    hasPrev,
    nextPage,
    prevPage,
    pageIndex,
    isLoading: query.isLoading,
    isError: query.isError,
  };
}

export { useTransactions };
