import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";

import { useBalance } from "./useBalance";

vi.mock("../lib/api", () => ({
  getBalance: vi.fn(),
}));

const { getBalance } = await import("../lib/api");

const BALANCE_DATA = {
  subscriber_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  msisdn_masked: "***3210",
  balance_paise: 50000,
  balance_inr: "₹500.00",
  last_updated_at: null,
};

function wrapper({ children }: { readonly children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client: qc }, children);
}

describe("useBalance", () => {
  beforeEach(() => {
    vi.mocked(getBalance).mockReset();
  });

  it("returns balance data on success", async () => {
    vi.mocked(getBalance).mockResolvedValue(BALANCE_DATA);
    const { result } = renderHook(() => useBalance(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.balance_paise).toBe(50000);
    expect(result.current.data?.balance_inr).toBe("₹500.00");
  });

  it("returns error on fetch failure", async () => {
    vi.mocked(getBalance).mockRejectedValue(new Error("Network error"));
    const { result } = renderHook(() => useBalance(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
