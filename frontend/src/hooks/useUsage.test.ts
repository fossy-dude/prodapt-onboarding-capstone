import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";

import { useUsage } from "./useUsage";

vi.mock("../lib/api", () => ({
  getUsage: vi.fn(),
}));

const { getUsage } = await import("../lib/api");

const USAGE_DATA = {
  subscriber_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  plan_period: { start: "2026-01-01T00:00:00Z", end: "2026-01-29T00:00:00Z" },
  voice_minutes: { used: 120, allowance: 600, unlimited: false },
  data_mb: 2048,
  data_gb: 2,
  data: { used: 2048, allowance: 10240, unlimited: false },
  sms: { used: 30, allowance: 100, unlimited: false },
  roaming_mb: { used: 0, allowance: null, unlimited: true },
};

function wrapper({ children }: { readonly children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createElement(QueryClientProvider, { client: qc }, children);
}

describe("useUsage", () => {
  beforeEach(() => {
    vi.mocked(getUsage).mockReset();
  });

  it("returns usage data with per-type breakdown", async () => {
    vi.mocked(getUsage).mockResolvedValue(USAGE_DATA);
    const { result } = renderHook(() => useUsage(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.voice_minutes.used).toBe(120);
    expect(result.current.data?.roaming_mb.unlimited).toBe(true);
  });

  it("returns error on fetch failure", async () => {
    vi.mocked(getUsage).mockRejectedValue(new Error("Network error"));
    const { result } = renderHook(() => useUsage(), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
