import MockAdapter from "axios-mock-adapter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/client";
import { useUnreadBadge } from "../useUnreadBadge";

let mock: MockAdapter;
beforeEach(() => {
  mock = new MockAdapter(api);
});
afterEach(() => {
  mock.restore();
});

const wrapper = ({ children }: { children: ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
};

const page = (unreadCount: number) => ({
  code: 0,
  message: "ok",
  data: { total: 0, page: 1, pageSize: 1, list: [], unreadCount },
});

describe("useUnreadBadge", () => {
  it("读取 events 响应的 unreadCount", async () => {
    mock.onGet("/events/?page=1&pageSize=1").reply(200, page(3));
    const { result } = renderHook(() => useUnreadBadge(true), { wrapper });
    await waitFor(() => expect(result.current).toBe(3));
  });
  it("忽略 list 内容只看 unreadCount", async () => {
    mock.onGet(/\/events\//).reply(200, {
      code: 0,
      message: "ok",
      data: { total: 999, page: 1, pageSize: 1, list: [{ junk: true }], unreadCount: 12 },
    });
    const { result } = renderHook(() => useUnreadBadge(true), { wrapper });
    await waitFor(() => expect(result.current).toBe(12));
  });
  it("disabled 时不发请求返回 0", async () => {
    const hits = vi.fn().mockReturnValue([200, page(7)]);
    mock.onGet(/\/events\//).reply(hits);
    const { result } = renderHook(() => useUnreadBadge(false), { wrapper });
    expect(result.current).toBe(0);
    await new Promise((r) => setTimeout(r, 50));
    expect(hits).not.toHaveBeenCalled();
  });
  it("40300 等错误时查询进入 error 态且徽标值归零（财务角色接口可用，此为防御）", async () => {
    mock.onGet(/\/events\//).reply(200, { code: 40300, message: "无权限", data: null });
    // 独立可控的 QueryClient：先确认查询真正进入 error 态，再断言徽标归零，
    // 避免 t=0（pending、data 尚为 undefined）时 expect(0) 空真
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { result } = renderHook(() => useUnreadBadge(true), {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={qc}>{children}</QueryClientProvider>
      ),
    });
    await waitFor(() =>
      expect(qc.getQueryCache().find({ queryKey: ["events", "unread-badge"] })?.state.status).toBe(
        "error",
      ),
    );
    expect(result.current).toBe(0);
  });
});
