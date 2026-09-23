import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

vi.mock("@/api/client", () => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/components/chart/ChartCard", () => ({
  ChartCard: ({ title }: { title: string }) => <div data-testid={`chart:${title}`} />,
}));
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({
    username: "alice",
    role: "成本管理员",
    status: "authenticated",
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

import { get } from "@/api/client";
import type { SyncAccount } from "@/api/types";
import DashboardPage from "@/pages/DashboardPage";
import { zh } from "@/i18n/zh";
import { localText } from "@/test/localTime";

const data = {
  cards: {
    cloudAccountTotal: 3,
    enabled: 2,
    disabled: 1,
    assetTotal: 10,
    running: 8,
    stopped: 2,
    monthAmount: "123456.78",
    monthRate: "12.34",
    isEstimate: true,
    unallocatedAmount: "999.00",
    unallocatedRatio: "1.25",
    eventPending: 7,
    eventHigh: 2,
    eventWarning: 3,
  },
  trend: {
    current: [],
    compare: [],
    statRange: { start: "2026-08-23", end: "2026-09-21" },
    compareRange: { start: "2026-07-24", end: "2026-08-22" },
    billMonthIncomplete: true,
  },
  syncStatus: {
    accounts: [
      {
        accountName: "prod-main",
        vendor: "aliyun",
        lastSyncTime: "2026-09-20T18:30:00Z",
        status: "success",
      },
    ],
    lastAggregateTime: "2026-09-20T19:00:00Z",
  },
};

function setup(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function account(accountName: string, status: string | null, vendor = "aliyun"): SyncAccount {
  return {
    accountName,
    vendor,
    lastSyncTime: status === null ? null : "2026-09-20T18:30:00Z",
    status,
  };
}

function renderAccounts(accounts: SyncAccount[]) {
  vi.mocked(get).mockResolvedValue({
    ...data,
    syncStatus: { lastAggregateTime: null, accounts },
  });
  setup(<DashboardPage />);
}

describe("DashboardPage", () => {
  it("渲染五张 KPI 卡与关键数值、预估标注", async () => {
    vi.mocked(get).mockResolvedValue(data);
    setup(<DashboardPage />);
    expect(await screen.findByText("123456.78")).toBeInTheDocument();
    expect(screen.getByText(zh["dash.kpiCloud"] ?? "")).toBeInTheDocument();
    expect(screen.getByText(zh["dash.kpiEvent"] ?? "")).toBeInTheDocument();
    expect(screen.getByText(zh["dash.estimateTag"] ?? "")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument(); // 待处理事件=未读
    expect(screen.getByTestId(`chart:${zh["dash.trendTitle"]}`)).toBeInTheDocument();
    expect(screen.getByText("prod-main")).toBeInTheDocument();
    // 同步块两处时间都按本地时区渲染；后端序列化的是 UTC，不可直接切片
    expect(screen.getByText(localText("2026-09-20T19:00:00Z"))).toBeInTheDocument();
    expect(screen.getByText(localText("2026-09-20T18:30:00Z"))).toBeInTheDocument();
  });
  it("状态为空（无同步记录）的账号圆点取中性灰，不得显示为成功绿", async () => {
    vi.mocked(get).mockResolvedValue({
      ...data,
      syncStatus: {
        lastAggregateTime: null,
        accounts: [
          { accountName: "prod-none", vendor: "aliyun", lastSyncTime: null, status: null },
        ],
      },
    });
    setup(<DashboardPage />);
    const dot = await screen.findByTestId("sync-dot-aliyun-prod-none");
    expect(dot.style.background).toBe("var(--gray-400)");
  });
  it("同步成功/同步中/同步失败三态圆点取 design.md 语义色 Token", async () => {
    renderAccounts([
      account("acc-ok", "success"),
      account("acc-syncing", "running"),
      account("acc-failed", "failed"),
    ]);
    expect((await screen.findByTestId("sync-dot-aliyun-acc-ok")).style.background).toBe(
      "var(--success-500)",
    );
    expect(screen.getByTestId("sync-dot-aliyun-acc-syncing").style.background).toBe(
      "var(--warning-500)",
    );
    expect(screen.getByTestId("sync-dot-aliyun-acc-failed").style.background).toBe(
      "var(--danger-500)",
    );
  });
  it("状态文字随圆点四态显示", async () => {
    renderAccounts([
      account("acc-ok", "success"),
      account("acc-syncing", "running"),
      account("acc-failed", "failed"),
      account("acc-none", null),
    ]);
    await screen.findByTestId("sync-row-aliyun-acc-ok");
    const stateText = (name: string) =>
      screen.getByTestId(`sync-row-aliyun-${name}`).textContent ?? "";
    expect(stateText("acc-ok")).toContain(zh["dash.syncOk"]);
    expect(stateText("acc-syncing")).toContain(zh["dash.syncRunning"]);
    expect(stateText("acc-failed")).toContain(zh["dash.syncFail"]);
    expect(stateText("acc-none")).toContain(zh["dash.syncNone"]);
  });
  it("同步中圆点带 dotRunning 修饰类（动画本体由浏览器实测覆盖）", async () => {
    renderAccounts([account("acc-syncing", "running")]);
    const dot = await screen.findByTestId("sync-dot-aliyun-acc-syncing");
    expect(dot.className).toContain("dotRunning");
  });
  it("跨厂商同名账号不产生重复 key", async () => {
    const spy = vi.spyOn(console, "error");
    renderAccounts([account("prod", "success"), account("prod", "failed", "tencent")]);
    expect(await screen.findAllByText("prod")).toHaveLength(2);
    const dupKey = spy.mock.calls.map((c) => String(c[0])).filter((m) => m.includes("same key"));
    expect(dupKey).toEqual([]);
  });
  it("接口失败展示重试入口", async () => {
    vi.mocked(get).mockRejectedValue(new Error("boom"));
    setup(<DashboardPage />);
    expect(await screen.findByText(zh["common.loadFail"] ?? "")).toBeInTheDocument();
    expect(screen.getByText(zh["common.retry"] ?? "")).toBeInTheDocument();
  });
});
