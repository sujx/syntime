import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("@/api/client", () => ({ get: vi.fn(), post: vi.fn() }));

import { get, post } from "@/api/client";
import { useDashboard } from "@/features/dashboard/hooks";
import { useEventList, useEventStatus, useEventTabCounts } from "@/features/events/hooks";
import { useDetails, useSummary } from "@/features/governance/hooks";

const mockedGet = vi.mocked(get);
const mockedPost = vi.mocked(post);

beforeEach(() => {
  mockedGet.mockReset();
  mockedPost.mockReset();
});

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("governance hooks", () => {
  it("useSummary 把 filters 原样作为查询参数", async () => {
    mockedGet.mockResolvedValue({
      total: 0,
      page: 1,
      pageSize: 20,
      list: [],
      resourceTypes: [],
      summary: { amountByResourceType: {}, totalAmount: "0.00" },
    });
    const { result } = renderHook(
      () =>
        useSummary({
          startDate: "2026-09-01",
          endDate: "2026-09-30",
          keyword: "A",
          sortField: "totalAmount",
          sortOrder: "desc",
        }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockedGet).toHaveBeenCalledWith(
      "/cost/summary/",
      expect.objectContaining({ startDate: "2026-09-01", keyword: "A" }),
    );
  });
  it("区间未就绪时不发请求", () => {
    renderHook(() => useSummary({ startDate: "", endDate: "" }), { wrapper });
    expect(mockedGet).not.toHaveBeenCalled();
  });
  it("useDetails 组装 projectTag+tagStatus+分页", async () => {
    mockedGet.mockResolvedValue({ total: 0, page: 1, pageSize: 20, list: [] });
    renderHook(
      () => useDetails("A", "normal", { startDate: "2026-09-01", endDate: "2026-09-30" }, 2),
      { wrapper },
    );
    await waitFor(() => expect(mockedGet).toHaveBeenCalled());
    expect(mockedGet).toHaveBeenLastCalledWith(
      "/cost/details/",
      expect.objectContaining({ projectTag: "A", tagStatus: "normal", page: 2 }),
    );
  });
});

describe("events hooks", () => {
  it("useEventList 传 params；tabCount 用 pageSize=1", async () => {
    mockedGet.mockResolvedValue({ total: 0, page: 1, pageSize: 20, list: [], unreadCount: 3 });
    renderHook(() => useEventList({ status: "unread", page: 1 }), { wrapper });
    renderHook(() => useEventTabCounts(), { wrapper });
    await waitFor(() => expect(mockedGet).toHaveBeenCalledTimes(6));
    expect(mockedGet).toHaveBeenCalledWith(
      "/events/",
      expect.objectContaining({ status: "unread" }),
    );
    expect(mockedGet).toHaveBeenCalledWith(
      "/events/",
      expect.objectContaining({ pageSize: 1, status: "read" }),
    );
  });
  it("useEventStatus 成功后失效 events 前缀（徽标联动）", async () => {
    const spy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    mockedPost.mockResolvedValue(null);
    const { result } = renderHook(() => useEventStatus(), { wrapper });
    result.current.mutate({ eventIds: [1], action: "read" });
    await waitFor(() =>
      expect(mockedPost).toHaveBeenCalledWith("/events/status/", { eventIds: [1], action: "read" }),
    );
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["events"] }));
  });
});

describe("dashboard hook", () => {
  it("useDashboard 命中 /dashboard/", async () => {
    mockedGet.mockResolvedValue({
      cards: {},
      trend: {
        current: [],
        compare: [],
        statRange: { start: "", end: "" },
        compareRange: { start: "", end: "" },
        billMonthIncomplete: false,
      },
      syncStatus: { accounts: [], lastAggregateTime: null },
    });
    renderHook(() => useDashboard(), { wrapper });
    await waitFor(() => expect(mockedGet).toHaveBeenCalledWith("/dashboard/"));
  });
});
