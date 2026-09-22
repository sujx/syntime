import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntdApp } from "antd";
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
import GovernancePage from "@/pages/GovernancePage";
import { zh } from "@/i18n/zh";

// matchMedia / getComputedStyle 桩已提升至 src/test/setup.ts（多文件共用）

const summaryData = {
  total: 2,
  page: 1,
  pageSize: 20,
  resourceTypes: [
    { code: "ecs", displayName: "云服务器 ECS" },
    { code: "rds", displayName: "云数据库 RDS" },
  ],
  summary: {
    amountByResourceType: { ecs: "700.00", rds: "300.00" },
    totalAmount: "1000.00",
  },
  list: [
    {
      projectTag: "项目A",
      tagStatus: "normal",
      amountByResourceType: { ecs: "100.00", rds: "50.00" },
      totalAmount: "150.00",
      lastPeriodAmount: "100.00",
      lastPeriodRange: { start: "2026-08-01", end: "2026-08-31" },
      rate: "50.00",
      budgetAmount: "120.00",
      budgetRate: "125.00",
      overBudget: true,
      budgetIncomplete: false,
      statRange: { start: "2026-09-01", end: "2026-09-21" },
    },
    {
      projectTag: "未分配成本",
      tagStatus: null,
      amountByResourceType: {},
      totalAmount: "850.00",
      lastPeriodAmount: "--",
      lastPeriodRange: { start: "2026-08-01", end: "2026-08-31" },
      rate: "--",
      budgetAmount: "--",
      budgetRate: "--",
      overBudget: false,
      budgetIncomplete: false,
      statRange: { start: "2026-09-01", end: "2026-09-21" },
    },
  ],
};

function setup(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AntdApp>{ui}</AntdApp>
    </QueryClientProvider>,
  );
}

// Task 4 装配 TrendCard/DetailDrawer 后本页会并发请求 trend/details，
// 统一按 URL 分流返回，避免把汇总数据喂给趋势卡导致字段缺失崩溃
const trendData = {
  current: [],
  compare: [],
  statRange: { start: "2026-09-01", end: "2026-09-21" },
  compareRange: { start: "2026-08-01", end: "2026-08-21" },
  billMonthIncomplete: false,
};
function mockRoutes() {
  vi.mocked(get).mockImplementation((url: string) =>
    url === "/cost/trend/"
      ? Promise.resolve(trendData)
      : url === "/cost/details/"
        ? Promise.resolve({ total: 0, page: 1, pageSize: 20, list: [] })
        : Promise.resolve(summaryData),
  );
}

describe("GovernancePage 汇总", () => {
  it("首查默认本月区间并渲染动态列与合计标题区", async () => {
    mockRoutes();
    setup(<GovernancePage />);
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ startDate: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/) }),
      ),
    );
    // 使用 role 查询避免 MeasureRow 中重复的 th
    expect(
      await screen.findByRole("columnheader", { name: "云服务器 ECS费用" }),
    ).toBeInTheDocument();
    expect(screen.getByText(zh["gov.totalPrefix"] ?? "")).toBeInTheDocument();
    expect(await screen.findByText(/1000\.00/)).toBeInTheDocument();
    expect(screen.getByText("150.00")).toBeInTheDocument();
    // 未分配行金额为空字典 → 动态列显示 --
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });
  it("排序三态：升序→降序→取消", async () => {
    mockRoutes();
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    vi.mocked(get).mockClear();

    // 第一次点击：升序
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ sortField: "totalAmount", sortOrder: "asc" }),
      ),
    );
    vi.mocked(get).mockClear();

    // 第二次点击：降序
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ sortField: "totalAmount", sortOrder: "desc" }),
      ),
    );
    vi.mocked(get).mockClear();

    // 第三次点击：取消排序（无 sortField/sortOrder）
    await userEvent.click(screen.getByRole("columnheader", { name: /项目总支出/ }));
    await waitFor(() => expect(vi.mocked(get)).toHaveBeenCalled());
    const calls = vi.mocked(get).mock.calls;
    const lastArgs = calls[calls.length - 1]?.[1] as Record<string, unknown> | undefined;
    expect(lastArgs).toBeDefined();
    expect(lastArgs).not.toHaveProperty("sortField");
    expect(lastArgs).not.toHaveProperty("sortOrder");
  });
  it("关键字搜索提交后带 keyword 重查", async () => {
    mockRoutes();
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    vi.mocked(get).mockClear();
    await userEvent.type(screen.getByPlaceholderText(zh["gov.filterKeyword"] ?? ""), "A{Enter}");
    await waitFor(() =>
      expect(vi.mocked(get)).toHaveBeenCalledWith(
        "/cost/summary/",
        expect.objectContaining({ keyword: "A" }),
      ),
    );
  });
  it("点击行打开明细抽屉（Task 4 计划内演进：detail-anchor 已删除）", async () => {
    mockRoutes();
    setup(<GovernancePage />);
    await screen.findByText("150.00");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await userEvent.click(screen.getByText("项目A"));
    // 抽屉标题为「成本明细 · 项目A」组合串，用部分匹配断标题出现
    expect(await screen.findByText(new RegExp(zh["gov.detailTitle"] ?? ""))).toBeInTheDocument();
  });
});
